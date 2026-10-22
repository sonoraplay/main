"""Pruebas de aceptación de EG-51 · simulador F2 avanzado (criterios 2 a 6).

Cada criterio se mide sobre los **eventos**, no sobre las etiquetas: las etiquetas tienen que
coincidir con lo que un consumidor vería en la cola. El criterio 1 (carga pico en RabbitMQ) está
en `tests/streaming/test_carga_pico.py`.
"""

import csv
import json
import random
import statistics
from collections import Counter, defaultdict
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from sonoraplay.catalogo import __main__ as catalogo_cli
from sonoraplay.config import (
    AtribucionOfflineConfig,
    ContratosConfig,
    DefectosF2Config,
    SeedConfig,
    SimuladorAvanzadoConfig,
)
from sonoraplay.reglas.atribucion import corregir_reloj_sesion
from sonoraplay.reglas.fraude import Reproduccion, SenalFraude, evaluar_cuentas
from sonoraplay.reglas.sesiones import deduplicar, tramos
from sonoraplay.seed import f3_suscripciones, f4_contratos
from sonoraplay.simulador import f2_avanzado as cli
from sonoraplay.simulador.f2_avanzado import (
    DEFECTOS,
    GRANJA_ARTISTA,
    GRANJA_DISPOSITIVO,
    GRANJA_HORAS,
    INTENSIVO,
    NORMAL,
    PERFILES_GRANJA,
    ejecutar,
    escribir_etiquetas,
    generar,
)
from sonoraplay.simulador.f2_minimo import CAMPOS, FuentesSimulador, Pista, Usuario, validador

MUESTRA_F1 = Path(__file__).resolve().parents[2] / "data" / "samples" / "f1_muestra.csv"
CFG = SimuladorAvanzadoConfig()  # 10.000 cuentas, 5 % de granjas, 2 % por defecto
TOLERANCIA_PTS = 1.0
SENAL_DEL_PERFIL = {
    GRANJA_HORAS: SenalFraude.HORAS_24H,
    GRANJA_ARTISTA: SenalFraude.CONCENTRACION_ARTISTA,
    GRANJA_DISPOSITIVO: SenalFraude.DISPOSITIVO_COMPARTIDO,
}


def _fuentes(n_usuarios: int, n_pistas: int = 3_000, n_artistas: int = 300) -> FuentesSimulador:
    r = random.Random(1)
    usuarios = tuple(
        Usuario(f"00000000-0000-4000-8000-{i:012d}", None if i % 10 == 0 else r.choice("CMB") + "O")
        for i in range(n_usuarios)
    )
    pistas = tuple(
        Pista(f"{i:04d}" + "x" * 18, r.randint(90_000, 360_000), f"artista-{i % n_artistas}")
        for i in range(n_pistas)
    )
    return FuentesSimulador(usuarios, pistas)


@pytest.fixture(scope="module")
def fuentes() -> FuentesSimulador:
    return _fuentes(12_000)


@pytest.fixture(scope="module")
def sim(fuentes):
    return generar(fuentes, CFG)


@pytest.fixture(scope="module")
def sesiones(sim) -> dict[str, list[dict]]:
    """Eventos por sesión, ordenados por `device_ts` y `server_ts`."""
    por = defaultdict(list)
    for e in sim.eventos:
        por[e["session_id"]].append(e)
    for evs in por.values():
        evs.sort(key=lambda e: (e["device_ts"], e["server_ts"]))
    return dict(por)


@pytest.fixture(scope="module")
def etiqueta_sesion(sim):
    return {s.session_id: s for s in sim.sesiones}


@pytest.fixture(scope="module")
def perfil(sim):
    return {c.cuenta_id: c.perfil for c in sim.cuentas}


def _ts(valor: str) -> datetime:
    return datetime.fromisoformat(valor)


def _pct(parte: int, total: int) -> float:
    return 100 * parte / total


def reproducciones_fraude(eventos, fuentes) -> list[Reproduccion]:
    """Reproducciones para RN-03, por los pasos de `docs/datos/eventos-f2.md` (1 a 6).

    Las de track desconocido van a cuarentena (no entran en RN-03), como dice el defecto 3.
    """
    artista = {p.track_id: p.artista for p in fuentes.pistas}
    por = defaultdict(list)
    for e in deduplicar(eventos):
        por[e["session_id"]].append(e)
    reps = []
    for crudos in por.values():
        evs = corregir_reloj_sesion(crudos, AtribucionOfflineConfig())
        evs.sort(key=lambda e: (_ts(e["device_ts"]), _ts(e["server_ts"])))
        start = next((e for e in evs if e["event_type"] == "start"), None)
        if start is None or start["track_id"] not in artista:
            continue
        reps.append(
            Reproduccion(
                cuenta_id=start["user_id"],
                dispositivo_id=start["device_id"],
                artista_id=artista[start["track_id"]],
                inicio=_ts(start["device_ts"]),
                ms_escuchados=sum(tramos(evs)),
            )
        )
    return reps


