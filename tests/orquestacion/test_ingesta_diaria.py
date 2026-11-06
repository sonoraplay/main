"""EG-34 · Tareas del DAG diario: idempotencia por fecha, referencia y contrato con Silver."""

import os
import sys
from datetime import date

import psycopg
import pytest

from sonoraplay.fuentes.f6_tasas import MONEDAS
from sonoraplay.fuentes.f7_paises import REST_COUNTRIES
from sonoraplay.orquestacion import ingesta_diaria as t

FECHA = date(2026, 9, 15)  # martes


def frankfurter(url: str):
    """Respuesta v2 falsa: una cotización por moneda para el 14 y el 15 de septiembre."""
    return [
        {"date": dia, "base": "USD", "quote": moneda, "rate": 100 + i + k / 10}
        for i, moneda in enumerate(MONEDAS)
        for k, dia in enumerate(("2026-09-14", "2026-09-15"))
    ]


def paises(url: str):
    codigos = [f"{chr(65 + i // 26)}{chr(65 + i % 26)}" for i in range(210)]
    monedas = dict(zip(("AR", "BR", "CL", "CO", "MX", "PE"), MONEDAS, strict=True))
    return [
        {
            "cca2": c,
            "region": "Americas",
            "currencies": {monedas[c]: {}} if c in monedas else {"USD": {}},
        }
        for c in codigos
    ] + [
        {"cca2": c, "region": "Americas", "currencies": {m: {}}}
        for c, m in monedas.items()
        if c not in codigos
    ]


def obtener(url: str):
    return paises(url) if url == REST_COUNTRIES else frankfurter(url)


@pytest.fixture
def conexion():
    url = os.environ.get("EG30_DATABASE_URL")
    if not url:
        pytest.skip("requiere EG30_DATABASE_URL (PostgreSQL con db/ddl/004)")
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1)) as c:
        yield c
        c.rollback()


def contar(conexion, tabla: str) -> int:
    return conexion.execute(f"SELECT count(*) FROM {tabla}").fetchone()[0]  # noqa: S608


def test_f6_diaria_es_idempotente_por_fecha(conexion):
    conexion.execute("DELETE FROM fuente_f6_tasas_diarias")
    primera = t.cargar_f6_diaria(FECHA, conexion, obtener)
    despues_de_una = contar(conexion, "fuente_f6_tasas_diarias")
    segunda = t.cargar_f6_diaria(FECHA, conexion, obtener)
    assert primera == segunda == despues_de_una == len(MONEDAS) * 2
    assert contar(conexion, "fuente_f6_tasas_diarias") == despues_de_una


def test_f6_diaria_acepta_cierre_de_semana(conexion):
    """Un sábado sin cotización propia sigue cubierto por la ventana de la semana previa."""
    assert t.cargar_f6_diaria("2026-09-19", conexion, obtener) == len(MONEDAS) * 2


def test_f6_diaria_rechaza_respuesta_incompleta(conexion):
    sin_pen = [f for f in frankfurter("") if f["quote"] != "PEN"]
    with pytest.raises(ValueError, match="sin cobertura"):
        t.cargar_f6_diaria(FECHA, conexion, lambda _u: sin_pen)


def test_referencia_es_idempotente(conexion):
    r1 = t.refrescar_referencia(FECHA, conexion, obtener)
    f7 = contar(conexion, "fuente_f7_paises")
    f5 = conexion.execute(
        "SELECT count(*) FROM fuente_f5_publicidad WHERE mes = '2026-09-01'"
    ).fetchone()[0]
    r2 = t.refrescar_referencia(FECHA, conexion, obtener)
    assert r1 == r2 and r1["publicidad"] == 6
    assert contar(conexion, "fuente_f7_paises") == f7
    assert (
        conexion.execute(
            "SELECT count(*) FROM fuente_f5_publicidad WHERE mes = '2026-09-01'"
        ).fetchone()[0]
        == f5
        == 6
    )


def test_silver_sin_comando_no_finge_exito():
    with pytest.raises(t.SilverNoConfigurado, match="EG-35"):
        t.lanzar_silver(FECHA, entorno={})


def test_silver_pasa_la_fecha_al_comando(tmp_path):
    marca = tmp_path / "fecha.txt"
    codigo = f"import sys,pathlib; pathlib.Path(r'{marca}').write_text(sys.argv[1])"
    comando = f'"{sys.executable}" -c "{codigo}" {{fecha}}'
    assert t.lanzar_silver("2026-09-15", entorno={t.VARIABLE_COMANDO_SILVER: comando}) == 0
    assert marca.read_text() == "2026-09-15"


