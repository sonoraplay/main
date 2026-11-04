"""EG-35: Spark Silver using the existing F2 business-rule implementations.

Bronze JSON -> deterministic event deduplication -> session reconstruction ->
catalog quarantine -> RN-01/RN-02/RN-04 -> partitioned Silver Parquet.
"""

from __future__ import annotations

from sonoraplay.config import AtribucionOfflineConfig, ReglasValidezConfig
from sonoraplay.reglas.atribucion import atribuir_reproduccion
from sonoraplay.reglas.sesiones import reconstruir


# Import Spark only when the Silver job is invoked; existing services need no Spark.
def event_schema():
    from pyspark.sql.types import (
        BooleanType,
        LongType,
        StringType,
        StructField,
        StructType,
    )

    return StructType(
        [
            StructField("schema_version", StringType(), False),
            StructField("event_id", StringType(), False),
            StructField("event_type", StringType(), False),
            StructField("user_id", StringType(), False),
            StructField("device_id", StringType(), False),
            StructField("track_id", StringType(), False),
            StructField("session_id", StringType(), False),
            StructField("device_ts", StringType(), False),
            StructField("server_ts", StringType(), False),
            StructField("position_ms", LongType(), False),
            StructField("country_playback", StringType(), False),
            StructField("is_offline", BooleanType(), False),
        ]
    )


def play_schema():
    from pyspark.sql.types import (
        BooleanType,
        IntegerType,
        StringType,
        StructField,
        StructType,
    )

    return StructType(
        [
            StructField("play_id", StringType()),
            StructField("user_id", StringType()),
            StructField("track_id", StringType()),
            StructField("country", StringType()),
            StructField("device_id", StringType()),
            StructField("inicio_utc", StringType()),
            StructField("sincronizado_utc", StringType()),
            StructField("ms_continuos_max", IntegerType()),
            StructField("is_offline", BooleanType()),
            StructField("mes_reproduccion", StringType()),
            StructField("mes_liquidacion", StringType()),
            StructField("tipo_atribucion", StringType()),
            StructField("motivo_cuarentena", StringType()),
            StructField("schema_version", StringType()),
        ]
    )


def _session_rows(pdf):
    """One grouped session; delegate clocks and segment logic to existing pure rules."""
    import pandas as pd

    records = pdf.to_dict("records")
    first = min(records, key=lambda e: (e["server_ts"], e["event_id"]))
    if len({(e["user_id"], e["device_id"], e["track_id"]) for e in records}) != 1:
        reason = "identidad_sesion_inconsistente"
    elif len({e["country_playback"] for e in records}) != 1:
        reason = "pais_reproduccion_inconsistente"
    elif len({e["schema_version"] for e in records}) != 1:
        reason = "version_esquema_inconsistente"
    else:
        reason = None

    if reason is None:
        reps = reconstruir(records)
        if not reps:
            reason = "sesion_sin_inicio"
    if reason:
        return pd.DataFrame(
            [
                {
                    "play_id": first["session_id"],
                    "user_id": first["user_id"],
                    "track_id": first["track_id"],
                    "country": first["country_playback"],
                    "device_id": first["device_id"],
                    "inicio_utc": None,
                    "sincronizado_utc": None,
                    "ms_continuos_max": None,
                    "is_offline": first["is_offline"],
                    "mes_reproduccion": None,
                    "mes_liquidacion": None,
                    "tipo_atribucion": None,
                    "motivo_cuarentena": reason,
                    "schema_version": first["schema_version"],
                }
            ]
        )
    if len(reps) != 1:
        raise ValueError("Expected exactly one reconstructed play per session")
    rep = reps[0]
    attribution = atribuir_reproduccion(
        rep.inicio, rep.sincronizado, rep.is_offline, AtribucionOfflineConfig()
    )
    return pd.DataFrame(
        [
            {
                "play_id": rep.reproduccion_id,
                "user_id": rep.cuenta_id,
                "track_id": rep.track_id,
                "country": first["country_playback"],
                "device_id": first["device_id"],
                "inicio_utc": rep.inicio.isoformat(),
                "sincronizado_utc": rep.sincronizado.isoformat(),
                "ms_continuos_max": rep.ms_continuos_max,
                "is_offline": rep.is_offline,
                "mes_reproduccion": attribution.mes_reproduccion.isoformat(),
                "mes_liquidacion": attribution.mes_liquidacion.isoformat(),
                "tipo_atribucion": str(attribution.tipo),
                "motivo_cuarentena": None,
                "schema_version": first["schema_version"],
            }
        ]
    )


