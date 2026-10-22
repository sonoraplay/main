"""Configuración central de SonoraPlay. Todo sale de variables de entorno."""

import os
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Literal

VOLUMENES = {"dev": 10_000, "completo": 900_000}


def database_url() -> str:
    try:
        return os.environ["DATABASE_URL"]
    except KeyError:
        raise SystemExit("Falta DATABASE_URL. Copia .env.example a .env o expórtala.") from None


@dataclass(frozen=True)
class SeedConfig:
    semilla: int = 42
    usuarios: int = VOLUMENES["dev"]
    tasa_defectos: float = 0.02
    fecha_referencia: date = date(2026, 9, 30)  # nunca now(): rompe la reproducibilidad
    fecha_inicio_historia: date = date(2024, 1, 1)
    tamano_lote: int = 5_000


# Catálogo F1 (EG-12)
N_TITULARES = 1_500
SEMILLA_CATALOGO = 42


# --- Umbrales de reglas de negocio ----------------------------------------------------------
# Cada bloque cita su regla y el ADR que justifica los valores. Recalibrar aquí, no en el código.


@dataclass(frozen=True)
class ReglasFraudeConfig:
    """RN-03 · detección de granjas (EG-18). Valores justificados en ADR-0005."""

    # RN-03 señal 1: horas escuchadas en cualquier ventana móvil de 24 h. Se marca si > 20.
    horas_max_24h: float = 20
    # RN-03 señal 2: fracción de las reproducciones del mes a un solo artista. Se marca si > 0,70...
    porcentaje_max_artista: float = 0.70
    # ...y ese artista tiene < 1.000 oyentes únicos en el mes UTC (EG-11 Q2).
    oyentes_min_artista: int = 1_000
    # RN-03 señal 3: cuentas distintas en un mismo dispositivo. Se marca si > 5 (ADR-0005:
    # protege a las familias de hasta 5 cuentas).
    cuentas_max_dispositivo: int = 5
    # EG-11 Q3: se excluye todo el mes de liquidación de la cuenta sospechosa ("en_revision").
    periodo_exclusion: Literal["mes"] = "mes"


@dataclass(frozen=True)
class ReglasValidezConfig:
    """RN-01 y RN-02 · validez y tope diario (EG-17). Supuestos de EG-11 Q1 y Q4, ADR-0002."""

    # RN-01: un tramo continuo de al menos estos segundos hace válida la reproducción (>= 30 s).
    # EG-11 Q1: la pausa, el seek o la interrupción antes del umbral reinician el conteo.
    segundos_min_validez: int = 30
    # RN-02: máximo de reproducciones válidas pagables por track, usuario y día.
    # EG-11 Q4 / ADR-0002: el "día" es la fecha UTC.
    max_reproducciones_dia: int = 10


@dataclass(frozen=True)
class ReglasLiquidacionConfig:
    """RN-05 / RN-06 · bolsa por país en dos componentes (EG-11 Q8, decidido en la planificación
    del S2). Las justificaciones quedan en ADR-0007 y ADR-0008. Fracciones de 0 a 1 en Decimal:
    el dinero nunca pasa por float.
    """

    # Componente de suscripción: fracción de la suscripción neta (Q5), repartida por
    # reproducciones válidas de planes pagos.
    fraccion_suscripcion: Decimal = Decimal("0.52")
    # Componente de publicidad: fracción de los ingresos publicitarios, repartida por
    # reproducciones válidas del plan gratuito.
    fraccion_publicidad: Decimal = Decimal("0.45")

    def __post_init__(self) -> None:
        for nombre in ("fraccion_suscripcion", "fraccion_publicidad"):
            valor = getattr(self, nombre)
            if not isinstance(valor, Decimal):
                raise TypeError(f"{nombre} debe ser Decimal (no float: se pierden centavos)")
            if not 0 <= valor <= 1:
                raise ValueError(f"{nombre} debe estar entre 0 y 1")


