"""RN-05 a RN-10 y RNF-02 · liquidación de regalías por país como funciones puras (EG-23).

Datos entran, datos salen: sin archivos, BD, red ni reloj del sistema. Las fechas, los ingresos,
las tasas de cambio y los contratos llegan como argumentos, para que la EG-24 (esqueleto) y la
EG-37 (Spark) reutilicen la misma lógica. La salida es el contrato de la EG-21: `FilaReporte`.

Flujo de un país y un mes:

1. `paises_facturacion` + `suscripcion_neta_por_pais` (RN-10, Q5, Q6): un solo pago por familia,
   atribuido al país de facturación del titular de la familia.
2. `convertir_a_usd` (moneda local → USD con la tasa del último día del mes).
3. `calcular_bolsa` (Q8): dos componentes con denominadores separados.
4. `liquidar_pais`: % vigente por reproducción (RN-07), condición territorial (Q7), exclusión
   (RN-08, con incidente), filas por (titular, componente, %) y reparto al centavo (RNF-02).

Dinero siempre en `Decimal`; se redondea en un solo sitio: `_repartir_centavos`.
"""

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_DOWN, ROUND_HALF_UP, Decimal
from enum import StrEnum

from sonoraplay.config import ReglasLiquidacionConfig
from sonoraplay.reporte_regalias import (
    CENTAVO,
    ESCALA_PARTICIPACION,
    Componente,
    FilaReporte,
    redondear_usd,
)

CIEN = Decimal(100)
TOLERANCIA_USD = CENTAVO  # RNF-02: ± 0,01 USD


# --- Entradas ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class CondicionContrato:
    """Una fila de F4 (`contratos`) con sus exclusiones (`exclusiones_territoriales`).

    `valido_desde` y `valido_hasta` son **inclusivos**, igual que en el DDL 002
    (`daterange(desde, hasta + 1, '[)')`): un contrato del 50 % con `valido_hasta` = 14 cubre
    todo el día 14 UTC, y el del 40 % con `valido_desde` = 15 empieza a las 00:00 UTC del 15.
    `territorio` None = condición general; un país = condición territorial (Q7).
    """

    contrato_id: uuid.UUID
    titular_id: uuid.UUID
    track_id: str
    porcentaje: Decimal  # de 0 a 100, como contratos.porcentaje
    valido_desde: date
    valido_hasta: date | None = None
    territorio: str | None = None
    exclusiones: frozenset[str] = frozenset()

    def __post_init__(self) -> None:
        if not isinstance(self.porcentaje, Decimal):
            raise TypeError("porcentaje debe ser Decimal (no float: se pierden centavos)")
        if not 0 <= self.porcentaje <= CIEN:
            raise ValueError(f"porcentaje fuera de rango: {self.porcentaje}")
        if self.valido_hasta is not None and self.valido_hasta < self.valido_desde:
            raise ValueError("valido_hasta no puede ser anterior a valido_desde")
        object.__setattr__(self, "exclusiones", frozenset(self.exclusiones))

    def vigente_en(self, fecha: date) -> bool:
        """RN-07: vigente si `valido_desde <= fecha <= valido_hasta` (ambos inclusivos)."""
        return self.valido_desde <= fecha and (
            self.valido_hasta is None or fecha <= self.valido_hasta
        )