@pytest.fixture(scope="module")
def fraude(sim, fuentes):
    reps = [
        r
        for r in reproducciones_fraude(sim.eventos, fuentes)
        if (r.inicio.year, r.inicio.month) == (CFG.mes.year, CFG.mes.month)
    ]
    return evaluar_cuentas(reps, CFG.fraude)


# --- Criterio 2 · granjas: 5 % ± 1 pt sobre 10.000 cuentas ------------------------------------


def test_diez_mil_cuentas_con_5_por_ciento_de_granjas(sim):
    assert len(sim.cuentas) == 10_000
    granjas = sum(c.etiqueta == "granja" for c in sim.cuentas)
    assert abs(_pct(granjas, len(sim.cuentas)) - 5) <= TOLERANCIA_PTS
    assert {c.perfil for c in sim.cuentas if c.etiqueta == "granja"} == set(PERFILES_GRANJA)


@pytest.mark.parametrize("pct", [0.0, 1.0, 2.5, 5.0, 7.5, 12.0])
def test_farm_pct_configurable_dentro_de_1_punto(pct):
    s = generar(_fuentes(1_000, 600, 60), replace(CFG, cuentas=1_000, pct_granjas=pct))
    granjas = sum(c.etiqueta == "granja" for c in s.cuentas)
    assert abs(_pct(granjas, 1_000) - pct) <= TOLERANCIA_PTS


def test_cada_granja_cumple_la_senal_de_su_perfil(sim, fraude, perfil):
    granjas = [c.cuenta_id for c in sim.cuentas if c.etiqueta == "granja"]
    for cuenta in granjas:
        assert SENAL_DEL_PERFIL[perfil[cuenta]] in fraude[cuenta].senales, (cuenta, perfil[cuenta])


def test_granjas_de_horas_escuchan_mas_de_20_h_en_24_h(sim, sesiones, perfil):
    por_cuenta = defaultdict(int)
    for evs in sesiones.values():
        if perfil[evs[0]["user_id"]] == GRANJA_HORAS:
            por_cuenta[evs[0]["user_id"]] += sum(tramos(evs))
    assert por_cuenta and all(ms > 20 * 3_600_000 for ms in por_cuenta.values())


def test_granjas_de_dispositivo_comparten_con_mas_de_5_cuentas(sesiones, perfil):
    cuentas = defaultdict(set)
    for evs in sesiones.values():
        cuentas[evs[0]["device_id"]].add(evs[0]["user_id"])
    compartidos = [c for c in cuentas.values() if len(c) > 1]
    assert compartidos and all(len(c) > 5 for c in compartidos)
    assert all(perfil[u] == GRANJA_DISPOSITIVO for c in compartidos for u in c)


# --- Criterio 3 · oyentes intensivos legítimos (falsos positivos) -----------------------------


def test_intensivos_escuchan_muchas_horas_con_artistas_variados(sim, sesiones, perfil, fuentes):
    artista = {p.track_id: p.artista for p in fuentes.pistas}
    horas = defaultdict(int)
    artistas = defaultdict(Counter)
    for evs in sesiones.values():
        u = evs[0]["user_id"]
        if perfil[u] == INTENSIVO:
            horas[u] += sum(tramos(evs))
            artistas[u][artista[evs[0]["track_id"]]] += 1
    assert len(horas) == CFG.n_intensivos
    for u, ms in horas.items():
        assert 12 * 3_600_000 <= ms < 20 * 3_600_000
        top = artistas[u].most_common(1)[0][1] / sum(artistas[u].values())
        assert top <= 0.5 and len(artistas[u]) >= 2


def test_ningun_intensivo_es_marcado_por_rn03(sim, fraude, perfil):
    intensivos = [c for c, p in perfil.items() if p == INTENSIVO]
    assert intensivos
    assert [c for c in intensivos if fraude[c].sospechosa] == []


# --- Criterio 4 · offline con 0 a 30 días de retraso ------------------------------------------


