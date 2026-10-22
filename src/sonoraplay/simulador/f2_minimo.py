"""Simulador F2 mínimo para el esqueleto (EG-19). Determinista: misma semilla, mismo archivo.

Escribe sesiones completas (start → pause/resume → end/skip) en JSON Lines para la EG-24. Los
usuarios salen de F3 y las pistas del catálogo F1 con contrato de su titular en F4. Granjas, oyentes
intensivos, eventos offline, los 5 defectos y la carga pico quedan para la EG-51; RabbitMQ, para la
EG-29. Ver docs/datos/simulador-f2.md.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path

import pandas as pd
from jsonschema import Draft202012Validator, FormatChecker
from sqlalchemy import Engine, text

from sonoraplay.config import SimuladorConfig
from sonoraplay.seed.f3_suscripciones import PAISES, det_uuid

ESQUEMA_F2 = Path(__file__).resolve().parents[3] / "schemas" / "f2_evento.schema.json"

# Orden fijo de las claves en cada línea: el mismo del `required` del esquema.
CAMPOS = (
    "schema_version",
    "event_id",
    "event_type",
    "user_id",
    "device_id",
    "track_id",
    "session_id",
    "device_ts",
    "server_ts",
    "position_ms",
    "country_playback",
    "is_offline",
)
DURACION_MAX_ESCENARIO_D = 600_000  # 11 sesiones de hasta 10 min caben en la misma mañana UTC
Paso = tuple[str, int, int]


@dataclass(frozen=True)
class Usuario:
    usuario_id: str
    pais_facturacion: str | None


@dataclass(frozen=True)
class Pista:
    track_id: str
    duration_ms: int


@dataclass(frozen=True)
class FuentesSimulador:
    """Usuarios de F3 y pistas de F1 con contrato vigente de su titular en F4, ordenados."""

    usuarios: tuple[Usuario, ...]
    pistas: tuple[Pista, ...]


def leer_fuentes(engine: Engine, directorio_f1: Path, fecha_base: date) -> FuentesSimulador:
    """Lee las fuentes reales para que cada evento cruce con F1, F3 y F4.

    - Usuarios activos todo el día `fecha_base` (alta antes y sin baja ese día), por `usuario_id`.
    - Pistas de `catalogo_f1.parquet` cuyo titular tiene una condición general (sin territorio)
      vigente en `fecha_base` para esa pista, por `track_id`.
    """
    dia = datetime.combine(fecha_base, time(), tzinfo=UTC)
    with engine.connect() as conn:
        usuarios = conn.execute(
            text(
                "SELECT usuario_id::text, pais_facturacion FROM usuarios "
                "WHERE fecha_alta < :dia AND (fecha_baja IS NULL OR fecha_baja >= :fin) "
                "ORDER BY usuario_id"
            ),
            {"dia": dia, "fin": dia + timedelta(days=1)},
        ).all()
        contratos = conn.execute(
            text(
                "SELECT DISTINCT track_id, titular_id::text FROM contratos "
                "WHERE territorio IS NULL AND valido_desde <= :d "
                "AND (valido_hasta IS NULL OR valido_hasta >= :d)"
            ),
            {"d": fecha_base},
        ).all()
    if not usuarios:
        raise ValueError(
            f"No hay usuarios de F3 activos el {fecha_base}. "
            "Corre antes: python -m sonoraplay.seed --modo dev"
        )

    ruta = directorio_f1 / "catalogo_f1.parquet"
    if not ruta.exists():
        raise ValueError(f"No existe {ruta}. Corre antes: python -m sonoraplay.catalogo")
    catalogo = pd.read_parquet(ruta, columns=["track_id", "titular_id", "duration_ms"])
    con_contrato = {(t, titular) for t, titular in contratos}
    pistas = sorted(
        (
            Pista(str(f.track_id), int(f.duration_ms))
            for f in catalogo.itertuples(index=False)
            if (str(f.track_id), str(f.titular_id)) in con_contrato
        ),
        key=lambda p: p.track_id,
    )
    if not pistas:
        raise ValueError(
            "Ninguna pista del catálogo F1 tiene contrato vigente en F4. "
            "Corre antes: python -m sonoraplay.seed.f4_contratos"
        )
    return FuentesSimulador(
        usuarios=tuple(Usuario(u, (p or "").strip() or None) for u, p in usuarios),
        pistas=tuple(pistas),
    )


def _iso(ts: datetime) -> str:
    """UTC con Z y milisegundos, como pide el esquema (ADR-0002)."""
    return f"{ts:%Y-%m-%dT%H:%M:%S}.{ts.microsecond // 1000:03d}Z"


def guion(
    tramos_ms: list[int], pausas_ms: list[int], duracion_ms: int, cerrar_en_pausa: bool = False
) -> list[Paso]:
    """Pasos (event_type, ms desde el start, position_ms) de una sesión.

    Mientras suena, la posición avanza lo mismo que el reloj; en una pausa solo avanza el reloj.
    La sesión cierra con `end` si llega al final de la pista y con `skip` si no. Con
    `cerrar_en_pausa`, el último tramo termina en `pause` y la sesión cierra después con `skip`.
    """
    pasos: list[Paso] = [("start", 0, 0)]
    t = pos = 0
    for i, tramo in enumerate(tramos_ms):
        t += tramo
        pos += tramo
        if pos > duracion_ms:
            raise ValueError(f"position_ms {pos} supera la duración de la pista {duracion_ms}")
        ultimo = i == len(tramos_ms) - 1
        if ultimo and not cerrar_en_pausa:
            pasos.append(("end" if pos == duracion_ms else "skip", t, pos))
            break
        pasos.append(("pause", t, pos))
        t += pausas_ms[i]
        pasos.append(("skip" if ultimo else "resume", t, pos))
    return pasos


class _Generador:
    def __init__(self, fuentes: FuentesSimulador, cfg: SimuladorConfig) -> None:
        if not fuentes.usuarios or not fuentes.pistas:
            raise ValueError("el simulador necesita al menos un usuario y una pista")
        self.fuentes = fuentes
        self.cfg = cfg
        self.rng = random.Random(f"{cfg.semilla}:f2")
        self.dia = datetime.combine(cfg.fecha_base, time(), tzinfo=UTC)
        self.libre: dict[str, datetime] = {}  # cuándo puede empezar la próxima sesión del usuario
        self.paises: dict[str, str] = {}
        self.eventos: list[dict] = []
        self.sesiones = 0
        self.par_d: tuple[str, str] | None = None  # (usuario, pista) del escenario D

    def elegir(self, minimo_ms: int, maximo_ms: int | None = None) -> tuple[Usuario, Pista]:
        """Usuario y pista al azar, sin repetir el par del escenario D salvo que sea el único.

        Así ninguna otra sesión suma reproducciones válidas al grupo de D y su tope queda exacto.
        """
        usuarios = self.fuentes.usuarios
        pistas = [
            p
            for p in self.fuentes.pistas
            if p.duration_ms >= minimo_ms and (maximo_ms is None or p.duration_ms <= maximo_ms)
        ]
        if not pistas:
            raise ValueError(f"no hay pistas de al menos {minimo_ms} ms para el simulador")
        unico = len(usuarios) == 1 and len(pistas) == 1
        while True:
            u, p = self.rng.choice(usuarios), self.rng.choice(pistas)
            if unico or (u.usuario_id, p.track_id) != self.par_d:
                return u, p

    def pais(self, u: Usuario) -> str:
        if u.usuario_id not in self.paises:
            self.paises[u.usuario_id] = u.pais_facturacion or self.rng.choice(PAISES)
        return self.paises[u.usuario_id]

    def sesion(self, u: Usuario, p: Pista, desde: datetime, pasos: list[Paso]) -> None:
        inicio = max(desde, self.libre.get(u.usuario_id, desde))
        n = self.sesiones
        self.sesiones += 1
        semilla = self.cfg.semilla
        session_id = str(det_uuid(semilla, "f2-sesion", n))
        device_id = "android-" + det_uuid(semilla, "f2-dispositivo", u.usuario_id).hex[:8]
        pais = self.pais(u)
        for i, (tipo, t_ms, pos) in enumerate(pasos):
            device_ts = inicio + timedelta(milliseconds=t_ms)
            server_ts = device_ts + timedelta(milliseconds=self.rng.randint(100, 500))
            valores = (
                "1.0",
                str(det_uuid(semilla, "f2-evento", n, i)),
                tipo,
                u.usuario_id,
                device_id,
                p.track_id,
                session_id,
                _iso(device_ts),
                _iso(server_ts),
                pos,
                pais,
                False,
            )
            self.eventos.append(dict(zip(CAMPOS, valores, strict=True)))
        fin = inicio + timedelta(milliseconds=pasos[-1][1])
        self.libre[u.usuario_id] = fin + timedelta(seconds=self.rng.randint(30, 300))

    def escenarios(self, a_en_tres_eventos: bool) -> None:
        """A, B, C y D con valores fijos: ejercitan RN-01 y RN-02 en cada archivo."""
        umbral = self.cfg.reglas.segundos_min_validez * 1_000
        manana = self.dia + timedelta(hours=8)

        # D: tope + 1 sesiones completas del mismo usuario y pista, el mismo día UTC (RN-02).
        # Se elige primero para que ninguna otra sesión use su par. Cada sesión empieza de 30 s
        # a 5 min después de la anterior (ver `sesion`).
        u_d, p_d = self.elegir(max(60_000, umbral), DURACION_MAX_ESCENARIO_D)
        self.par_d = (u_d.usuario_id, p_d.track_id)
        for _ in range(self.cfg.reglas.max_reproducciones_dia + 1):
            self.sesion(u_d, p_d, manana, guion([p_d.duration_ms], [], p_d.duration_ms))
        # A: el tramo más largo se queda 1 s corto del umbral → no válida (RN-01).
        u, p = self.elegir(umbral)
        pasos = guion([umbral - 1_000], [5_000], p.duration_ms, cerrar_en_pausa=a_en_tres_eventos)
        self.sesion(u, p, manana, pasos)
        # B: exactamente el umbral → válida, en el límite.
        u, p = self.elegir(umbral)
        self.sesion(u, p, manana, guion([umbral], [], p.duration_ms))
        # C: 15 s + pausa + 20 s → no válida: la pausa reinicia el conteo (EG-11 Q1).
        tramos = [umbral // 2, umbral * 2 // 3]
        u, p = self.elegir(sum(tramos))
        self.sesion(u, p, manana, guion(tramos, [10_000], p.duration_ms))

    def relleno(self, restantes: int) -> None:
        """Sesiones aleatorias de 2 a 4 eventos hasta completar exactamente `restantes`."""
        while restantes:
            tamanos = [n for n in (2, 3, 4) if n <= restantes and restantes - n != 1]
            n = self.rng.choice(tamanos)
            u, p = self.elegir(2)
            d = p.duration_ms
            pausas = [self.rng.randint(2_000, 120_000)]
            if n == 4:
                t1 = self.rng.randint(1, d - 1)
                t2 = d - t1 if self.rng.random() < 0.5 else self.rng.randint(1, d - t1)
                pasos = guion([t1, t2], pausas, d)
            else:
                t1 = d if n == 2 and self.rng.random() < 0.5 else self.rng.randint(1, d - 1)
                pasos = guion([t1], pausas, d, cerrar_en_pausa=n == 3)
            desde = self.dia + timedelta(hours=10, milliseconds=self.rng.randint(0, 12 * 3_600_000))
            self.sesion(u, p, desde, pasos)
            restantes -= n


def generar(fuentes: FuentesSimulador, cfg: SimuladorConfig) -> list[dict]:
    """Función pura: sin reloj del sistema, sin `random` global y sin E/S.

    Devuelve exactamente `cfg.eventos` eventos ordenados por `device_ts` (y por orden de
    generación ante un empate), cada uno con las claves en el orden de `CAMPOS`.
    """
    g = _Generador(fuentes, cfg)
    restantes = cfg.eventos - cfg.eventos_minimos
    # Con 1 evento de sobra no cabe una sesión de relleno: A se emite en 3 eventos.
    g.escenarios(a_en_tres_eventos=restantes == 1)
    g.relleno(restantes - 1 if restantes == 1 else restantes)
    orden = sorted(range(len(g.eventos)), key=lambda i: (g.eventos[i]["device_ts"], i))
    return [g.eventos[i] for i in orden]


def validador() -> Draft202012Validator:
    esquema = json.loads(ESQUEMA_F2.read_text(encoding="utf-8"))
    return Draft202012Validator(esquema, format_checker=FormatChecker())


def escribir(eventos: list[dict], salida: Path) -> None:
    """JSON Lines en UTF-8 con `\\n` también en Windows: el mismo archivo byte por byte."""
    salida.parent.mkdir(parents=True, exist_ok=True)
    with salida.open("w", encoding="utf-8", newline="\n") as f:
        for e in eventos:
            f.write(json.dumps(e, ensure_ascii=False, separators=(",", ":")) + "\n")


def ejecutar(engine: Engine, directorio_f1: Path, salida: Path, cfg: SimuladorConfig) -> int:
    """Lee las fuentes, genera, valida cada evento contra el esquema F2 y escribe el archivo."""
    eventos = generar(leer_fuentes(engine, directorio_f1, cfg.fecha_base), cfg)
    v = validador()
    for e in eventos:
        v.validate(e)
    escribir(eventos, salida)
    return len(eventos)