def transform(events, catalog, *, run_id=None, source_version=None, ingested_at_utc=None):
    """Return (silver, quarantine), without performing external writes.

    catalog must contain a unique track_id column from F1. All sessions in the
    processing/reprocessing window must be present for a correct RN-02 count.
    """
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    required = set(event_schema().fieldNames())
    missing = required.difference(events.columns)
    if missing:
        raise ValueError(f"Missing required F2 fields: {sorted(missing)}")

    if "track_id" not in catalog.columns:
        raise ValueError("F1 catalog is missing track_id")
    if catalog.filter(F.col("track_id").isNull()).limit(1).count():
        raise ValueError("F1 catalog cannot contain null track_id")
    if catalog.groupBy("track_id").count().filter(F.col("count") > 1).limit(1).count():
        raise ValueError("F1 catalog must contain exactly one row per track_id")

    # Fail closed on missing mandatory event fields: Spark JSON schemas are nullable at read time.
    missing_values = None
    for field in event_schema().fieldNames():
        empty = F.col(field).isNull()
        if field != "position_ms" and field != "is_offline":
            empty = empty | (F.trim(F.col(field)) == "")
        missing_values = empty if missing_values is None else missing_values | empty
    if events.filter(missing_values).limit(1).count():
        raise ValueError("Bronze contains null or empty mandatory F2 fields")

    # Retries can differ in server_ts; keep the earliest received event.
    event_window = Window.partitionBy("event_id").orderBy(
        F.col("server_ts").asc(), F.col("session_id").asc()
    )
    unique = (
        events.withColumn("_rank", F.row_number().over(event_window))
        .filter(F.col("_rank") == 1)
        .drop("_rank")
    )
    plays = unique.groupBy("session_id").applyInPandas(_session_rows, play_schema())

    known = catalog.select("track_id").distinct().withColumn("_known", F.lit(True))
    checked = (
        plays.join(known, "track_id", "left")
        .withColumn(
            "motivo_cuarentena",
            F.when(F.col("motivo_cuarentena").isNotNull(), F.col("motivo_cuarentena")).when(
                F.col("_known").isNull(), F.lit("track_desconocido")
            ),
        )
        .drop("_known")
    )

    quarantine = checked.filter(F.col("motivo_cuarentena").isNotNull())
    good = checked.filter(F.col("motivo_cuarentena").isNull()).drop("motivo_cuarentena")
    cfg = ReglasValidezConfig()
    good = good.withColumn(
        "valida_rn01", F.col("ms_continuos_max") >= cfg.segundos_min_validez * 1000
    )
    # RN-02 ranks ONLY RN-01-valid plays, with deterministic tie-breaking.
    order = Window.partitionBy("user_id", "track_id", F.substring("inicio_utc", 1, 10)).orderBy(
        "inicio_utc", "play_id"
    )
    valid = good.filter("valida_rn01").withColumn("_rn", F.row_number().over(order))
    invalid = good.filter("NOT valida_rn01").withColumn("_rn", F.lit(None).cast("int"))
    result = (
        valid.unionByName(invalid)
        .withColumn(
            "pagable",
            F.when(~F.col("valida_rn01"), F.lit(False)).otherwise(
                F.col("_rn") <= cfg.max_reproducciones_dia
            ),
        )
        .withColumn(
            "motivo_validez",
            F.when(~F.col("valida_rn01"), "duracion_insuficiente")
            .when(~F.col("pagable"), "tope_diario")
            .otherwise("pagable"),
        )
        .drop("_rn")
    )
    # Partition by the corrected UTC playback date, not the settlement period.
    result = result.withColumn("year", F.substring("inicio_utc", 1, 4)).withColumn(
        "month", F.substring("inicio_utc", 6, 2)
    )
    # Lineage is provided by the caller, not inferred from the Spark executor clock.
    # Keep it on both accepted and quarantined records.
    if any(value is not None for value in (run_id, source_version, ingested_at_utc)):
        if not all(value is not None for value in (run_id, source_version, ingested_at_utc)):
            raise ValueError("run_id, source_version and ingested_at_utc must be provided together")
        if not run_id or not source_version:
            raise ValueError("run_id and source_version must be non-empty")
        from datetime import UTC, datetime

        timestamp = datetime.fromisoformat(ingested_at_utc.replace("Z", "+00:00"))
        if timestamp.tzinfo is None or timestamp.utcoffset() is None:
            raise ValueError("ingested_at_utc must include a timezone")
        ingestion_utc = timestamp.astimezone(UTC).isoformat().replace("+00:00", "Z")
        for column, value in (
            ("run_id", run_id),
            ("source_version", source_version),
            ("ingested_at_utc", ingestion_utc),
        ):
            result = result.withColumn(column, F.lit(value))
            quarantine = quarantine.withColumn(column, F.lit(value))
    return result, quarantine


