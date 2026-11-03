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