@dataclass(frozen=True)
class ContratosConfig:
    """EG-14 · parámetros reproducibles del seed F4."""

    semilla: int = 42
    fecha_inicio: date = date(2026, 9, 1)
    fraccion_cambios: float = 0.15
    fraccion_exclusiones: float = 0.10
    fraccion_condiciones_territoriales: float = 0.10
    porcentaje_min: int = 30
    porcentaje_max: int = 70

    def __post_init__(self) -> None:
        for nombre in (
            "fraccion_cambios",
            "fraccion_exclusiones",
            "fraccion_condiciones_territoriales",
        ):
            valor = getattr(self, nombre)
            if not 0 <= valor <= 1:
                raise ValueError(f"{nombre} debe estar entre 0 y 1")
        if not 0 <= self.porcentaje_min <= self.porcentaje_max <= 100:
            raise ValueError("los porcentajes contractuales deben estar entre 0 y 100")


@dataclass(frozen=True)
class SimuladorConfig:
    """EG-19 · simulador F2 mínimo para el esqueleto (EG-24). La EG-51 lo extiende.

    Los escenarios obligatorios (RN-01 y RN-02) salen de `reglas`, así que si se recalibran los
    umbrales los escenarios se mueven con ellos.
    """

    semilla: int = 42
    eventos: int = 100
    # Septiembre: el mes que liquidaría la EG-24. Nunca now(): rompe la reproducibilidad.
    fecha_base: date = date(2026, 9, 15)
    reglas: ReglasValidezConfig = ReglasValidezConfig()

    @property
    def eventos_minimos(self) -> int:
        """Eventos de los escenarios A (2), B (2), C (4) y D (2 por cada sesión del tope + 1)."""
        return 2 + 2 + 4 + 2 * (self.reglas.max_reproducciones_dia + 1)

    def __post_init__(self) -> None:
        if self.eventos < self.eventos_minimos:
            raise ValueError(
                f"eventos debe ser al menos {self.eventos_minimos} para los escenarios "
                f"de RN-01 y RN-02 (recibido: {self.eventos})"
            )


@dataclass(frozen=True)
class AtribucionOfflineConfig:
    """RN-04 · cierre de sincronización del mes anterior en UTC (ADR-0002)."""

    dia_corte: int = 2
    hora_corte: int = 23
    minuto_corte: int = 59
    tolerancia_reloj_segundos: int = 60

    def __post_init__(self) -> None:
        if not 1 <= self.dia_corte <= 28:
            raise ValueError("dia_corte debe estar entre 1 y 28")
        if not 0 <= self.hora_corte <= 23 or not 0 <= self.minuto_corte <= 59:
            raise ValueError("hora_corte y minuto_corte fuera de rango")
        if self.tolerancia_reloj_segundos < 0:
            raise ValueError("tolerancia_reloj_segundos no puede ser negativa")


# --- Simulador F2 avanzado (EG-51) ------------------------------------------------------------


@dataclass(frozen=True)
class DefectosF2Config:
    """Los 5 defectos de `docs/datos/eventos-f2.md`, en % de las sesiones de cuentas normales.

    Cada sesión tiene a lo sumo un defecto, así que los porcentajes se suman (máximo 100).
    """

    evento_sin_fin: float = 2.0
    reloj_desfasado: float = 2.0
    track_desconocido: float = 2.0
    duplicado_por_reintento: float = 2.0
    pais_facturacion_distinto: float = 2.0

    def como_dict(self) -> dict[str, float]:
        return {
            "evento_sin_fin": self.evento_sin_fin,
            "reloj_desfasado": self.reloj_desfasado,
            "track_desconocido": self.track_desconocido,
            "duplicado_por_reintento": self.duplicado_por_reintento,
            "pais_facturacion_distinto": self.pais_facturacion_distinto,
        }

    def __post_init__(self) -> None:
        for nombre, valor in self.como_dict().items():
            if not 0 <= valor <= 100:
                raise ValueError(f"defecto {nombre} debe estar entre 0 y 100 (recibido: {valor})")
        if sum(self.como_dict().values()) > 100:
            raise ValueError("los porcentajes de defectos suman más de 100")


