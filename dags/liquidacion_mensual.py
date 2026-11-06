"""EG-38 · DAG mensual: el día 3 de cada mes (UTC) liquida el mes anterior.

Espera a que la ingesta diaria del mes (y los 2 días de gracia de RN-04) esté completa,
corre el job de liquidación (EG-37) y registra la duración (meta RNF-01 < 1 h). Cada corrida
crea una versión nueva de la liquidación (ADR-0007); nunca sobrescribe la anterior.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.exceptions import AirflowSkipException
from airflow.providers.standard.operators.python import PythonOperator
from airflow.providers.standard.sensors.python import PythonSensor
from airflow.sdk import DAG

from sonoraplay.orquestacion import ingesta_diaria as ing
from sonoraplay.orquestacion import liquidacion_mensual as liq

default_args = {
    "owner": "julian",
    "retries": 2,
    "retry_delay": timedelta(minutes=10),
    "retry_exponential_backoff": True,
    # Se ejecuta solo al agotar los reintentos: deja el error en el log y avisa por SNS.
    "on_failure_callback": liq.notificar_fallo,
}


def _ingesta_lista(logical_date, **_):
    with ing.conexion_postgres() as conexion:
        return liq.ingesta_completa(conexion, liq.periodo_a_liquidar(logical_date))


def _liquidar(logical_date, run_id, **_):
    with ing.conexion_postgres() as conexion:
        try:
            periodo = liq.periodo_a_liquidar(logical_date)
            return liq.liquidar(
                periodo,
                conexion,
                run_id,
                silver_run_id=liq.silver_run_id_del_periodo(conexion, periodo),
            )
        except liq.LiquidacionNoConfigurada as exc:
            raise AirflowSkipException(str(exc)) from exc


with DAG(
    dag_id="sonoraplay_liquidacion_mensual",
    description="EG-38: liquida el mes anterior el día 3 (UTC), con versión nueva en cada corrida",
    schedule="0 6 3 * *",
    start_date=datetime(2026, 10, 1),
    catchup=False,
    max_active_runs=1,
    default_args=default_args,
    tags=["sonoraplay", "EG-38", "mensual"],
) as dag:
    esperar_ingesta = PythonSensor(
        task_id="esperar_ingesta_diaria",
        python_callable=_ingesta_lista,
        mode="reschedule",
        poke_interval=15 * 60,
        timeout=12 * 60 * 60,
        retries=0,
    )
    liquidar = PythonOperator(task_id="liquidar_mes", python_callable=_liquidar)

    esperar_ingesta >> liquidar
