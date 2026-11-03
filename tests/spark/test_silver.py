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


def test_cli_rejects_invalid_date():
    """Airflow must not silently accept a malformed processing day."""
    from sonoraplay.spark.silver import main

    with pytest.raises(SystemExit) as exc:
        main(["--fecha", "2026-02-30"])
    assert exc.value.code != 0


def test_cli_refuses_unsafe_daily_publication(tmp_path):
    """Never report a successful Airflow run before idempotent publication exists."""
    from sonoraplay.spark.silver import main

    args = [
        "--fecha",
        "2026-09-17",
        "--bronze",
        str(tmp_path / "bronze"),
        "--catalogo",
        str(tmp_path / "catalog"),
        "--silver",
        str(tmp_path / "silver"),
        "--cuarentena",
        str(tmp_path / "quarantine"),
        "--run-id",
        "test-run",
        "--source-version",
        "fixture-v1",
    ]
    with pytest.raises(SystemExit) as exc:
        main(args)
    assert exc.value.code != 0
    assert not (tmp_path / "silver").exists()
    assert not (tmp_path / "quarantine").exists()


def test_bronze_window_uses_month_to_date():
    """RN-02 must be computed with earlier days in the same UTC month."""
    from datetime import date

    from sonoraplay.spark.silver import bronze_window

    assert bronze_window(date(2026, 9, 17))[0] == date(2026, 9, 1)
    assert bronze_window(date(2026, 9, 17))[-1] == date(2026, 9, 17)
    assert len(bronze_window(date(2026, 9, 17))) == 17


def test_bronze_window_includes_previous_month_during_rn04_grace():
    """The first three days must also inspect the prior month's arrivals."""
    from datetime import date

    from sonoraplay.spark.silver import bronze_window

    assert bronze_window(date(2026, 10, 2))[0] == date(2026, 9, 1)
    assert bronze_window(date(2026, 10, 2))[-1] == date(2026, 10, 2)
    assert bronze_window(date(2026, 10, 4))[0] == date(2026, 10, 1)


def test_bronze_paths_match_eg33_layout():
    """No accidental day partitioning of Silver or wrong Bronze prefix."""
    from datetime import date

    from sonoraplay.spark.silver import bronze_partition_paths

    paths = bronze_partition_paths("s3a://bronze/f2/", date(2026, 9, 2))
    assert paths[0] == "s3a://bronze/f2/fecha=2026-08-01"
    assert paths[-2:] == [
        "s3a://bronze/f2/fecha=2026-09-01",
        "s3a://bronze/f2/fecha=2026-09-02",
    ]
    assert len(paths) == 33


def test_read_bronze_window_reads_eg33_jsonl(spark, tmp_path):
    """Read the actual day-partition layout with an explicit F2 schema."""
    from datetime import date

    from sonoraplay.spark.silver import read_bronze_window

    root = tmp_path / "f2"
    for day in ("2026-09-01", "2026-09-02"):
        partition = root / f"fecha={day}"
        partition.mkdir(parents=True)
        rows = [row.asDict() for row in _events(spark, "duplicado_por_reintento").collect()]
        (partition / "lote-0001.jsonl").write_text(
            "\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8"
        )
    events = read_bronze_window(spark, str(root), date(2026, 9, 2))
    assert events.count() == 2 * len(rows)
    assert events.schema.fieldNames() == event_schema().fieldNames()


def test_read_bronze_window_requires_target_day(spark, tmp_path):
    """Airflow must fail rather than silently publish an empty day."""
    from datetime import date

    from sonoraplay.spark.silver import read_bronze_window

    partition = tmp_path / "f2" / "fecha=2026-09-01"
    partition.mkdir(parents=True)
    (partition / "lote-0001.jsonl").write_text("{}\n", encoding="utf-8")
    with pytest.raises(FileNotFoundError, match="2026-09-02"):
        read_bronze_window(spark, str(tmp_path / "f2"), date(2026, 9, 2))


