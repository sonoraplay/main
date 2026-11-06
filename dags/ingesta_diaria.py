"""EG-34 · DAG diario: F6 → referencia → Bronze→Silver (Spark).

CeleryExecutor con RabbitMQ como broker (ver ``airflow/``). Cada tarea es idempotente por
fecha lógica; los reintentos y la política de fallo se declaran en ``default_args``.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.exceptions import AirflowSkipException
from airflow.providers.standard.operators.python import PythonOperator
from airflow.sdk import DAG

from sonoraplay.orquestacion import ingesta_diaria as t
from sonoraplay.orquestacion import liquidacion_mensual as liq

REINTENTOS = 2
ESPERA_ENTRE_REINTENTOS = timedelta(minutes=5)

default_args = {
    "owner": "julian",
    "retries": REINTENTOS,
    "retry_delay": ESPERA_ENTRE_REINTENTOS,
    "retry_exponential_backoff": True,
}


def _f6(logical_date, **_):
    with t.conexion_postgres() as conexion:
        return t.cargar_f6_diaria(t.fecha_procesada(logical_date), conexion)


def _referencia(logical_date, **_):
    with t.conexion_postgres() as conexion:
        return t.refrescar_referencia(t.fecha_procesada(logical_date), conexion)


def _silver(logical_date, run_id, ti, **_):
    # Un intento nuevo, un prefijo nuevo: el run de Silver nunca se reutiliza tras un fallo.
    silver_run = t.run_id_silver(run_id, ti.try_number)
    try:
        t.lanzar_silver(t.fecha_procesada(logical_date), run_id=silver_run)
    except t.SilverNoConfigurado as exc:
        raise AirflowSkipException(str(exc)) from exc
    return silver_run  # XCom: lo lee la verificación


def _verificar(logical_date, ti, **_):
    silver_run = ti.xcom_pull(task_ids="spark_bronze_a_silver")
    t.verificar_silver_publicado(t.fecha_procesada(logical_date), silver_run)
    return silver_run


def _marcar(logical_date, run_id, ti, **_):
    silver_run = ti.xcom_pull(task_ids="verificar_silver_publicado")
    with t.conexion_postgres() as conexion:
        liq.marcar_ingesta(conexion, t.fecha_procesada(logical_date), run_id, silver_run)


with DAG(
    dag_id="sonoraplay_ingesta_diaria",
    description="EG-34: tasas F6, datos de referencia y Bronze → Silver, una vez al día (UTC)",
    schedule="0 2 * * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["sonoraplay", "EG-34", "diario"],
) as dag:
    cargar_f6 = PythonOperator(task_id="cargar_tasas_f6", python_callable=_f6)
    refrescar = PythonOperator(task_id="refrescar_referencia", python_callable=_referencia)
    silver = PythonOperator(task_id="spark_bronze_a_silver", python_callable=_silver)

    verificar = PythonOperator(task_id="verificar_silver_publicado", python_callable=_verificar)

    # Solo corre si Silver terminó: un día omitido (EG-35 sin conectar) no cuenta como ingerido.
    marcar = PythonOperator(task_id="marcar_ingesta_completa", python_callable=_marcar)

    cargar_f6 >> refrescar >> silver >> verificar >> marcar
