"""EG-35 Spark acceptance tests. Run with: uv run --with pyspark pytest tests/spark."""
import json
from pathlib import Path

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from pyspark.sql import SparkSession

from sonoraplay.spark.silver import event_schema, transform

FIXTURES = Path(__file__).resolve().parents[2] / "schemas" / "ejemplos" / "defectos"
TRACK = "23Mcmg5O8rBKAOzxvrTjnD"


@pytest.fixture(scope="module")
def spark():
    session = (SparkSession.builder.master("local[2]").appName("eg35-test")
               .config("spark.sql.session.timeZone", "UTC")
               .getOrCreate())
    yield session
    session.stop()


def _events(spark, name):
    data = json.loads((FIXTURES / f"{name}.json").read_text(encoding="utf-8"))
    return spark.createDataFrame(data["eventos"], schema=event_schema())


def _catalog(spark):
    return spark.createDataFrame([(TRACK,)], ["track_id"])


def test_retries_keep_one_play(spark):
    silver, quarantine = transform(_events(spark, "duplicado_por_reintento"), _catalog(spark))
    assert silver.count() == 1
    assert quarantine.count() == 0
    assert silver.first()["ms_continuos_max"] == 210_760


def test_clock_correction_preserves_duration(spark):
    silver, _ = transform(_events(spark, "reloj_desfasado"), _catalog(spark))
    row = silver.first()
    assert row["inicio_utc"].startswith("2026-09-17T14:00:00.250")
    assert row["ms_continuos_max"] == 210_760


def test_unknown_track_is_quarantined(spark):
    silver, quarantine = transform(_events(spark, "track_desconocido"), _catalog(spark))
    assert silver.count() == 0
    assert quarantine.first()["motivo_cuarentena"] == "track_desconocido"


def test_unclosed_segment_counts_only_closed_segments(spark):
    silver, _ = transform(_events(spark, "evento_sin_fin"), _catalog(spark))
    assert silver.first()["ms_continuos_max"] == 40_000