def run(
    spark,
    bronze_path,
    catalog,
    silver_path,
    quarantine_path,
    *,
    run_id,
    source_version,
):
    """Write a new immutable Silver run; existing paths are never overwritten.

    The caller must supply the actual source version and a unique run identifier.
    This does not implement safe late-arrival reprocessing or atomic multi-path writes.
    """
    from datetime import UTC, datetime

    events = spark.read.schema(event_schema()).json(bronze_path)
    silver, quarantine = transform(
        events,
        catalog,
        run_id=run_id,
        source_version=source_version,
        ingested_at_utc=datetime.now(UTC).isoformat(),
    )
    silver.write.mode("errorifexists").partitionBy("year", "month", "country").parquet(silver_path)
    quarantine.write.mode("errorifexists").parquet(quarantine_path)


def bronze_window(fecha):
    """Return required server-arrival dates for a monthly Bronze rebuild.

    Bronze EG-33 is partitioned by UTC server_ts, not corrected playback time.
    Include the previous month during the RN-04 grace period (days 1-3).
    This bounded window is NOT sufficient for arbitrary late offline arrivals.
    """
    from datetime import date, timedelta

    if not isinstance(fecha, date):
        raise TypeError("fecha must be a date")
    first = fecha.replace(day=1)
    if fecha.day <= 3:
        first = (first - timedelta(days=1)).replace(day=1)
    return [first + timedelta(days=offset) for offset in range((fecha - first).days + 1)]


def bronze_partition_paths(bronze_root, fecha):
    """Match EG-33's f2/fecha=YYYY-MM-DD/lote-*.jsonl convention."""
    root = bronze_root.rstrip("/")
    return [f"{root}/fecha={day.isoformat()}" for day in bronze_window(fecha)]


def read_bronze_window(spark, bronze_root, fecha):
    """Read existing EG-33 arrival partitions; require the requested day.

    Missing historical dates are allowed (no events), but the closed target
    date must exist. This is only a reader, not a safe monthly publisher.
    """
    from pyspark.sql import functions as F

    paths = bronze_partition_paths(bronze_root, fecha)
    hadoop = spark._jvm.org.apache.hadoop
    configuration = spark._jsc.hadoopConfiguration()
    existing = []
    for path in paths:
        uri = hadoop.fs.Path(path)
        filesystem = uri.getFileSystem(configuration)
        if filesystem.exists(uri):
            existing.append(path)
        elif path == paths[-1]:
            raise FileNotFoundError(f"Missing Bronze partition for processing date: {path}")
    if not existing:
        raise FileNotFoundError(f"No Bronze partitions found for {fecha.isoformat()}")
    # Read all files in the directories; Spark JSON supports EG-33 JSONL.
    events = spark.read.schema(event_schema()).json(existing)
    if events.filter(F.col("server_ts").isNull()).limit(1).count():
        raise ValueError("Bronze contains malformed or missing server_ts")
    return events



def read_bronze_history(spark, bronze_root, fecha):
    """Read ALL available arrival partitions through the closed UTC day.

    Offline events can arrive arbitrarily late. A month-to-date arrival slice
    cannot establish complete sessions or a correct historical RN-02 ranking.
    This deliberately expensive reference reader is safe for correctness tests,
    but does not implement snapshot publication or upstream completeness proofs.
    """
    from datetime import date

    from pyspark.sql import functions as F

    if not isinstance(fecha, date):
        raise TypeError("fecha must be a date")
    root = bronze_root.rstrip("/")
    hadoop = spark._jvm.org.apache.hadoop
    configuration = spark._jsc.hadoopConfiguration()
    uri = hadoop.fs.Path(root)
    filesystem = uri.getFileSystem(configuration)
    if not filesystem.exists(uri):
        raise FileNotFoundError(f"Missing Bronze F2 root: {root}")

    paths = []
    target_found = False
    for status in filesystem.listStatus(uri):
        if not status.isDirectory():
            continue
        name = status.getPath().getName()
        if not name.startswith("fecha="):
            continue
        label = name[len("fecha=") :]
        try:
            day = date.fromisoformat(label)
            if day.isoformat() != label:
                raise ValueError("Noncanonical partition date")
        except ValueError as exc:
            raise ValueError(f"Invalid Bronze arrival partition: {name}") from exc
        if day <= fecha:
            paths.append((day, status.getPath().toString()))
            target_found |= day == fecha
    if not target_found:
        raise FileNotFoundError(f"Missing Bronze partition for processing date: {fecha}")
    paths.sort()
    events = spark.read.schema(event_schema()).json([path for _, path in paths])
    if events.filter(F.col("server_ts").isNull()).limit(1).count():
        raise ValueError("Bronze contains malformed or missing server_ts")
    return events