def test_affected_months_include_late_offline_playback(spark):
    """The playback month, not the Bronze arrival month, drives replay."""
    from sonoraplay.spark.silver import affected_playback_months

    silver = spark.createDataFrame(
        [("2026-08-31T23:59:00+00:00",), ("2026-09-01T00:01:00+00:00",)],
        ["inicio_utc"],
    )
    quarantine = spark.createDataFrame(
        [("2026-07-15T10:00:00+00:00",)],
        ["inicio_utc"],
    )
    assert affected_playback_months(silver, quarantine) == [
        "2026-07",
        "2026-08",
        "2026-09",
    ]


def test_replay_coverage_rejects_missing_older_month():
    """Never publish if an offline event affects an unrebuilt month."""
    from sonoraplay.spark.silver import validate_replay_coverage

    with pytest.raises(ValueError, match="2026-07"):
        validate_replay_coverage(["2026-07", "2026-09"], ["2026-09"])
    assert validate_replay_coverage(["2026-07", "2026-09"], ["2026-07", "2026-09"])


def test_replay_coverage_rejects_invalid_month():
    from sonoraplay.spark.silver import validate_replay_coverage

    with pytest.raises(ValueError, match="Invalid playback month"):
        validate_replay_coverage(["2026-13"], ["2026-13"])


def _synthetic_plays(spark, durations_ms):
    """Build complete F2 sessions without changing the production business rules."""
    from datetime import UTC, datetime, timedelta

    template = json.loads(
        (FIXTURES / "duplicado_por_reintento.json").read_text(encoding="utf-8")
    )["eventos"]
    start_template = next(event for event in template if event["event_type"] == "start")
    end_template = next(event for event in template if event["event_type"] == "end")
    base = datetime(2026, 9, 19, 0, 0, tzinfo=UTC)
    events = []
    for index, duration in enumerate(durations_ms):
        start_time = base + timedelta(minutes=index * 10)
        end_time = start_time + timedelta(milliseconds=duration)
        session = f"session-{index:03d}"
        for kind, source, moment, position in (
            ("start", start_template, start_time, 0),
            ("end", end_template, end_time, duration),
        ):
            event = source.copy()
            event.update(
                event_id=f"{session}-{kind}",
                session_id=session,
                device_ts=moment.isoformat().replace("+00:00", "Z"),
                server_ts=(moment + timedelta(milliseconds=200))
                .isoformat()
                .replace("+00:00", "Z"),
                position_ms=position,
            )
            events.append(event)
    return spark.createDataFrame(events, schema=event_schema())


def test_rn01_29_seconds_is_not_payable(spark):
    """RN-01: below 30 seconds must not earn royalties."""
    silver, quarantine = transform(_synthetic_plays(spark, [29_000]), _catalog(spark))
    row = silver.first()
    assert quarantine.count() == 0
    assert row["ms_continuos_max"] == 29_000
    assert row["valida_rn01"] is False
    assert row["pagable"] is False
    assert row["motivo_validez"] == "duracion_insuficiente"


def test_rn02_eleventh_valid_play_is_not_payable(spark):
    """RN-02: the cap is 10 valid plays per user, track and UTC day."""
    silver, quarantine = transform(
        _synthetic_plays(spark, [30_000] * 11), _catalog(spark)
    )
    assert quarantine.count() == 0
    rows = {row["play_id"]: row for row in silver.collect()}
    assert len(rows) == 11
    assert sum(row["pagable"] for row in rows.values()) == 10
    assert rows["session-010"]["pagable"] is False
    assert rows["session-010"]["motivo_validez"] == "tope_diario"


def test_rn02_replay_of_complete_month_is_deterministic(spark):
    """Replaying identical full-month events does not change logical plays."""
    events = _synthetic_plays(spark, [30_000] * 11)
    first, _ = transform(events, _catalog(spark))
    second, _ = transform(events, _catalog(spark))
    fields = ("play_id", "pagable", "motivo_validez", "inicio_utc")
    def snapshot(frame):
        return sorted(
            tuple(row[name] for name in fields) for row in frame.collect()
        )
    assert snapshot(first) == snapshot(second)