@dataclass(frozen=True)
class ReproduccionLiquidable:
    """Reproducción ya **válida y pagable** (RN-01, RN-02 y RN-03 aplicadas antes).

    `pais_facturacion` define la bolsa (Q6, sale de `paises_facturacion`); `pais_reproduccion`
    solo decide la condición territorial (Q7) y la exclusión (RN-08). `inicio` debe ser aware;
    se normaliza a UTC y su fecha UTC decide el % vigente (RN-07, ADR-0002). No se valida que
    `inicio` caiga en el período: un ajuste de la EG-22 trae reproducciones de meses anteriores
    y cada una usa el % de su propia fecha.
    """

    reproduccion_id: str
    usuario_id: str
    titular_id: uuid.UUID
    track_id: str
    inicio: datetime
    pais_facturacion: str
    pais_reproduccion: str | None
    componente: Componente

    def __post_init__(self) -> None:
        if self.inicio.tzinfo is None or self.inicio.utcoffset() is None:
            raise ValueError(f"inicio debe ser un datetime aware en UTC (ADR-0002): {self.inicio}")
        object.__setattr__(self, "inicio", self.inicio.astimezone(UTC))
        Componente(self.componente)

    @property
    def fecha(self) -> date:
        return self.inicio.date()


@dataclass(frozen=True)
class Pago:
    """Pago de F3 (`pagos` unido a `suscripciones.usuario_id`). En un plan familiar solo paga
    el titular de la familia: es el único pago que se reparte entre todos los miembros (RN-10)."""

    usuario_id: str
    monto_usd: Decimal
    estado: str  # 'aprobado' | 'rechazado'


@dataclass(frozen=True)
class TasaCambio:
    """Tasa de F6: cuántas unidades de `moneda` vale 1 USD en `fecha` (p. ej. 4.000 COP)."""

    moneda: str
    fecha: date
    unidades_por_usd: Decimal

    def __post_init__(self) -> None:
        if not isinstance(self.unidades_por_usd, Decimal):
            raise TypeError("unidades_por_usd debe ser Decimal")
        if self.unidades_por_usd <= 0:
            raise ValueError("unidades_por_usd debe ser positiva")


# --- Salidas ----------------------------------------------------------------------------------


class TipoIncidente(StrEnum):
    TERRITORIO_EXCLUIDO = "territorio_excluido"  # RN-08
    SIN_CONDICION_VIGENTE = "sin_condicion_vigente"  # pista sin contrato en esa fecha


@dataclass(frozen=True)
class Incidente:
    """Registro de incidente devuelto como dato. Quien orquesta decide dónde guardarlo."""

    tipo: TipoIncidente
    reproduccion_id: str
    titular_id: uuid.UUID
    track_id: str
    fecha: date
    pais_reproduccion: str | None
    contrato_id: uuid.UUID | None


@dataclass(frozen=True)
class BolsaPais:
    """Bolsa de un país en USD, sin redondear (el redondeo es solo por fila)."""

    pais: str
    suscripcion: Decimal
    publicidad: Decimal

    @property
    def total(self) -> Decimal:
        return self.suscripcion + self.publicidad

    def de(self, componente: Componente) -> Decimal:
        return self.suscripcion if componente == Componente.SUSCRIPCION else self.publicidad


@dataclass(frozen=True)
class ResultadoLiquidacion:
    periodo: date
    bolsa: BolsaPais
    filas: tuple[FilaReporte, ...]
    incidentes: tuple[Incidente, ...]

    def total_usd(self, componente: Componente | None = None) -> Decimal:
        return sum(
            (f.regalia_usd for f in self.filas if componente in (None, f.componente)),
            Decimal(0),
        )

    def total_titular(self, titular_id: uuid.UUID) -> Decimal:
        return sum((f.regalia_usd for f in self.filas if f.titular_id == titular_id), Decimal(0))


# --- Ingresos y bolsa -------------------------------------------------------------------------


def paises_facturacion(
    pais_de_usuario: Mapping[str, str | None], titular_de_familia: Mapping[str, str]
) -> dict[str, str]:
    """Q6 / RN-10: país de la bolsa de cada usuario.

    Un miembro de familia usa el país de facturación del **titular** de su familia, aunque el
    suyo sea otro. `titular_de_familia` va de miembro a titular (`miembros_familia` +
    `grupos_familiares`). Un país nulo es un defecto del seed F3 que se depura en Silver: aquí
    lanza ValueError en vez de inventar un país.
    """
    resultado: dict[str, str] = {}
    for usuario in pais_de_usuario:
        titular = titular_de_familia.get(usuario, usuario)
        pais = pais_de_usuario.get(titular)
        if pais is None:
            raise ValueError(f"usuario {usuario}: país de facturación nulo (titular {titular})")
        resultado[usuario] = pais
    return resultado