def snapshot_paths(silver_root, quarantine_root, run_id):
    """Allocate immutable per-run outputs without pretending S3 writes are atomic."""
    import re

    if not isinstance(run_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", run_id):
        raise ValueError("run_id must be a safe nonempty path component")
    roots = (silver_root, quarantine_root)
    if any(not isinstance(root, str) or not root.strip() for root in roots):
        raise ValueError("Silver and quarantine roots must be nonempty")
    if silver_root.rstrip("/") == quarantine_root.rstrip("/"):
        raise ValueError("Silver and quarantine roots must be different")
    return tuple(f"{root.rstrip('/')}/runs/{run_id}" for root in roots)

def affected_playback_months(silver, quarantine):
    """Identify corrected UTC playback months touched by a Bronze batch.

    This is a planning primitive for safe full-month replay. It does not
    publish or replace partitions. Include quarantined sessions when their
    corrected playback timestamp is available, so later catalog corrections
    cannot be silently omitted from the replay plan.
    """
    from pyspark.sql import functions as F

    required = {"inicio_utc"}
    for name, frame in (("silver", silver), ("quarantine", quarantine)):
        missing = required.difference(frame.columns)
        if missing:
            raise ValueError(f"{name} is missing required columns: {sorted(missing)}")

    dates = silver.select("inicio_utc").unionByName(quarantine.select("inicio_utc"))
    months = (
        dates.filter(F.col("inicio_utc").isNotNull())
        .select(F.substring("inicio_utc", 1, 7).alias("playback_month"))
        .distinct()
        .orderBy("playback_month")
    )
    return [row.playback_month for row in months.collect()]


def validate_replay_coverage(affected_months, replayed_months):
    """Fail closed if a late playback month was not fully rebuilt.

    Affected months come from corrected playback dates, not Bronze arrival
    partitions or the settlement month. The caller must supply evidence that
    each affected month was rebuilt from its complete event history.
    """
    import re

    affected = set(affected_months)
    replayed = set(replayed_months)
    for month in affected | replayed:
        if not isinstance(month, str) or not re.fullmatch(r"\d{4}-(0[1-9]|1[0-2])", month):
            raise ValueError(f"Invalid playback month: {month!r}")
    missing = affected - replayed
    if missing:
        raise ValueError(f"Missing complete replay for playback months: {sorted(missing)}")
    return True


def main(argv=None):
    """Validated CLI entry point; refuse unsafe daily publication until implemented."""
    import argparse
    import os
    from datetime import date

    parser = argparse.ArgumentParser(description="EG-35 Silver processing")
    parser.add_argument("--fecha", required=True, help="Closed UTC day (YYYY-MM-DD)")
    parser.add_argument("--bronze", default=os.getenv("SONORAPLAY_BRONZE_PATH"))
    parser.add_argument("--catalogo", default=os.getenv("SONORAPLAY_CATALOG_PATH"))
    parser.add_argument("--silver", default=os.getenv("SONORAPLAY_SILVER_PATH"))
    parser.add_argument("--cuarentena", default=os.getenv("SONORAPLAY_QUARANTINE_PATH"))
    parser.add_argument("--run-id", default=os.getenv("SONORAPLAY_RUN_ID"))
    parser.add_argument("--source-version", default=os.getenv("SONORAPLAY_SOURCE_VERSION"))
    args = parser.parse_args(argv)

    try:
        parsed = date.fromisoformat(args.fecha)
        if parsed.isoformat() != args.fecha:
            raise ValueError("date must be canonical")
    except ValueError:
        parser.error("--fecha must be a valid UTC date in YYYY-MM-DD format")
    for name in ("bronze", "catalogo", "silver", "cuarentena", "run_id", "source_version"):
        if not getattr(args, name):
            parser.error(f"--{name.replace('_', '-')} or its environment variable is required")

    # A daily job must not call run(): it uses errorifexists and has no safe
    # full-month replay / atomic publication protocol. Fail rather than lose data.
    parser.error(
        "daily Silver publication is not enabled: safe month-to-date replay, "
        "late-event detection and atomic publication are not implemented"
    )


if __name__ == "__main__":
    main()