@dataclass(frozen=True)
class SimuladorAvanzadoConfig:
    """EG-51 · granjas, oyentes intensivos, offline, defectos y carga pico sobre un mes UTC.

    Los porcentajes van en puntos (5.0 = 5 %). Las cantidades se redondean una sola vez y se
    asignan exactas, así que la proporción generada no se aleja más de medio evento del valor
    pedido. Los perfiles se calibran contra `fraude` (RN-03): las granjas superan algún umbral y
    los intensivos legítimos quedan por debajo de todos.
    """

    semilla: int = 42
    cuentas: int = 10_000
    # Primer día del mes que se simula (septiembre: el que liquidaría el esqueleto).
    mes: date = date(2026, 9, 1)
    pct_granjas: float = 5.0  # FARM_PCT
    pct_intensivos: float = 2.0
    pct_offline: float = 10.0  # de las sesiones de cuentas normales
    retraso_offline_max_dias: int = 30
    # Sesiones de una cuenta normal en el mes. Mínimo 2: con 1 sola, el 100 % va a un artista.
    sesiones_por_cuenta: tuple[int, int] = (6, 12)
    # Granja de horas: escucha entre estas horas dentro de 24 h (RN-03 señal 1 marca > 20).
    horas_granja: tuple[float, float] = (21.0, 23.0)
    # Oyente intensivo legítimo: muchas horas en un día, bajo el umbral y con artistas variados.
    horas_intensivo: tuple[float, float] = (12.0, 18.0)
    # Granja de artista: fracción de reproducciones al artista que infla (RN-03 señal 2: > 0,70).
    fraccion_artista_granja: float = 0.9
    sesiones_granja_artista: tuple[int, int] = (30, 60)
    # Granja de dispositivo: cuentas por dispositivo compartido (RN-03 señal 3: > 5).
    cuentas_por_dispositivo_granja: int = 6
    defectos: DefectosF2Config = field(default_factory=DefectosF2Config)
    fraude: ReglasFraudeConfig = field(default_factory=ReglasFraudeConfig)

    def __post_init__(self) -> None:
        if self.cuentas < 1:
            raise ValueError("cuentas debe ser al menos 1")
        if self.mes.day != 1:
            raise ValueError(f"mes debe ser el primer día de un mes (recibido: {self.mes})")
        for nombre in ("pct_granjas", "pct_intensivos", "pct_offline"):
            valor = getattr(self, nombre)
            if not 0 <= valor <= 100:
                raise ValueError(f"{nombre} debe estar entre 0 y 100 (recibido: {valor})")
        if self.pct_granjas + self.pct_intensivos > 100:
            raise ValueError("pct_granjas + pct_intensivos no puede pasar de 100")
        if self.pct_offline + sum(self.defectos.como_dict().values()) > 100:
            raise ValueError("pct_offline + los defectos no puede pasar de 100 %")
        if not 0 <= self.retraso_offline_max_dias <= 30:
            raise ValueError("retraso_offline_max_dias debe estar entre 0 y 30")
        lo, hi = self.sesiones_por_cuenta
        if not 2 <= lo <= hi:
            raise ValueError(
                "sesiones_por_cuenta debe ser (min, max) con 2 <= min <= max: una cuenta con "
                "1 sesión manda el 100 % a un artista y RN-03 la marcaría (falso positivo)"
            )
        umbral = self.fraude.horas_max_24h
        if not umbral < self.horas_granja[0] <= self.horas_granja[1] < 24:
            raise ValueError(f"horas_granja debe estar entre {umbral} (exclusivo) y 24")
        if not 0 < self.horas_intensivo[0] <= self.horas_intensivo[1] < umbral:
            raise ValueError(f"horas_intensivo debe quedar por debajo de {umbral} h")
        if not self.fraude.porcentaje_max_artista < self.fraccion_artista_granja <= 1:
            raise ValueError("fraccion_artista_granja debe superar porcentaje_max_artista")
        if self.cuentas_por_dispositivo_granja <= self.fraude.cuentas_max_dispositivo:
            raise ValueError("cuentas_por_dispositivo_granja debe superar cuentas_max_dispositivo")

    @property
    def n_granjas(self) -> int:
        return round(self.cuentas * self.pct_granjas / 100)

    @property
    def n_intensivos(self) -> int:
        return round(self.cuentas * self.pct_intensivos / 100)
