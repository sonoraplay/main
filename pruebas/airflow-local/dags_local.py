# ruff: noqa: E501  (script de pruebas con SQL y comandos largos)
"""Ejecuta los DAG REALES con Airflow 3.1.3 (ejecutor local, sin Celery) y los jobs simulados."""

import os
import shutil
import sys
from datetime import UTC, datetime
from pathlib import Path

os.environ.setdefault("SILVER_COMMITS_URI", "/opt/silver-simulado/commits")
os.environ["SILVER_JOB_COMMAND"] = (
    f"{sys.executable} /var/tmp/wt-dev/pruebas/airflow-local/silver_simulado.py --fecha {{fecha}} --run-id {{run_id}}"
)
os.environ["LIQUIDACION_JOB_COMMAND"] = (
    f"{sys.executable} /var/tmp/wt-dev/pruebas/airflow-local/liquidacion_simulada.py --periodo {{periodo}} --silver-run-id {{silver_run_id}}"
)

import psycopg
from airflow.models import DagBag

from sonoraplay.orquestacion import ingesta_diaria as ing

URL = os.environ["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://", 1)


def sql(q, *a):
    with psycopg.connect(URL) as c:
        cur = c.execute(q, a)
        return cur.fetchall() if cur.description else None


def modo(m, f="modo.txt"):
    Path("/opt/silver-simulado", f).write_text(m)


# F6 y referencia llaman APIs externas: se sustituyen (no son lo que se prueba aquí).
ing.cargar_f6_diaria = lambda *a, **k: 0
ing.refrescar_referencia = lambda *a, **k: {"paises": 0, "publicidad": 0}

bag = DagBag("/var/tmp/wt-dev/dags", include_examples=False)
assert not bag.import_errors, bag.import_errors
diario = bag.dags["sonoraplay_ingesta_diaria"]
mensual = bag.dags["sonoraplay_liquidacion_mensual"]


def correr(dag, fecha_logica):
    run = dag.test(logical_date=fecha_logica)
    return {ti.task_id: str(ti.state) for ti in run.get_task_instances()} if run else None


def L(y, m, d, h=2):
    return datetime(y, m, d, h, tzinfo=UTC)


esc = sys.argv[1]
if esc == "limpiar":
    sql("DELETE FROM ingesta_diaria_estado")
    sql("DELETE FROM corridas_liquidacion")
    sql("DELETE FROM reporte_regalias")
    sql("DELETE FROM liquidaciones")
    shutil.rmtree("/opt/silver-simulado", ignore_errors=True)
    Path("/opt/silver-simulado").mkdir()
    print("limpio")
elif esc == "diario-ok":
    modo("ok")
    print(correr(diario, L(2026, 11, 6)))
    print(
        "estado:",
        sql("SELECT fecha, run_id, silver_run_id FROM ingesta_diaria_estado ORDER BY fecha"),
    )
    print(
        "marcadores:", sorted(p.name for p in Path("/opt/silver-simulado/commits").glob("*.json"))
    )
elif esc == "diario-repetido":
    modo("ok")
    print(correr(diario, L(2026, 11, 6, 3)))
    print(
        "estado:",
        sql("SELECT fecha, run_id, silver_run_id FROM ingesta_diaria_estado ORDER BY fecha"),
    )
elif esc == "diario-sin-marcador":
    modo("sin-marcador")
    try:
        print(correr(diario, L(2026, 11, 8)))
    except Exception as e:
        print("FALLA (esperado):", type(e).__name__, str(e)[:160])
    print(
        "fila 2026-11-07:", sql("SELECT fecha FROM ingesta_diaria_estado WHERE fecha='2026-11-07'")
    )
    modo("ok")
elif esc == "mensual":
    sql(
        "INSERT INTO ingesta_diaria_estado (fecha, run_id, silver_run_id) SELECT d::date,'prueba-manual','prueba-manual.1.'||to_char(d,'YYYYMMDD') FROM generate_series(date '2026-10-01', date '2026-11-02', interval '1 day') d ON CONFLICT (fecha) DO UPDATE SET silver_run_id=EXCLUDED.silver_run_id"
    )
    modo("ok", "modo_liq.txt")
    print(correr(mensual, L(2026, 11, 3, 6)))
    print(correr(mensual, datetime(2026, 11, 3, 6, 0, 1, tzinfo=UTC)))
    print(
        "liquidaciones:",
        sql(
            "SELECT liquidacion_id, periodo, publicada_en IS NOT NULL FROM liquidaciones ORDER BY creada_en"
        ),
    )
    print(
        "corridas:",
        sql("SELECT run_id, estado, duracion_s FROM corridas_liquidacion ORDER BY corrida_id"),
    )
elif esc == "mensual-sin-version":
    modo("sin-version", "modo_liq.txt")
    try:
        print(correr(mensual, datetime(2026, 11, 3, 6, 0, 2, tzinfo=UTC)))
    except Exception as e:
        print("FALLA (esperado):", type(e).__name__, str(e)[:200])
    print(
        "corridas:",
        sql(
            "SELECT run_id, estado, left(detalle,80) FROM corridas_liquidacion ORDER BY corrida_id DESC LIMIT 1"
        ),
    )
    modo("ok", "modo_liq.txt")
