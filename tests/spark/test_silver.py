"""EG-35 Spark acceptance tests; run in the dedicated Spark CI job."""

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
    session = (
        SparkSession.builder.master("local[2]")
        .appName("eg35-test")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
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


def test_rn01_exact_30_seconds(spark):
    """RN-01 accepts a single uninterrupted 30-second segment."""
    from datetime import datetime, timedelta

    original = [row.asDict() for row in _events(spark, "duplicado_por_reintento").collect()]
    start = next(e.copy() for e in original if e["event_type"] == "start")
    end = next(e.copy() for e in original if e["event_type"] == "end")
    start["event_id"] = "boundary-start"
    end["event_id"] = "boundary-end"
    end["session_id"] = start["session_id"]
    end["user_id"] = start["user_id"]
    end["device_id"] = start["device_id"]
    end["track_id"] = start["track_id"]
    end["country_playback"] = start["country_playback"]
    end["position_ms"] = start["position_ms"] + 30_000
    end["device_ts"] = (
        (datetime.fromisoformat(start["device_ts"]) + timedelta(seconds=30))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z")
    )
    start["server_ts"] = start["device_ts"]
    end["server_ts"] = end["device_ts"]

    silver, quarantine = transform(
        spark.createDataFrame([start, end], schema=event_schema()), _catalog(spark)
    )
    assert quarantine.count() == 0
    result = silver.first()
    assert result["ms_continuos_max"] == 30_000
    assert result["valida_rn01"] is True
    assert result["pagable"] is True


def test_partitioned_parquet_roundtrip(spark, tmp_path):
    """Verify real Parquet write/read and the required partition columns."""
    silver, quarantine = transform(_events(spark, "duplicado_por_reintento"), _catalog(spark))
    assert quarantine.count() == 0
    target = str(tmp_path / "silver")
    silver.write.mode("errorifexists").partitionBy("year", "month", "country").parquet(target)
    restored = spark.read.parquet(target)
    assert restored.count() == 1
    assert {"year", "month", "country"} <= set(restored.columns)


def test_rn01_29_seconds_is_not_payable(spark):
    """A 29-second uninterrupted play must not pass RN-01."""
    from datetime import datetime, timedelta

    original = [row.asDict() for row in _events(spark, "duplicado_por_reintento").collect()]
    start = next(e.copy() for e in original if e["event_type"] == "start")
    end = next(e.copy() for e in original if e["event_type"] == "end")
    start["event_id"] = "short-start"
    end["event_id"] = "short-end"
    end["position_ms"] = start["position_ms"] + 29_000
    end["device_ts"] = (
        datetime.fromisoformat(start["device_ts"]) + timedelta(seconds=29)
    ).isoformat()
    start["server_ts"] = start["device_ts"]
    end["server_ts"] = end["device_ts"]
    silver, quarantine = transform(
        spark.createDataFrame([start, end], schema=event_schema()), _catalog(spark)
    )
    assert quarantine.count() == 0
    assert silver.first()["ms_continuos_max"] == 29_000
    assert silver.first()["pagable"] is False


def test_rn02_eleventh_play_exceeds_daily_cap(spark):
    """Only the first ten valid plays per user/track/UTC day are payable."""
    from datetime import datetime, timedelta

    original = [row.asDict() for row in _events(spark, "duplicado_por_reintento").collect()]
    start_template = next(e for e in original if e["event_type"] == "start")
    end_template = next(e for e in original if e["event_type"] == "end")
    base = datetime.fromisoformat(start_template["device_ts"])
    events = []
    for number in range(11):
        start = start_template.copy()
        end = end_template.copy()
        start["session_id"] = end["session_id"] = f"daily-{number}"
        start["event_id"] = f"daily-start-{number}"
        end["event_id"] = f"daily-end-{number}"
        start_at = base + timedelta(minutes=5 * number)
        end_at = start_at + timedelta(seconds=35)
        start["device_ts"] = start["server_ts"] = start_at.isoformat()
        end["device_ts"] = end["server_ts"] = end_at.isoformat()
        end["position_ms"] = start["position_ms"] + 35_000
        events.extend([start, end])
    silver, quarantine = transform(
        spark.createDataFrame(events, schema=event_schema()), _catalog(spark)
    )
    assert quarantine.count() == 0
    assert silver.count() == 11
    assert silver.filter("pagable").count() == 10
    assert silver.filter("motivo_validez = 'tope_diario'").count() == 1


@pytest.mark.parametrize(
    ("sync_day", "expected_month", "expected_type"),
    [
        ("2026-10-02", "2026-09-01", "normal"),
        ("2026-10-03", "2026-10-01", "ajuste"),
    ],
)
def test_rn04_offline_cutoff(spark, sync_day, expected_month, expected_type):
    """An offline September play stays in September until the UTC cutoff."""
    from datetime import UTC, datetime, timedelta

    original = [row.asDict() for row in _events(spark, "duplicado_por_reintento").collect()]
    start = next(e.copy() for e in original if e["event_type"] == "start")
    end = next(e.copy() for e in original if e["event_type"] == "end")
    playback = datetime(2026, 9, 28, 12, tzinfo=UTC)
    start["event_id"] = "offline-start"
    end["event_id"] = "offline-end"
    start["is_offline"] = end["is_offline"] = True
    start["device_ts"] = playback.isoformat()
    end["device_ts"] = (playback + timedelta(seconds=35)).isoformat()
    end["position_ms"] = start["position_ms"] + 35_000
    sync = datetime.fromisoformat(f"{sync_day}T23:59:30+00:00")
    start["server_ts"] = (sync - timedelta(seconds=1)).isoformat()
    end["server_ts"] = sync.isoformat()
    silver, quarantine = transform(
        spark.createDataFrame([start, end], schema=event_schema()), _catalog(spark)
    )
    assert quarantine.count() == 0
    row = silver.first()
    assert row["mes_reproduccion"] == "2026-09-01"
    assert row["mes_liquidacion"] == expected_month
    assert row["tipo_atribucion"] == expected_type


def test_lineage_is_preserved_in_silver_and_quarantine(spark):
    """One caller-supplied lineage tuple is preserved for all output rows."""
    events = _events(spark, "track_desconocido")
    silver, quarantine = transform(
        events,
        _catalog(spark),
        run_id="eg35-test-run",
        source_version="fixture-track-desconocido-v1",
        ingested_at_utc="2026-11-03T12:00:00+00:00",
    )
    assert silver.count() == 0
    row = quarantine.first()
    assert row["run_id"] == "eg35-test-run"
    assert row["source_version"] == "fixture-track-desconocido-v1"
    assert row["ingested_at_utc"] == "2026-11-03T12:00:00Z"


def test_lineage_requires_complete_metadata(spark):
    """Do not silently publish partial lineage metadata."""
    with pytest.raises(ValueError, match="must be provided together"):
        transform(
            _events(spark, "duplicado_por_reintento"),
            _catalog(spark),
            run_id="incomplete",
        )


@pytest.mark.parametrize(
    ("field", "invalid_value"),
    [("event_id", None), ("session_id", ""), ("country_playback", None)],
)
def test_reject_missing_required_bronze_values(spark, field, invalid_value):
    """A declared StructType does not validate non-null JSON at runtime."""
    rows = [row.asDict() for row in _events(spark, "duplicado_por_reintento").collect()]
    rows[0][field] = invalid_value
    from pyspark.sql.types import StructField, StructType

    schema = StructType(
        [StructField(item.name, item.dataType, True) for item in event_schema().fields]
    )
    with pytest.raises(ValueError, match="mandatory F2 fields"):
        transform(spark.createDataFrame(rows, schema=schema), _catalog(spark))


def test_quarantine_conflicting_playback_countries(spark):
    """A session must not silently inherit an arbitrary playback country."""
    rows = [row.asDict() for row in _events(spark, "duplicado_por_reintento").collect()]
    next(row for row in rows if row["event_type"] == "end")["country_playback"] = "ZZ"
    silver, quarantine = transform(
        spark.createDataFrame(rows, schema=event_schema()), _catalog(spark)
    )
    assert silver.count() == 0
    assert quarantine.first()["motivo_cuarentena"] == "pais_reproduccion_inconsistente"


def test_reject_duplicate_catalog_track(spark):
    """A duplicated F1 key could multiply Silver rows during the join."""
    catalog = spark.createDataFrame([(TRACK,), (TRACK,)], ["track_id"])
    with pytest.raises(ValueError, match="exactly one row"):
        transform(_events(spark, "duplicado_por_reintento"), catalog)