def suscripcion_neta_por_pais(
    pagos: Iterable[Pago], pais_de_usuario: Mapping[str, str]
) -> dict[str, Decimal]:
    """Q5: suscripción neta = suma de `pagos.monto_usd` con estado 'aprobado', por país (Q6).

    Cada pago cuenta **una vez**: el pago familiar entra una sola vez a la bolsa del país del
    titular y se reparte entre las reproducciones de todos los miembros (RN-10).
    """
    totales: dict[str, Decimal] = defaultdict(Decimal)
    for p in pagos:
        if not isinstance(p.monto_usd, Decimal):
            raise TypeError("monto_usd debe ser Decimal")
        if p.estado == "aprobado":
            totales[pais_de_usuario[p.usuario_id]] += p.monto_usd
    return dict(totales)


def ultimo_dia_del_mes(periodo: date) -> date:
    siguiente = (periodo.replace(day=28) + timedelta(days=4)).replace(day=1)
    return siguiente - timedelta(days=1)


def convertir_a_usd(monto: Decimal, moneda: str, tasa: TasaCambio, periodo: date) -> Decimal:
    """Moneda local → USD con la tasa del **último día del mes** del período.

    Una tasa de otra fecha o de otra moneda lanza ValueError. No redondea: el monto entra
    exacto a la bolsa y solo se redondea la regalía de cada fila.
    """
    if not isinstance(monto, Decimal):
        raise TypeError("monto debe ser Decimal")
    if tasa.moneda != moneda:
        raise ValueError(f"tasa de {tasa.moneda} para un monto en {moneda}")
    cierre = ultimo_dia_del_mes(periodo)
    if tasa.fecha != cierre:
        raise ValueError(f"la tasa debe ser la del {cierre} (último día del mes), no {tasa.fecha}")
    return monto / tasa.unidades_por_usd


def calcular_bolsa(
    pais: str,
    suscripcion_neta_usd: Decimal,
    publicidad_usd: Decimal,
    cfg: ReglasLiquidacionConfig,
) -> BolsaPais:
    """Q8: suscripción = 52 % × suscripción neta; publicidad = 45 % × ingresos publicitarios."""
    for nombre, valor in (("suscripcion", suscripcion_neta_usd), ("publicidad", publicidad_usd)):
        if not isinstance(valor, Decimal):
            raise TypeError(f"{nombre} debe ser Decimal (no float: se pierden centavos)")
        if valor < 0:
            raise ValueError(f"{nombre} no puede ser negativo")
    return BolsaPais(
        pais=pais,
        suscripcion=suscripcion_neta_usd * cfg.fraccion_suscripcion,
        publicidad=publicidad_usd * cfg.fraccion_publicidad,
    )


# --- % aplicable ------------------------------------------------------------------------------

Condiciones = Mapping[tuple[uuid.UUID, str], Sequence[CondicionContrato]]


def indexar_condiciones(
    condiciones: Iterable[CondicionContrato],
) -> dict[tuple[uuid.UUID, str], list[CondicionContrato]]:
    """Agrupa las condiciones por (titular, pista) para buscarlas por reproducción."""
    indice: dict[tuple[uuid.UUID, str], list[CondicionContrato]] = defaultdict(list)
    for c in condiciones:
        indice[(c.titular_id, c.track_id)].append(c)
    return dict(indice)


