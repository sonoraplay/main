"""Simulador F2 avanzado (EG-51): granjas, oyentes intensivos, offline, defectos y carga pico.

Extiende el simulador mínimo (EG-19) a un mes UTC completo y a miles de cuentas:

- **Granjas** (RN-03), en tres perfiles: más de 20 h en 24 h, más del 70 % de las reproducciones
  a un artista con menos de 1.000 oyentes, y dispositivos compartidos por más de 5 cuentas.
- **Oyentes intensivos legítimos**: muchas horas en un día, pero bajo el umbral y con artistas
  variados, para medir falsos positivos.
- **Offline** (RN-04): sesiones sincronizadas de 0 a 30 días después.
- **Los 5 defectos** de `docs/datos/eventos-f2.md`, cada uno en su proporción.
- **Etiquetas de verdad** (granja / legítima por cuenta, defecto y offline por sesión), aparte
  de los eventos, para el informe de fraude (EG-43).

`generar` es una función pura: misma semilla y mismas fuentes, mismos eventos. La carga pico
hacia RabbitMQ está en `sonoraplay.streaming.carga_pico`. Ver docs/datos/simulador-f2.md.

Uso: python -m sonoraplay.simulador.f2_avanzado [--cuentas N] [--pico --tasa 120 --duracion 60]
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import random
import string
from collections import Counter, defaultdict
from dataclasses import dataclass, replace
from datetime import UTC, datetime, time, timedelta
from pathlib import Path

from sonoraplay.config import DefectosF2Config, SimuladorAvanzadoConfig
from sonoraplay.seed.f3_suscripciones import PAISES, det_uuid
from sonoraplay.simulador.f2_minimo import (
    CAMPOS,
    FuentesSimulador,
    Paso,
    Pista,
    Usuario,
    _iso,
    escribir,
    guion,
    leer_fuentes,
    validador,
)

BASE62 = string.digits + string.ascii_uppercase + string.ascii_lowercase
_HORA_MS = 3_600_000
_DIA_MS = 24 * _HORA_MS

GRANJA_HORAS = "granja_horas_24h"
GRANJA_ARTISTA = "granja_concentracion_artista"
GRANJA_DISPOSITIVO = "granja_dispositivo_compartido"
INTENSIVO = "intensivo"
NORMAL = "normal"
PERFILES_GRANJA = (GRANJA_HORAS, GRANJA_ARTISTA, GRANJA_DISPOSITIVO)
DEFECTOS = tuple(DefectosF2Config().como_dict())


@dataclass(frozen=True)
class EtiquetaCuenta:
    """Verdad de una cuenta: `etiqueta` es "granja" o "legitima"; `perfil`, cuál de los 5."""

    cuenta_id: str
    etiqueta: str
    perfil: str


@dataclass(frozen=True)
class EtiquetaSesion:
    """Verdad de una sesión: si es offline y qué defecto se le inyectó ("" si ninguno)."""

    session_id: str
    cuenta_id: str
    perfil: str
    is_offline: bool
    defecto: str


@dataclass(frozen=True)
class Simulacion:
    eventos: list[dict]
    cuentas: list[EtiquetaCuenta]
    sesiones: list[EtiquetaSesion]


@dataclass
class _Sesion:
    usuario: Usuario
    perfil: str
    device_id: str
    pista: Pista
    inicio: datetime
    pasos: list[Paso]
    is_offline: bool = False
    defecto: str = ""

    @property
    def fin(self) -> datetime:
        return self.inicio + timedelta(milliseconds=self.pasos[-1][1])


def artista(p: Pista) -> str:
    """Artista de la pista; si las fuentes no lo traen, cada pista cuenta como su propio artista."""
    return p.artista or p.track_id


class _Generador:
    def __init__(self, fuentes: FuentesSimulador, cfg: SimuladorAvanzadoConfig) -> None:
        if cfg.cuentas > len(fuentes.usuarios):
            raise ValueError(
                f"Se piden {cfg.cuentas} cuentas y las fuentes solo tienen "
                f"{len(fuentes.usuarios)} usuarios activos. Baja --cuentas o corre el seed F3 "
                "con más usuarios."
            )
        self.cfg = cfg
        self.rng = random.Random(f"{cfg.semilla}:f2-avanzado")
        self.ini = datetime.combine(cfg.mes, time(), tzinfo=UTC)
        siguiente = (cfg.mes.replace(day=28) + timedelta(days=4)).replace(day=1)
        self.fin = datetime.combine(siguiente, time(), tzinfo=UTC)
        self.mes_ms = (self.fin - self.ini) // timedelta(milliseconds=1)
        self.catalogo = {p.track_id for p in fuentes.pistas}
        self.pistas = [p for p in fuentes.pistas if p.duration_ms >= 2_000]
        if not self.pistas:
            raise ValueError("el simulador avanzado necesita pistas de al menos 2 s")
        self.usuarios = sorted(
            self.rng.sample(list(fuentes.usuarios), cfg.cuentas), key=lambda u: u.usuario_id
        )
        self.paises: dict[str, str] = {}
        self.sesiones: list[_Sesion] = []
        self.perfil: dict[str, str] = {}

    # --- Utilidades ----------------------------------------------------------------------------

    def ms(self, a: int, b: int) -> timedelta:
        return timedelta(milliseconds=self.rng.randint(a, b))

    def pais(self, u: Usuario) -> str:
        if u.usuario_id not in self.paises:
            self.paises[u.usuario_id] = u.pais_facturacion or self.rng.choice(PAISES)
        return self.paises[u.usuario_id]

    def dispositivo(self, u: Usuario) -> str:
        """El mismo `device_id` que el simulador mínimo: uno por usuario."""
        return "android-" + det_uuid(self.cfg.semilla, "f2-dispositivo", u.usuario_id).hex[:8]

    def guion_aleatorio(self, p: Pista) -> list[Paso]:
        """Escucha completa, salto a mitad, o con una pausa (y a veces hasta el final)."""
        d = p.duration_ms
        x = self.rng.random()
        if x < 0.5:
            return guion([d], [], d)
        if x < 0.75:
            return guion([self.rng.randint(1, d - 1)], [], d)
        t1 = self.rng.randint(1, d - 1)
        t2 = d - t1 if self.rng.random() < 0.5 else self.rng.randint(1, d - t1)
        return guion([t1, t2], [self.rng.randint(2_000, 120_000)], d)

    def agregar(self, u: Usuario, device: str, p: Pista, inicio: datetime, pasos: list[Paso]):
        s = _Sesion(u, self.perfil[u.usuario_id], device, p, inicio, pasos)
        self.sesiones.append(s)
        return s

    def linea_de_tiempo(
        self, u: Usuario, device: str, turnos: list[list[Pista]], n: int, desde_max: float, hueco_ms
    ) -> None:
        """`n` sesiones seguidas sin solaparse, desde un instante al azar del mes. Para al final.

        La sesión `i` toma su pista de `turnos[i % len(turnos)]`: con 3 o más turnos ningún artista
        pasa de 1/3 + 1 sesión, así una cuenta normal nunca cumple la señal 2 de RN-03.
        """
        t = self.ini + self.ms(0, int(self.mes_ms * desde_max))
        for i in range(n):
            p = self.rng.choice(turnos[i % len(turnos)])
            pasos = self.guion_aleatorio(p)
            if t + timedelta(milliseconds=pasos[-1][1]) >= self.fin:
                break
            s = self.agregar(u, device, p, t, pasos)
            t = s.fin + self.ms(*hueco_ms)

    def bloque_continuo(
        self, u: Usuario, pistas_por_turno: list[list[Pista]], objetivo_ms: int, tope_ms: int
    ) -> None:
        """Escuchas completas una tras otra (con 1 a 20 s entre pistas) hasta `objetivo_ms`.

        Cada pista sale de `pistas_por_turno[i % len]`, para alternar artistas. Nunca pasa de
        `tope_ms` escuchados: así un intensivo no cruza el umbral por una pista muy larga.
        """
        t = self.ini + self.ms(0, self.mes_ms - 25 * _HORA_MS)
        escuchado = i = saltos = 0
        device = self.dispositivo(u)
        while escuchado < objetivo_ms and saltos < 100:
            p = self.rng.choice(pistas_por_turno[i % len(pistas_por_turno)])
            i += 1
            if escuchado + p.duration_ms >= tope_ms:
                saltos += 1  # esta pista no cabe bajo el tope; se prueba otra
                continue
            saltos = 0
            s = self.agregar(u, device, p, t, guion([p.duration_ms], [], p.duration_ms))
            escuchado += p.duration_ms
            t = s.fin + self.ms(1_000, 20_000)

    # --- Perfiles ------------------------------------------------------------------------------

    def planear(self) -> None:
        cfg = self.cfg
        orden = list(self.usuarios)
        self.rng.shuffle(orden)
        granjas, resto = orden[: cfg.n_granjas], orden[cfg.n_granjas :]
        intensivos, normales = resto[: cfg.n_intensivos], resto[cfg.n_intensivos :]

        # Reparto de granjas: un tercio por dispositivo (si alcanza para un grupo), el resto
        # entre horas y artista.
        tam = cfg.cuentas_por_dispositivo_granja
        n_disp = len(granjas) // 3 if len(granjas) // 3 >= tam else 0
        n_horas = (len(granjas) - n_disp) // 2
        g_horas = granjas[:n_horas]
        g_artista = granjas[n_horas : len(granjas) - n_disp]
        g_disp = granjas[len(granjas) - n_disp :]
        for grupo, perfil in (
            (g_horas, GRANJA_HORAS),
            (g_artista, GRANJA_ARTISTA),
            (g_disp, GRANJA_DISPOSITIVO),
            (intensivos, INTENSIVO),
            (normales, NORMAL),
        ):
            for u in grupo:
                self.perfil[u.usuario_id] = perfil

        # Artistas que inflan las granjas: nadie más los escucha, así tienen < 1.000 oyentes.
        por_artista: dict[str, list[Pista]] = defaultdict(list)
        for p in self.pistas:
            por_artista[artista(p)].append(p)
        artistas = sorted(por_artista)
        reservados: list[str] = []
        if g_artista:
            k = max(1, min(len(g_artista), len(artistas) // 10))
            if len(artistas) - k < 2:
                raise ValueError(
                    "las granjas de artista necesitan al menos 3 artistas en el catálogo"
                )
            reservados = sorted(self.rng.sample(artistas, k))
        libres = [a for a in artistas if a not in set(reservados)]
        if (intensivos or normales) and len(libres) < 3:
            raise ValueError(
                "las cuentas normales e intensivas necesitan al menos 3 artistas libres en el "
                "catálogo"
            )
        legit = [p for a in libres for p in por_artista[a]]

        umbral_ms = int(cfg.fraude.horas_max_24h * _HORA_MS)
        hueco_normal = (30_000, 4 * _DIA_MS)

        # Una cuenta normal alterna entre 3 artistas suyos: nunca pasa del 70 % a uno solo.
        for u in normales:
            n = self.rng.randint(*cfg.sesiones_por_cuenta)
            propios = [por_artista[a] for a in self.rng.sample(libres, min(3, len(libres)))]
            self.linea_de_tiempo(u, self.dispositivo(u), propios, n, 0.8, hueco_normal)

        for u in intensivos:
            turnos = [por_artista[a] for a in self.rng.sample(libres, min(10, len(libres)))]
            objetivo = int(self.rng.uniform(*cfg.horas_intensivo) * _HORA_MS)
            self.bloque_continuo(u, turnos, objetivo, umbral_ms)

        for u in g_horas:
            objetivo = int(self.rng.uniform(*cfg.horas_granja) * _HORA_MS)
            self.bloque_continuo(u, [legit], objetivo, 24 * _HORA_MS)

        for i, u in enumerate(g_artista):
            propias = por_artista[reservados[i % len(reservados)]]
            n = self.rng.randint(*cfg.sesiones_granja_artista)
            n_propias = math.ceil(n * cfg.fraccion_artista_granja)
            elegidas = [self.rng.choice(propias) for _ in range(n_propias)]
            elegidas += [self.rng.choice(legit) for _ in range(n - n_propias)]
            self.rng.shuffle(elegidas)
            t = self.ini + self.ms(0, self.mes_ms // 2)
            device = self.dispositivo(u)
            for p in elegidas:
                s = self.agregar(u, device, p, t, guion([p.duration_ms], [], p.duration_ms))
                t = s.fin + self.ms(2 * 60_000, 4 * _HORA_MS)

        grupos = len(g_disp) // tam if g_disp else 0
        for g in range(grupos):
            # Los sobrantes se reparten entre los primeros grupos (6, 7... cuentas por grupo).
            miembros = g_disp[g::grupos]
            device = "android-" + det_uuid(cfg.semilla, "f2a-dispositivo-granja", g).hex[:8]
            for u in miembros:
                n = self.rng.randint(*cfg.sesiones_por_cuenta)
                self.linea_de_tiempo(u, device, [legit], n, 0.8, hueco_normal)

    def marcar_offline_y_defectos(self) -> None:
        """Elige, sin repetir, las sesiones normales offline y las de cada defecto.

        Las cantidades se redondean una vez sobre el total de sesiones normales. País distinto
        solo aplica a cuentas con país de facturación en F3, así que se elige primero.
        """
        normales = [i for i, s in enumerate(self.sesiones) if s.perfil == NORMAL]
        total = len(normales)
        pct = self.cfg.defectos.como_dict()
        libres = set(normales)

        def tomar(n: int, candidatos: list[int], que: str) -> list[int]:
            if n > len(candidatos):
                raise ValueError(f"no hay sesiones suficientes para {que}: {n} > {len(candidatos)}")
            elegidos = self.rng.sample(sorted(candidatos), n)
            libres.difference_update(elegidos)
            return elegidos

        con_pais = [i for i in normales if self.sesiones[i].usuario.pais_facturacion]
        n = round(total * pct["pais_facturacion_distinto"] / 100)
        for i in tomar(n, con_pais, "pais_facturacion_distinto"):
            self.sesiones[i].defecto = "pais_facturacion_distinto"
        for defecto in DEFECTOS:
            if defecto == "pais_facturacion_distinto":
                continue
            n = round(total * pct[defecto] / 100)
            for i in tomar(n, list(libres), defecto):
                self.sesiones[i].defecto = defecto
        n = round(total * self.cfg.pct_offline / 100)
        for i in tomar(n, list(libres), "offline"):
            self.sesiones[i].is_offline = True

    # --- Emisión -------------------------------------------------------------------------------

    def track_desconocido(self) -> str:
        while True:
            t = "".join(self.rng.choice(BASE62) for _ in range(22))
            if t not in self.catalogo:
                return t

    def emitir(self, n: int, s: _Sesion) -> tuple[list[dict], str]:
        semilla = self.cfg.semilla
        session_id = str(det_uuid(semilla, "f2a-sesion", n))
        u = s.usuario
        pais = self.pais(u)
        track = s.pista.track_id
        desfase = timedelta(0)
        if s.defecto == "pais_facturacion_distinto":
            pais = self.rng.choice([x for x in PAISES if x != u.pais_facturacion])
        elif s.defecto == "track_desconocido":
            track = self.track_desconocido()
        elif s.defecto == "reloj_desfasado":
            # Entre 1 y 6 h, adelantado o atrasado: muy por encima de la tolerancia de 60 s.
            desfase = self.rng.choice((-1, 1)) * self.ms(_HORA_MS, 6 * _HORA_MS)

        reales = [s.inicio + timedelta(milliseconds=t) for _, t, _ in s.pasos]
        if s.is_offline:
            # Se sincroniza todo junto, de 0 a 30 días después del último evento.
            tope = max(0, self.cfg.retraso_offline_max_dias * _DIA_MS - 1_000)
            sync = reales[-1] + self.ms(0, tope)
            servidor = [sync + timedelta(milliseconds=10 * i) for i in range(len(reales))]
        else:
            servidor = [r + self.ms(100, 500) for r in reales]

        eventos = []
        filas = zip(s.pasos, reales, servidor, strict=True)
        for i, ((tipo, _, pos), real, srv) in enumerate(filas):
            valores = (
                "1.0",
                str(det_uuid(semilla, "f2a-evento", n, i)),
                tipo,
                u.usuario_id,
                s.device_id,
                track,
                session_id,
                _iso(real + desfase),
                _iso(srv),
                pos,
                pais,
                s.is_offline,
            )
            eventos.append(dict(zip(CAMPOS, valores, strict=True)))

        if s.defecto == "evento_sin_fin":
            eventos.pop()  # nunca llega el end ni el skip
        elif s.defecto == "duplicado_por_reintento":
            original = self.rng.choice(eventos)
            reintento = dict(original)
            reintento["server_ts"] = _iso(
                datetime.fromisoformat(original["server_ts"]) + self.ms(1_000, 5_000)
            )
            eventos.append(reintento)
        return eventos, session_id


def generar(fuentes: FuentesSimulador, cfg: SimuladorAvanzadoConfig) -> Simulacion:
    """Función pura: sin reloj del sistema, sin `random` global y sin E/S.

    Los eventos salen en orden de llegada (`server_ts`, y orden de generación ante un empate),
    que es como los vería la cola. Las etiquetas van aparte de los eventos.
    """
    g = _Generador(fuentes, cfg)
    g.planear()
    g.marcar_offline_y_defectos()

    eventos: list[dict] = []
    sesiones: list[EtiquetaSesion] = []
    for n, s in enumerate(g.sesiones):
        evs, session_id = g.emitir(n, s)
        eventos.extend(evs)
        sesiones.append(
            EtiquetaSesion(session_id, s.usuario.usuario_id, s.perfil, s.is_offline, s.defecto)
        )
    orden = sorted(range(len(eventos)), key=lambda i: (eventos[i]["server_ts"], i))
    cuentas = []
    for u in g.usuarios:
        perfil = g.perfil[u.usuario_id]
        etiqueta = "granja" if perfil in PERFILES_GRANJA else "legitima"
        cuentas.append(EtiquetaCuenta(u.usuario_id, etiqueta, perfil))
    return Simulacion([eventos[i] for i in orden], cuentas, sesiones)


# --- E/S -------------------------------------------------------------------------------------


def escribir_etiquetas(sim: Simulacion, directorio: Path) -> tuple[Path, Path]:
    """`cuentas.csv` y `sesiones.csv` en UTF-8 con `\\n`: verdad para EG-43, fuera de la cola."""
    directorio.mkdir(parents=True, exist_ok=True)
    cuentas, sesiones = directorio / "cuentas.csv", directorio / "sesiones.csv"
    with cuentas.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(("cuenta_id", "etiqueta", "perfil"))
        w.writerows((c.cuenta_id, c.etiqueta, c.perfil) for c in sim.cuentas)
    with sesiones.open("w", encoding="utf-8", newline="") as f:
        w = csv.writer(f, lineterminator="\n")
        w.writerow(("session_id", "cuenta_id", "perfil", "is_offline", "defecto"))
        w.writerows(
            (s.session_id, s.cuenta_id, s.perfil, str(s.is_offline).lower(), s.defecto)
            for s in sim.sesiones
        )
    return cuentas, sesiones


def resumen(sim: Simulacion) -> dict:
    """Conteos y proporciones generadas, para el registro de la corrida y la evidencia."""
    perfiles = Counter(c.perfil for c in sim.cuentas)
    normales = [s for s in sim.sesiones if s.perfil == NORMAL]
    defectos = Counter(s.defecto for s in normales if s.defecto)
    n = len(normales) or 1
    return {
        "eventos": len(sim.eventos),
        "cuentas": len(sim.cuentas),
        "perfiles": dict(sorted(perfiles.items())),
        "pct_granjas": round(100 * sum(perfiles[p] for p in PERFILES_GRANJA) / len(sim.cuentas), 3),
        "sesiones": len(sim.sesiones),
        "sesiones_normales": len(normales),
        "pct_offline": round(100 * sum(s.is_offline for s in normales) / n, 3),
        "pct_defectos": {d: round(100 * defectos[d] / n, 3) for d in DEFECTOS},
    }


def ejecutar(
    engine, directorio_f1: Path, salida: Path, etiquetas: Path, cfg: SimuladorAvanzadoConfig
) -> tuple[Simulacion, dict]:
    """Lee las fuentes, genera, valida cada evento contra el esquema F2 y escribe los archivos."""
    fuentes = leer_fuentes(engine, directorio_f1, cfg.mes.replace(day=15))
    sim = generar(fuentes, cfg)
    v = validador()
    for e in sim.eventos:
        v.validate(e)
    escribir(sim.eventos, salida)
    escribir_etiquetas(sim, etiquetas)
    return sim, resumen(sim)


def _defecto(valor: str) -> tuple[str, float]:
    nombre, _, pct = valor.partition("=")
    if nombre not in DEFECTOS or not pct:
        raise argparse.ArgumentTypeError(f"usa NOMBRE=PCT con NOMBRE en {', '.join(DEFECTOS)}")
    return nombre, float(pct)


def main(argv: list[str] | None = None) -> None:
    from sqlalchemy import create_engine

    from sonoraplay.config import database_url

    base = SimuladorAvanzadoConfig()
    p = argparse.ArgumentParser(
        prog="python -m sonoraplay.simulador.f2_avanzado",
        description="Simulador F2 avanzado (EG-51): granjas, offline, defectos y carga pico",
    )
    p.add_argument("--cuentas", type=int, default=base.cuentas)
    p.add_argument("--semilla", type=int, default=base.semilla)
    p.add_argument(
        "--pct-granjas", type=float, default=float(os.environ.get("FARM_PCT", base.pct_granjas))
    )
    p.add_argument("--pct-intensivos", type=float, default=base.pct_intensivos)
    p.add_argument("--pct-offline", type=float, default=base.pct_offline)
    p.add_argument(
        "--defecto", type=_defecto, action="append", default=[], metavar="NOMBRE=PCT",
        help="proporción de un defecto, en %% de las sesiones normales (se puede repetir)",
    )  # fmt: skip
    p.add_argument("--salida", type=Path, default=Path("data/processed/eventos_f2_avanzado.jsonl"))
    p.add_argument("--etiquetas", type=Path, default=Path("data/processed/etiquetas_f2"))
    p.add_argument("--datos-f1", type=Path, default=Path("data/processed"))
    p.add_argument("--pico", action="store_true", help="publica en RabbitMQ a ritmo fijo")
    p.add_argument("--tasa", type=float, default=120.0, help="eventos/s en modo pico")
    p.add_argument("--duracion", type=float, default=60.0, help="segundos en modo pico")
    a = p.parse_args(argv)
    try:
        cfg = replace(
            base,
            cuentas=a.cuentas,
            semilla=a.semilla,
            pct_granjas=a.pct_granjas,
            pct_intensivos=a.pct_intensivos,
            pct_offline=a.pct_offline,
            defectos=replace(base.defectos, **dict(a.defecto)),
        )
    except ValueError as e:
        p.error(str(e))

    sim, res = ejecutar(create_engine(database_url()), a.datos_f1, a.salida, a.etiquetas, cfg)
    print(json.dumps(res, ensure_ascii=False, indent=2), flush=True)
    print(f"{len(sim.eventos)} eventos en {a.salida}; etiquetas en {a.etiquetas}/", flush=True)

    if a.pico:
        from sonoraplay.streaming.carga_pico import publicar_pico
        from sonoraplay.streaming.config import StreamingConfig

        n = math.ceil(a.tasa * a.duracion) + int(a.tasa)  # un segundo de margen
        lineas = [json.dumps(e, ensure_ascii=False, separators=(",", ":")) for e in sim.eventos[:n]]
        r = publicar_pico(StreamingConfig.desde_entorno(), lineas, a.tasa, a.duracion)
        print(json.dumps(r.como_dict(), indent=2), flush=True)
        if not r.cumple():
            raise SystemExit(1)


if __name__ == "__main__":
    main()