def test_silver_propaga_el_fallo_del_job():
    from subprocess import CalledProcessError

    comando = f'"{sys.executable}" -c "raise SystemExit(3)"'
    with pytest.raises(CalledProcessError):
        t.lanzar_silver(FECHA, entorno={t.VARIABLE_COMANDO_SILVER: comando})


def test_la_corrida_de_las_02_procesa_el_dia_anterior_cerrado():
    from datetime import UTC, datetime

    assert t.fecha_procesada(datetime(2026, 11, 3, 2, tzinfo=UTC)) == date(2026, 11, 2)
    assert t.fecha_procesada(datetime(2026, 11, 1, 2, tzinfo=UTC)) == date(2026, 10, 31)


def test_silver_recibe_tambien_el_run_id_para_el_linaje(tmp_path):
    marca = tmp_path / "args.txt"
    codigo = f"import sys,pathlib; pathlib.Path(r'{marca}').write_text(' '.join(sys.argv[1:]))"
    comando = f'"{sys.executable}" -c "{codigo}" --fecha {{fecha}} --run-id {{run_id}}'
    t.lanzar_silver(
        "2026-09-15", entorno={t.VARIABLE_COMANDO_SILVER: comando}, run_id="scheduled__2026-09-16"
    )
    assert marca.read_text() == "--fecha 2026-09-15 --run-id scheduled__2026-09-16"


def _marca(**cambios):
    base = {
        "schema_version": "eg35-commit-v1",
        "run_id": "r.1",
        "fecha": "2026-09-15",
        "silver_rows": 10,
    }
    return {**base, **cambios}


ENV_COMMITS = {t.VARIABLE_COMMITS_SILVER: "s3://b/silver/commits"}


def test_run_id_de_intento_es_valido_y_cambia_con_cada_intento():
    import re

    a = t.run_id_silver("scheduled__2026-09-16T02:00:00+00:00", 1)
    b = t.run_id_silver("scheduled__2026-09-16T02:00:00+00:00", 2)
    assert a != b
    for x in (a, b, t.run_id_silver("x" * 300, 3), t.run_id_silver(":::", 1)):
        assert re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", x), x


def test_verificacion_acepta_un_marcador_valido():
    marca = t.verificar_silver_publicado(
        "2026-09-15", "r.1", ENV_COMMITS, leer=lambda uri, rid: _marca()
    )
    assert marca["silver_rows"] == 10


@pytest.mark.parametrize(
    "cambio",
    [
        {"schema_version": "otro"},
        {"run_id": "otro"},
        {"fecha": "2026-09-14"},
        {"silver_rows": 0},
        {"silver_rows": None},
    ],
)
def test_verificacion_falla_cerrado_con_marcador_invalido(cambio):
    with pytest.raises(t.SilverNoPublicado):
        t.verificar_silver_publicado(
            "2026-09-15", "r.1", ENV_COMMITS, leer=lambda uri, rid: _marca(**cambio)
        )


def test_verificacion_sin_marcador_no_marca_el_dia():
    def sin_marcador(uri, rid):
        raise FileNotFoundError(rid)

    with pytest.raises(t.SilverNoPublicado, match="Sin marcador"):
        t.verificar_silver_publicado("2026-09-15", "r.1", ENV_COMMITS, leer=sin_marcador)


def test_verificacion_sin_uri_configurada():
    with pytest.raises(t.SilverNoConfigurado):
        t.verificar_silver_publicado("2026-09-15", "r.1", {}, leer=lambda u, r: _marca())


def test_el_marcador_tambien_se_lee_de_un_directorio_local(tmp_path):
    import json

    (tmp_path / "r.1.json").write_text(json.dumps(_marca()), encoding="utf-8")
    marca = t.verificar_silver_publicado(
        "2026-09-15", "r.1", {t.VARIABLE_COMMITS_SILVER: str(tmp_path)}
    )
    assert marca["silver_rows"] == 10
    with pytest.raises(t.SilverNoPublicado, match="Sin marcador"):
        t.verificar_silver_publicado(
            "2026-09-15", "otro", {t.VARIABLE_COMMITS_SILVER: str(tmp_path)}
        )
