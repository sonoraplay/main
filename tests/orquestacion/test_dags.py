"""EG-34 criterio 5 · Si algún DAG no importa, esta prueba falla (corre en el job `dags` del CI)."""

from pathlib import Path

import pytest

pytest.importorskip("airflow", reason="Airflow solo está en el job `dags` del CI")

from airflow.models import DagBag  # noqa: E402

DAGS = Path(__file__).resolve().parents[2] / "dags"


@pytest.fixture(scope="module")
def dagbag():
    return DagBag(dag_folder=str(DAGS), include_examples=False)


def test_ningun_dag_falla_al_importar(dagbag):
    assert dagbag.import_errors == {}


def test_hay_dags_cargados(dagbag):
    assert dagbag.dags, "la carpeta dags/ no produjo ningún DAG"


def test_dag_diario_orquesta_f6_referencia_silver(dagbag):
    dag = dagbag.dags["sonoraplay_ingesta_diaria"]
    assert dag.schedule == "0 2 * * *"
    assert dag.catchup is False
    ids = [tarea.task_id for tarea in dag.topological_sort()]
    assert ids == ["cargar_tasas_f6", "refrescar_referencia", "spark_bronze_a_silver"]


def test_todas_las_tareas_reintentan_al_menos_dos_veces(dagbag):
    for dag in dagbag.dags.values():
        for tarea in dag.tasks:
            assert tarea.retries >= 2, f"{dag.dag_id}.{tarea.task_id}"
            assert tarea.retry_delay.total_seconds() > 0, f"{dag.dag_id}.{tarea.task_id}"
