"""EG-37 · Insumos de Gold que salen de RDS: usuarios (F3), contratos (F4) y bolsas (F3, F5, F6).

Sin Spark: son pocas filas (usuarios, contratos) o agregados (bolsas) y se reutilizan las
funciones puras de la EG-23 (``paises_facturacion``, ``suscripcion_neta_por_pais``,
``convertir_a_usd``, ``calcular_bolsa``). Nada se inventa: lo que no se puede asignar se
**devuelve como excluido** para que el job lo informe, y Gold falla si una reproducción pagable
queda sin país.

Supuestos que conviene revisar con el equipo (también en ``docs/servicios/liquidacion-spark.md``):

- **Componente del usuario (Q8):** plan de la suscripción vigente el último día del mes (o, si ya
  terminó dentro del mes, la que terminó más tarde). ``free`` → ``publicidad``; el resto →
  ``suscripcion``. Un cambio de plan a mitad de mes no parte las reproducciones del usuario.
- **Suscripción neta (Q5):** pagos ``aprobado`` con ``fecha_pago`` dentro del mes, por país de
  facturación del que paga (Q6, RN-10).
- **Publicidad (F5):** ``ingresos_publicidad`` del mes en moneda local, a USD con la tasa de
  cierre de F6 del último día del mes (``fuente_f6_cierres``). ``USD`` no necesita tasa.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal

from sonoraplay.config import ReglasLiquidacionConfig
from sonoraplay.reglas.liquidacion import (
    BolsaPais,
    CondicionContrato,
    Pago,
    TasaCambio,
    calcular_bolsa,
    convertir_a_usd,
    paises_facturacion,
    suscripcion_neta_por_pais,
    ultimo_dia_del_mes,
)
from sonoraplay.reporte_regalias import Componente
from sonoraplay.spark.gold import condiciones_desde_filas


@dataclass
class InsumosUsuarios:
    """País de facturación y componente por usuario, más lo que no se pudo asignar."""

    filas: list[tuple[str, str, str]] = field(default_factory=list)  # user_id, país, componente
    sin_pais: list[str] = field(default_factory=list)
    sin_suscripcion: list[str] = field(default_factory=list)


def _mes_siguiente(periodo: date) -> date:
    return ultimo_dia_del_mes(periodo) + timedelta(days=1)


def _validar_periodo(periodo: date) -> None:
    if periodo.day != 1:
        raise ValueError("periodo debe ser el primer día del mes")


def _paises_por_usuario(conexion) -> tuple[dict[str, str], list[str]]:
    """País de facturación de cada usuario (Q6/RN-10) y los usuarios cuyo país es nulo.

    Un miembro de familia usa el país del titular del grupo. ``paises_facturacion`` falla ante un
    país nulo; aquí se apartan esos usuarios (y los miembros de sus grupos) para no bloquear a
    los demás, y se devuelven para informarlos.
    """
    pais_de = {
        str(u): p
        for u, p in conexion.execute("SELECT usuario_id, pais_facturacion FROM usuarios")
    }
    titular_de = {
        str(u): str(t)
        for u, t in conexion.execute(
            "SELECT m.usuario_id, g.titular_id FROM miembros_familia m "
            "JOIN grupos_familiares g USING (grupo_id)"
        )
    }
    sin_pais = sorted(u for u in pais_de if pais_de[titular_de.get(u, u)] is None)
    con_pais = {u: p for u, p in pais_de.items() if u not in set(sin_pais)}
    return paises_facturacion(con_pais, {m: t for m, t in titular_de.items() if m in con_pais}), (
        sin_pais
    )


def cargar_usuarios(conexion, periodo: date) -> InsumosUsuarios:
    """Entrada ``usuarios`` de ``gold.liquidar`` para ``periodo``."""
    _validar_periodo(periodo)
    paises, sin_pais = _paises_por_usuario(conexion)
    cierre = ultimo_dia_del_mes(periodo)
    # Una fila por usuario: la suscripción vigente al cierre, o la que terminó más tarde.
    planes = {
        str(u): codigo
        for u, codigo in conexion.execute(
            "SELECT DISTINCT ON (s.usuario_id) s.usuario_id, p.codigo "
            "FROM suscripciones s JOIN planes p USING (plan_id) "
            "WHERE s.fecha_inicio <= %s AND (s.fecha_fin IS NULL OR s.fecha_fin >= %s) "
            "ORDER BY s.usuario_id, s.fecha_inicio DESC, s.suscripcion_id",
            (cierre, periodo),
        )
    }
    salida = InsumosUsuarios(sin_pais=sin_pais)
    for usuario, pais in sorted(paises.items()):
        plan = planes.get(usuario)
        if plan is None:
            salida.sin_suscripcion.append(usuario)
            continue
        componente = Componente.PUBLICIDAD if plan == "free" else Componente.SUSCRIPCION
        salida.filas.append((usuario, pais, str(componente)))
    return salida


def cargar_condiciones(conexion) -> list[CondicionContrato]:
    """Contratos de F4 con sus exclusiones territoriales (RN-08)."""
    exclusiones: dict[str, set[str]] = defaultdict(set)
    for contrato_id, pais in conexion.execute(
        "SELECT contrato_id, pais FROM exclusiones_territoriales"
    ):
        exclusiones[str(contrato_id)].add(pais)
    filas = [
        {
            "contrato_id": c,
            "titular_id": t,
            "track_id": track,
            "porcentaje": porcentaje,
            "valido_desde": desde,
            "valido_hasta": hasta,
            "territorio": territorio,
            "exclusiones": exclusiones.get(str(c), ()),
        }
        for c, t, track, porcentaje, desde, hasta, territorio in conexion.execute(
            "SELECT contrato_id, titular_id, track_id, porcentaje, valido_desde, valido_hasta, "
            "territorio FROM contratos"
        )
    ]
    return condiciones_desde_filas(filas)


@dataclass
class InsumosBolsas:
    bolsas: list[BolsaPais]
    pagos_sin_pais: int  # pagos aprobados que no entran a ninguna bolsa por falta de país


def cargar_bolsas(
    conexion, periodo: date, cfg: ReglasLiquidacionConfig | None = None
) -> InsumosBolsas:
    """Una ``BolsaPais`` por país con suscripción neta (F3) o publicidad (F5) en ``periodo``."""
    _validar_periodo(periodo)
    cfg = cfg or ReglasLiquidacionConfig()
    paises, _ = _paises_por_usuario(conexion)

    pagos: list[Pago] = []
    sin_pais = 0
    for usuario, monto, estado in conexion.execute(
        "SELECT s.usuario_id, pg.monto_usd, pg.estado FROM pagos pg "
        "JOIN suscripciones s USING (suscripcion_id) "
        "WHERE pg.fecha_pago >= %s AND pg.fecha_pago < %s",
        (periodo, _mes_siguiente(periodo)),
    ):
        if str(usuario) not in paises:
            sin_pais += estado == "aprobado"
            continue
        pagos.append(Pago(str(usuario), Decimal(monto), estado))
    suscripcion = suscripcion_neta_por_pais(pagos, paises)

    cierre = ultimo_dia_del_mes(periodo)
    tasas = {
        moneda: TasaCambio(moneda, fecha, Decimal(tasa))
        for moneda, fecha, tasa in conexion.execute(
            "SELECT moneda, fecha_cierre, unidades_por_usd FROM fuente_f6_cierres "
            "WHERE fecha_cierre = %s",
            (cierre,),
        )
    }
    publicidad: dict[str, Decimal] = defaultdict(Decimal)
    for pais, moneda, ingresos in conexion.execute(
        "SELECT pais, moneda, ingresos_publicidad FROM fuente_f5_publicidad WHERE mes = %s",
        (periodo,),
    ):
        if moneda == "USD":
            publicidad[pais] += Decimal(ingresos)
            continue
        if moneda not in tasas:
            raise ValueError(f"falta la tasa de cierre de {moneda} del {cierre} (F6) para {pais}")
        publicidad[pais] += convertir_a_usd(Decimal(ingresos), moneda, tasas[moneda], periodo)

    bolsas = [
        calcular_bolsa(pais, suscripcion.get(pais, Decimal(0)), publicidad.get(pais, Decimal(0)), cfg)
        for pais in sorted(set(suscripcion) | set(publicidad))
    ]
    return InsumosBolsas(bolsas, sin_pais)