def test_sesiones_offline_llegan_de_0_a_30_dias_tarde(sesiones, etiqueta_sesion):
    retrasos = []
    for sid, evs in sesiones.items():
        offline = {e["is_offline"] for e in evs}
        assert len(offline) == 1  # una sesión es toda offline o toda online
        assert offline == {etiqueta_sesion[sid].is_offline}
        if offline == {True}:
            assert all(_ts(e["server_ts"]) >= _ts(e["device_ts"]) for e in evs)
            ultimo = max(evs, key=lambda e: e["device_ts"])
            retrasos.append(_ts(ultimo["server_ts"]) - _ts(ultimo["device_ts"]))
    assert retrasos
    assert all(timedelta(0) <= r <= timedelta(days=30) for r in retrasos)
    assert min(retrasos) < timedelta(days=1) and max(retrasos) > timedelta(days=29)


def test_proporcion_offline_configurada(sim):
    normales = [s for s in sim.sesiones if s.perfil == NORMAL]
    assert abs(_pct(sum(s.is_offline for s in normales), len(normales)) - 10) <= TOLERANCIA_PTS


# --- Criterio 5 · los 5 defectos, en su proporción ± 1 pt -------------------------------------


def _detectar_defectos(sesiones, fuentes) -> dict[str, set[str]]:
    """Detecta cada defecto mirando solo los eventos (como lo haría calidad de datos)."""
    catalogo = {p.track_id for p in fuentes.pistas}
    pais_f3 = {u.usuario_id: u.pais_facturacion for u in fuentes.usuarios}
    tolerancia = timedelta(seconds=AtribucionOfflineConfig().tolerancia_reloj_segundos)
    hallados = defaultdict(set)
    for sid, evs in sesiones.items():
        if evs[-1]["event_type"] not in {"end", "skip"}:
            hallados["evento_sin_fin"].add(sid)
        if not evs[0]["is_offline"]:
            desfase = statistics.median(_ts(e["server_ts"]) - _ts(e["device_ts"]) for e in evs)
            if abs(desfase) > tolerancia:
                hallados["reloj_desfasado"].add(sid)
        if evs[0]["track_id"] not in catalogo:
            hallados["track_desconocido"].add(sid)
        if len({e["event_id"] for e in evs}) < len(evs):
            hallados["duplicado_por_reintento"].add(sid)
        f3 = pais_f3[evs[0]["user_id"]]
        if f3 and evs[0]["country_playback"] != f3:
            hallados["pais_facturacion_distinto"].add(sid)
    return hallados


def test_cada_defecto_se_ve_en_los_eventos_y_coincide_con_su_etiqueta(sesiones, sim, fuentes):
    hallados = _detectar_defectos(sesiones, fuentes)
    for defecto in DEFECTOS:
        etiquetadas = {s.session_id for s in sim.sesiones if s.defecto == defecto}
        assert etiquetadas and hallados[defecto] == etiquetadas, defecto


def test_cada_defecto_en_2_por_ciento_de_las_sesiones_normales(sesiones, sim, fuentes):
    normales = sum(s.perfil == NORMAL for s in sim.sesiones)
    for defecto, sids in _detectar_defectos(sesiones, fuentes).items():
        assert abs(_pct(len(sids), normales) - 2) <= TOLERANCIA_PTS, defecto


@pytest.mark.parametrize(
    "defectos",
    [
        DefectosF2Config(0, 0, 0, 0, 0),
        DefectosF2Config(5, 1, 3, 0.5, 7.5),
        DefectosF2Config(10, 10, 10, 10, 10),
    ],
)
def test_proporciones_de_defectos_configurables(defectos):
    fuentes = _fuentes(2_000, 600, 60)
    s = generar(fuentes, replace(CFG, cuentas=2_000, defectos=defectos))
    por = defaultdict(list)
    for e in s.eventos:
        por[e["session_id"]].append(e)
    for evs in por.values():
        evs.sort(key=lambda e: (e["device_ts"], e["server_ts"]))
    hallados = _detectar_defectos(por, fuentes)
    normales = sum(x.perfil == NORMAL for x in s.sesiones)
    for defecto, pct in defectos.como_dict().items():
        assert abs(_pct(len(hallados[defecto]), normales) - pct) <= TOLERANCIA_PTS, defecto


# --- Criterio 6 · semilla, esquema y etiquetas aparte -----------------------------------------


def test_misma_semilla_mismos_eventos_y_etiquetas():
    fuentes = _fuentes(1_500, 600, 60)
    cfg = replace(CFG, cuentas=1_500)
    assert generar(fuentes, cfg) == generar(fuentes, cfg)
    assert generar(fuentes, cfg).eventos != generar(fuentes, replace(cfg, semilla=7)).eventos


def test_todos_los_eventos_validan_contra_el_esquema(sim):
    v = validador()
    errores = [(e["event_id"], err.message) for e in sim.eventos for err in v.iter_errors(e)]
    assert errores == []
    assert all(list(e) == list(CAMPOS) for e in sim.eventos)  # sin campos de etiqueta