def porcentaje_aplicable(
    rep: ReproduccionLiquidable, condiciones: Condiciones
) -> tuple[Decimal, CondicionContrato | None, Incidente | None]:
    """% de una reproducción en su fecha UTC. Misma precedencia que
    `api_contratos.services.elegir_condicion` (se prueba la paridad):

    1. RN-07: solo las condiciones vigentes en `rep.fecha`.
    2. RN-08: si el país de reproducción está excluido en la condición general → 0 % e incidente.
    3. Q7: si hay condición territorial para ese país, se usa.
    4. Si no, la condición general. Sin condición vigente → 0 % e incidente.
    """
    vigentes = [
        c for c in condiciones.get((rep.titular_id, rep.track_id), ()) if c.vigente_en(rep.fecha)
    ]
    generales = [c for c in vigentes if c.territorio is None]
    if len(generales) > 1:
        raise ValueError(f"condiciones generales solapadas para {rep.track_id} en {rep.fecha}")
    general = generales[0] if generales else None
    pais = rep.pais_reproduccion

    def incidente(tipo: TipoIncidente, c: CondicionContrato | None) -> Incidente:
        return Incidente(
            tipo=tipo,
            reproduccion_id=rep.reproduccion_id,
            titular_id=rep.titular_id,
            track_id=rep.track_id,
            fecha=rep.fecha,
            pais_reproduccion=pais,
            contrato_id=c.contrato_id if c else None,
        )

    if general is not None and pais is not None and pais in general.exclusiones:
        return Decimal(0), general, incidente(TipoIncidente.TERRITORIO_EXCLUIDO, general)
    territorial = next((c for c in vigentes if pais is not None and c.territorio == pais), None)
    elegida = territorial or general
    if elegida is None:
        return Decimal(0), None, incidente(TipoIncidente.SIN_CONDICION_VIGENTE, None)
    return elegida.porcentaje, elegida, None


# --- Liquidación de un país -------------------------------------------------------------------


def liquidar_pais(
    periodo: date,
    bolsa: BolsaPais,
    reproducciones: Iterable[ReproduccionLiquidable],
    condiciones: Condiciones,
) -> ResultadoLiquidacion:
    """Liquida un país en un mes y devuelve las filas del reporte y los incidentes.

    - Solo cuentan las reproducciones cuyo `pais_facturacion` es `bolsa.pais` (Q6).
    - Denominadores separados por componente (Q8): las del plan gratuito nunca entran al de
      suscripción y viceversa.
    - Una reproducción excluida (RN-08) o sin contrato **sí** cuenta en el denominador y queda en
      una fila con 0 %: paga 0, y su parte de la bolsa no se reparte a otros titulares.
    - Una fila por (titular, componente, %): si el % cambió a mitad de mes (RN-07) hay una fila
      por cada %, con `regalia = bolsa × participación × % / 100`.
    """
    if periodo.day != 1:
        raise ValueError("periodo debe ser el primer día del mes")
    conteos: dict[tuple[Componente, uuid.UUID, Decimal], int] = defaultdict(int)
    incidentes: list[Incidente] = []
    vistos: set[str] = set()
    for rep in reproducciones:
        if rep.pais_facturacion != bolsa.pais:
            continue
        if rep.reproduccion_id in vistos:
            raise ValueError(f"reproduccion_id repetido: {rep.reproduccion_id}")
        vistos.add(rep.reproduccion_id)
        pct, _, inc = porcentaje_aplicable(rep, condiciones)
        if inc is not None:
            incidentes.append(inc)
        conteos[(rep.componente, rep.titular_id, pct)] += 1

    return repartir_bolsa(periodo, bolsa, conteos, incidentes)


