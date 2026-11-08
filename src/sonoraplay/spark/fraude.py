"""EG-36: Spark fraud signals RN-03, based on ADR-0005."""
from __future__ import annotations

from sonoraplay.config import ReglasFraudeConfig


def evaluar_fraude(silver, artistas, cfg=None):
    """Return (annotated_silver, signals). Input Silver is never modified."""
    from pyspark.sql import functions as F
    from pyspark.sql.types import BooleanType, StringType, StructField, StructType

    cfg = cfg or ReglasFraudeConfig()
    required = {"play_id", "user_id", "track_id", "device_id", "inicio_utc",
                "ms_continuos_max", "mes_reproduccion", "mes_liquidacion", "pagable"}
    missing = required - set(silver.columns)
    if missing:
        raise ValueError(f"EG-36: missing Silver columns: {sorted(missing)}")
    if not {"track_id", "artista_principal"} <= set(artistas.columns):
        raise ValueError("EG-36: F1 requires track_id and artista_principal")
    for col in required:
        if silver.filter(F.col(col).isNull()).limit(1).count():
            raise ValueError(f"EG-36: null Silver column {col}")
    if silver.groupBy("play_id").count().filter("count > 1").limit(1).count():
        raise ValueError("EG-36: duplicate play_id")
    if artistas.filter(F.col("track_id").isNull() | F.col("artista_principal").isNull()
                       | (F.trim("artista_principal") == "")).limit(1).count():
        raise ValueError("EG-36: invalid F1 artist mapping")
    if artistas.groupBy("track_id").count().filter("count > 1").limit(1).count():
        raise ValueError("EG-36: duplicate F1 track_id")

    mapped = silver.join(
        artistas.select("track_id", F.col("artista_principal").alias("_artista")),
        "track_id", "left",
    )
    if mapped.filter(F.col("_artista").isNull()).limit(1).count():
        raise ValueError("EG-36: Silver track without F1 artist")
    if mapped.filter(
        (F.substring("inicio_utc", 1, 7) != F.substring("mes_reproduccion", 1, 7))
        | (F.col("ms_continuos_max") < 0)
    ).limit(1).count():
        raise ValueError("EG-36: invalid playback month or duration")

    schema = StructType([
        StructField("user_id", StringType(), False),
        StructField("mes_reproduccion", StringType(), False),
        StructField("horas_24h", BooleanType(), False),
    ])

    def rolling(pdf):
        import pandas as pd
        from datetime import datetime
        from sonoraplay.reglas.fraude import Reproduccion, senal_horas_24h

        reps = [
            Reproduccion(
                cuenta_id=str(r["user_id"]), dispositivo_id=str(r["device_id"]),
                artista_id=str(r["_artista"]),
                inicio=datetime.fromisoformat(str(r["inicio_utc"]).replace("Z", "+00:00")),
                ms_escuchados=int(r["ms_continuos_max"]),
            )
            for _, r in pdf.iterrows()
        ]
        return pd.DataFrame([{
            "user_id": str(pdf["user_id"].iloc[0]),
            "mes_reproduccion": str(pdf["mes_reproduccion"].iloc[0]),
            "horas_24h": bool(senal_horas_24h(reps, cfg)),
        }])

    horas = mapped.groupBy("user_id", "mes_reproduccion").applyInPandas(rolling, schema)
    listeners = mapped.groupBy("mes_reproduccion", "_artista").agg(
        F.countDistinct("user_id").alias("_oyentes")
    )
    artist_counts = mapped.groupBy("mes_reproduccion", "user_id", "_artista").agg(
        F.count("*").alias("_n")
    )
    totals = mapped.groupBy("mes_reproduccion", "user_id").agg(
        F.count("*").alias("_total")
    )
    concentration = (
        artist_counts.join(listeners, ["mes_reproduccion", "_artista"])
        .join(totals, ["mes_reproduccion", "user_id"])
        .groupBy("mes_reproduccion", "user_id")
        .agg(F.max(
            (F.col("_n") > F.col("_total") * F.lit(cfg.porcentaje_max_artista))
            & (F.col("_oyentes") < F.lit(cfg.oyentes_min_artista))
        ).alias("concentracion_artista"))
    )
    shared = mapped.groupBy("mes_reproduccion", "device_id").agg(
        F.countDistinct("user_id").alias("_usuarios_dispositivo")
    )
    devices = (
        mapped.join(shared, ["mes_reproduccion", "device_id"])
        .groupBy("mes_reproduccion", "user_id")
        .agg(F.max(
            F.col("_usuarios_dispositivo") > F.lit(cfg.cuentas_max_dispositivo)
        ).alias("dispositivo_compartido"))
    )
    keys = ["mes_reproduccion", "user_id"]
    signals = (
        horas.join(concentration, keys).join(devices, keys)
        .withColumn("sospechosa",
                    F.col("horas_24h") | F.col("concentracion_artista")
                    | F.col("dispositivo_compartido"))
    )
    # Playback-month signals; hold every play of that account in its settlement month.
    flags = (
        mapped.select("user_id", "mes_reproduccion", "mes_liquidacion").distinct()
        .join(signals, keys).filter("sospechosa")
        .select("user_id", "mes_liquidacion").distinct()
        .withColumn("_en_revision", F.lit(True))
    )
    annotated = (
        silver.join(flags, ["user_id", "mes_liquidacion"], "left")
        .withColumn("estado_fraude",
                    F.when(F.col("_en_revision").isNotNull(), F.lit("en_revision"))
                    .otherwise(F.lit("valida_para_fraude")))
        .withColumn("pagable_gold",
                    F.col("pagable") & (F.col("estado_fraude") == "valida_para_fraude"))
        .drop("_en_revision")
    )
    return annotated, signals


def preparar_gold(silver_evaluado, periodo):
    """Fail closed: never allocate royalties for held or invalid plays."""
    from pyspark.sql import functions as F

    required = {"pagable", "pagable_gold", "estado_fraude", "mes_liquidacion"}
    missing = required - set(silver_evaluado.columns)
    if missing:
        raise ValueError(f"EG-36: fraud gate missing {sorted(missing)}")
    if silver_evaluado.filter(
        F.col("pagable").isNull() | F.col("pagable_gold").isNull()
        | F.col("estado_fraude").isNull()
        | ~F.col("estado_fraude").isin("en_revision", "valida_para_fraude")
        | (F.col("pagable_gold") != (
            F.col("pagable") & (F.col("estado_fraude") == "valida_para_fraude")
        ))
    ).limit(1).count():
        raise ValueError("EG-36: inconsistent fraud eligibility")
    return silver_evaluado.filter(
        F.col("pagable_gold") & (F.col("mes_liquidacion") == periodo.isoformat())
    )
