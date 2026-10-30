"""EG-35: Spark Silver using the existing F2 business-rule implementations.

Bronze JSON -> deterministic event deduplication -> session reconstruction ->
catalog quarantine -> RN-01/RN-02/RN-04 -> partitioned Silver Parquet.
"""
from __future__ import annotations

from datetime import UTC, datetime

from sonoraplay.config import AtribucionOfflineConfig, ReglasValidezConfig
from sonoraplay.reglas.atribucion import atribuir_reproduccion
from sonoraplay.reglas.sesiones import reconstruir

# Import Spark only when the Silver job is invoked; existing services need no Spark.
def event_schema():
    from pyspark.sql.types import (
        BooleanType, LongType, StringType, StructField, StructType,
    )

    return StructType([
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
    ])


def play_schema():
    from pyspark.sql.types import (
        BooleanType, IntegerType, StringType, StructField, StructType,
    )

    return StructType([
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
    ])


def _session_rows(pdf):
    """One grouped session; delegate clocks and segment logic to existing pure rules."""
    import pandas as pd

    records = pdf.to_dict("records")
    first = records[0]
    if len({(e["user_id"], e["device_id"], e["track_id"]) for e in records}) != 1:
        reason = "identidad_sesion_inconsistente"
    else:
        reason = None

    if reason is None:
        reps = reconstruir(records)
        if not reps:
            reason = "sesion_sin_inicio"
    if reason:
        return pd.DataFrame([{
            "play_id": first["session_id"], "user_id": first["user_id"],
            "track_id": first["track_id"], "country": first["country_playback"],
            "device_id": first["device_id"], "inicio_utc": None,
            "sincronizado_utc": None, "ms_continuos_max": None,
            "is_offline": first["is_offline"], "mes_reproduccion": None,
            "mes_liquidacion": None, "tipo_atribucion": None,
            "motivo_cuarentena": reason, "schema_version": first["schema_version"],
        }])
    rep = reps[0]
    attribution = atribuir_reproduccion(
        rep.inicio, rep.sincronizado, rep.is_offline, AtribucionOfflineConfig()
    )
    return pd.DataFrame([{
        "play_id": rep.reproduccion_id, "user_id": rep.cuenta_id,
        "track_id": rep.track_id, "country": first["country_playback"],
        "device_id": first["device_id"], "inicio_utc": rep.inicio.isoformat(),
        "sincronizado_utc": rep.sincronizado.isoformat(),
        "ms_continuos_max": rep.ms_continuos_max, "is_offline": rep.is_offline,
        "mes_reproduccion": attribution.mes_reproduccion.isoformat(),
        "mes_liquidacion": attribution.mes_liquidacion.isoformat(),
        "tipo_atribucion": str(attribution.tipo),
        "motivo_cuarentena": None, "schema_version": first["schema_version"],
    }])


def transform(events, catalog):
    """Return (silver, quarantine), without performing external writes.

    catalog must contain a unique track_id column from F1. All sessions in the
    processing/reprocessing window must be present for a correct RN-02 count.
    """
    from pyspark.sql import Window, functions as F

    if catalog.select("track_id").distinct().count() != catalog.count():
        raise ValueError("F1 catalog must contain exactly one row per track_id")

    # Retries can differ in server_ts; keep the earliest received event.
    event_window = Window.partitionBy("event_id").orderBy(
        F.col("server_ts").asc(), F.col("session_id").asc()
    )
    unique = (events.withColumn("_rank", F.row_number().over(event_window))
              .filter(F.col("_rank") == 1).drop("_rank"))
    plays = unique.groupBy("session_id").applyInPandas(_session_rows, play_schema())

    known = catalog.select("track_id").distinct().withColumn("_known", F.lit(True))
    checked = plays.join(known, "track_id", "left").withColumn(
        "motivo_cuarentena",
        F.when(F.col("motivo_cuarentena").isNotNull(), F.col("motivo_cuarentena"))
        .when(F.col("_known").isNull(), F.lit("track_desconocido"))
    ).drop("_known")

    quarantine = checked.filter(F.col("motivo_cuarentena").isNotNull())
    good = checked.filter(F.col("motivo_cuarentena").isNull()).drop("motivo_cuarentena")
    cfg = ReglasValidezConfig()
    good = good.withColumn(
        "valida_rn01", F.col("ms_continuos_max") >= cfg.segundos_min_validez * 1000
    )
    # RN-02 ranks ONLY RN-01-valid plays, with deterministic tie-breaking.
    order = Window.partitionBy(
        "user_id", "track_id", F.substring("inicio_utc", 1, 10)
    ).orderBy("inicio_utc", "play_id")
    valid = good.filter("valida_rn01").withColumn("_rn", F.row_number().over(order))
    invalid = good.filter("NOT valida_rn01").withColumn("_rn", F.lit(None).cast("int"))
    result = valid.unionByName(invalid).withColumn(
        "pagable", F.col("valida_rn01") & (F.col("_rn") <= cfg.max_reproducciones_dia)
    ).withColumn(
        "motivo_validez",
        F.when(~F.col("valida_rn01"), "duracion_insuficiente")
        .when(~F.col("pagable"), "tope_diario").otherwise("pagable")
    ).drop("_rn")
    # Partition by the corrected UTC playback date, not the settlement period.
    result = (result.withColumn("year", F.substring("inicio_utc", 1, 4))
              .withColumn("month", F.substring("inicio_utc", 6, 2)))
    return result, quarantine


def run(spark, bronze_path, catalog, silver_path, quarantine_path):
    """Read F2 Bronze and write partitioned Parquet; never overwrite published Gold."""
    events = spark.read.schema(event_schema()).json(bronze_path)
    silver, quarantine = transform(events, catalog)
    silver.write.mode("overwrite").partitionBy("year", "month", "country").parquet(
        silver_path
    )
    quarantine.write.mode("overwrite").parquet(quarantine_path)