def repartir_bolsa(
    periodo: date,
    bolsa: BolsaPais,
    conteos: Mapping[tuple[Componente, uuid.UUID, Decimal], int],
    incidentes: Sequence[Incidente] = (),
) -> ResultadoLiquidacion:
    """Reparte la bolsa de un país a partir de los **conteos** por (componente, titular, %).

    Es la segunda mitad de `liquidar_pais`, separada para que el job de Spark (EG-37) cuente las
    reproducciones de forma distribuida y reparta con exactamente esta misma aritmética (mismo
    redondeo al centavo, RNF-02). El denominador de cada componente es la suma de sus conteos.
    """
    totales: dict[Componente, int] = defaultdict(int)
    for (componente, _, _), n in conteos.items():
        totales[componente] += n
    filas: list[FilaReporte] = []
    for componente in Componente:
        claves = sorted(
            (k for k in conteos if k[0] == componente), key=lambda k: (str(k[1]), -k[2])
        )
        if not claves:
            continue  # sin reproducciones: no hay a quién repartir ni división por cero
        total = totales[componente]
        exactos = [bolsa.de(componente) * conteos[k] * k[2] / (CIEN * total) for k in claves]
        for k, regalia in zip(claves, _repartir_centavos(exactos), strict=True):
            _, titular, pct = k
            filas.append(
                FilaReporte(
                    titular_id=titular,
                    periodo=periodo,
                    pais=bolsa.pais,
                    componente=componente,
                    reproducciones_validas=conteos[k],
                    # Solo informativa: la regalía usa la participación sin redondear.
                    participacion=(Decimal(conteos[k]) / total).quantize(
                        ESCALA_PARTICIPACION, rounding=ROUND_HALF_UP
                    ),
                    porcentaje_contractual=pct.quantize(CENTAVO),
                    regalia_usd=regalia,
                )
            )
    resultado = ResultadoLiquidacion(periodo, bolsa, tuple(filas), tuple(incidentes))
    verificar_invariantes(resultado)
    return resultado


def _repartir_centavos(exactos: Sequence[Decimal]) -> list[Decimal]:
    """Único punto de redondeo de la liquidación (RNF-02), por método del mayor residuo.

    Redondear cada fila por separado con ROUND_HALF_UP puede hacer que la suma supere la bolsa
    (p. ej. 3 filas de 33,335 → 3 × 33,34 = 100,02 > 100,005). Por eso:
    1. cada fila se trunca al centavo (ROUND_DOWN);
    2. el total objetivo es `redondear_usd(suma exacta)`, que nunca supera la bolsa en más de
       0,005 USD porque la suma exacta es ≤ bolsa (los % son ≤ 100);
    3. los centavos que faltan para llegar al objetivo van, de a uno, a las filas con mayor
       residuo; los empates se rompen por el orden de entrada (titular, %), así que el
       resultado es determinista.
    Cada fila queda a menos de 0,01 USD de su valor exacto y la suma por componente es
    exactamente `redondear_usd(suma exacta)`. Una fila con valor exacto 0 (0 %) nunca recibe
    un centavo: solo hay tantos centavos por repartir como filas con residuo > 0.
    """
    pisos = [e.quantize(CENTAVO, rounding=ROUND_DOWN) for e in exactos]
    objetivo = redondear_usd(sum(exactos, Decimal(0)))
    faltan = int((objetivo - sum(pisos, Decimal(0))) / CENTAVO)
    orden = sorted(range(len(exactos)), key=lambda i: -(exactos[i] - pisos[i]))
    for i in orden[:faltan]:
        pisos[i] += CENTAVO
    return pisos


def verificar_invariantes(resultado: ResultadoLiquidacion) -> None:
    """RNF-02: la suma de regalías no supera ninguno de los dos componentes ni la bolsa total
    del país, con tolerancia de ± 0,01 USD. Lanza ValueError si se viola."""
    bolsa = resultado.bolsa
    for componente in Componente:
        suma = resultado.total_usd(componente)
        if suma > bolsa.de(componente) + TOLERANCIA_USD:
            raise ValueError(f"RNF-02: {componente} {suma} > bolsa {bolsa.de(componente)}")
    if resultado.total_usd() > bolsa.total + TOLERANCIA_USD:
        raise ValueError(f"RNF-02: total {resultado.total_usd()} > bolsa {bolsa.total}")