def test_eventos_en_orden_de_llegada_y_ids_unicos_salvo_reintentos(sim, etiqueta_sesion):
    assert [e["server_ts"] for e in sim.eventos] == sorted(e["server_ts"] for e in sim.eventos)
    repetidos = [i for i, n in Counter(e["event_id"] for e in sim.eventos).items() if n > 1]
    por_id = {e["event_id"]: e["session_id"] for e in sim.eventos}
    defectos = {etiqueta_sesion[por_id[i]].defecto for i in repetidos}
    assert defectos == {"duplicado_por_reintento"}


def test_etiquetas_cubren_todas_las_cuentas_y_sesiones(sim, sesiones):
    assert {e["user_id"] for e in sim.eventos} <= {c.cuenta_id for c in sim.cuentas}
    assert {s.session_id for s in sim.sesiones} == set(sesiones)


def test_etiquetas_en_csv_aparte(sim, tmp_path):
    cuentas, ses = escribir_etiquetas(sim, tmp_path / "etiquetas")
    filas = list(csv.DictReader(cuentas.open(encoding="utf-8")))
    assert len(filas) == len(sim.cuentas)
    assert Counter(f["etiqueta"] for f in filas)["granja"] == CFG.n_granjas
    assert {f["etiqueta"] for f in filas} == {"granja", "legitima"}
    filas = list(csv.DictReader(ses.open(encoding="utf-8")))
    assert len(filas) == len(sim.sesiones)
    assert b"\r\n" not in cuentas.read_bytes() + ses.read_bytes()


# --- Configuración y CLI ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "cambios",
    [
        {"pct_granjas": 101},
        {"pct_granjas": 60, "pct_intensivos": 50},
        {"horas_granja": (19, 23)},
        {"horas_intensivo": (12, 21)},
        {"cuentas_por_dispositivo_granja": 5},
        {"fraccion_artista_granja": 0.7},
        {"retraso_offline_max_dias": 31},
        {"pct_offline": 95},
    ],
)
def test_configuracion_invalida_lanza_value_error(cambios):
    with pytest.raises(ValueError):
        replace(CFG, **cambios)


def test_defectos_que_suman_mas_de_100_lanzan_value_error():
    with pytest.raises(ValueError, match="más de 100"):
        DefectosF2Config(50, 50, 1, 0, 0)


def test_pocas_cuentas_en_las_fuentes_lanza_error():
    with pytest.raises(ValueError, match="solo tienen 100 usuarios"):
        generar(_fuentes(100, 600, 60), CFG)


def test_la_cli_rechaza_un_defecto_desconocido(capsys):
    with pytest.raises(SystemExit):
        cli.main(["--defecto", "inventado=3"])


# --- Integración con PostgreSQL, el catálogo F1 de muestra y la CLI ----------------------------


def test_extremo_a_extremo_con_f1_f3_f4_y_cli(db_vacia, tmp_path, monkeypatch, capsys):
    f3_suscripciones.ejecutar(db_vacia, SeedConfig(usuarios=400))
    f1 = tmp_path / "f1"
    catalogo_cli.main(["--entrada", str(MUESTRA_F1), "--salida", str(f1), "--titulares", "50"])
    f4_contratos.ejecutar(db_vacia, f1, ContratosConfig())

    cfg = replace(CFG, cuentas=300, pct_intensivos=0)
    a, etq_a = tmp_path / "a.jsonl", tmp_path / "etq_a"
    sim, res = ejecutar(db_vacia, f1, a, etq_a, cfg)
    assert res["eventos"] == len(sim.eventos) and res["pct_granjas"] == 5.0

    monkeypatch.setenv("DATABASE_URL", db_vacia.url.render_as_string(hide_password=False))
    monkeypatch.setenv("FARM_PCT", "5")
    b, etq_b = tmp_path / "b.jsonl", tmp_path / "etq_b"
    args = ["--cuentas", "300", "--pct-intensivos", "0", "--datos-f1", str(f1)]
    cli.main([*args, "--salida", str(b), "--etiquetas", str(etq_b)])
    assert '"pct_granjas": 5.0' in capsys.readouterr().out

    assert a.read_bytes() == b.read_bytes()  # misma semilla: mismo archivo, byte por byte
    assert (etq_a / "cuentas.csv").read_bytes() == (etq_b / "cuentas.csv").read_bytes()
    eventos = [json.loads(x) for x in a.read_text(encoding="utf-8").splitlines()]
    assert len(eventos) == res["eventos"]
    assert all(_ts(e["device_ts"]).tzinfo == UTC for e in eventos)
