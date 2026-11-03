"""Genera un mes sintético de eventos F2 (Bronze) y su catálogo, con popularidad sesgada.

Es determinista para una semilla. Se genera con Spark para poder llegar a volúmenes que Python
puro no alcanza. Cada reproducción produce un ``start`` y un ``end``; una fracción se duplica
(reintento) y otra usa pistas fuera del catálogo (cuarentena).
"""

from __future__ import annotations

from dataclasses import dataclass

PAISES = ("CO", "MX", "AR", "BR", "CL", "PE")


@dataclass(frozen=True)
class Parametros:
    mes: str = "2026-09"
    dias: int = 30
    reproducciones: int = 100_000
    usuarios: int = 10_000
    artistas: int = 200
    pistas_por_artista: int = 50
    titulares: int = 50
    # >1 concentra las reproducciones en pocos artistas (1 = uniforme). Es el sesgo (skew).
    sesgo: float = 3.0
    tasa_duplicados: float = 0.01
    tasa_desconocidas: float = 0.005
    semilla: int = 42


def _uuid_de(F, expresion):
    """UUID determinista (formato 8-4-4-4-12) derivado de un md5."""
    h = F.md5(expresion)
    return F.concat_ws(
        "-",
        F.substring(h, 1, 8),
        F.substring(h, 9, 4),
        F.substring(h, 13, 4),
        F.substring(h, 17, 4),
        F.substring(h, 21, 12),
    )


def generar(spark, destino: str, p: Parametros | None = None) -> dict:
    """Escribe ``<destino>/bronze/fecha=AAAA-MM-DD`` (JSON) y ``<destino>/catalogo`` (Parquet)."""
    from pyspark.sql import functions as F

    p = p or Parametros()
    n_pistas = p.artistas * p.pistas_por_artista
    pistas = (
        spark.range(n_pistas)
        .select(
            F.concat(F.lit("trk"), F.lpad(F.col("id").cast("string"), 8, "0")).alias("track_id"),
            (F.col("id") / p.pistas_por_artista).cast("int").alias("artista_id"),
        )
        .withColumn("titular_id", F.col("artista_id") % p.titulares)
    )
    pistas.write.mode("overwrite").parquet(f"{destino}/catalogo")

    r = lambda k: F.rand(p.semilla + k)  # noqa: E731
    artista = F.floor(F.lit(p.artistas) * F.pow(r(1), F.lit(p.sesgo))).cast("int")
    pista = artista * p.pistas_por_artista + F.floor(r(2) * p.pistas_por_artista).cast("int")
    base = (
        spark.range(p.reproducciones)
        .withColumn("usuario", F.floor(r(0) * p.usuarios).cast("int"))
        .withColumn(
            "pista",
            F.when(
                r(3) < p.tasa_desconocidas,
                F.concat(F.lit("fuera"), F.col("id").cast("string")),
            ).otherwise(F.concat(F.lit("trk"), F.lpad(pista.cast("string"), 8, "0"))),
        )
        .withColumn("dia", 1 + F.floor(r(4) * p.dias).cast("int"))
        .withColumn("segundo", F.floor(r(5) * 86_000).cast("int"))
        .withColumn("duracion_s", 5 + F.floor(r(6) * 295).cast("int"))
        .withColumn(
            "inicio",
            F.timestamp_seconds(
                F.unix_timestamp(
                    F.to_timestamp(
                        F.concat(
                            F.lit(p.mes), F.lit("-"), F.lpad(F.col("dia").cast("string"), 2, "0")
                        )
                    )
                )
                + F.col("segundo")
            ),
        )
        .withColumn("sesion", _uuid_de(F, F.concat(F.lit("s"), F.col("id").cast("string"))))
        .withColumn(
            "usuario_uuid", _uuid_de(F, F.concat(F.lit("u"), F.col("usuario").cast("string")))
        )
        .withColumn(
            "pais", F.element_at(F.array(*[F.lit(c) for c in PAISES]), F.col("usuario") % 6 + 1)
        )
    )

    def evento(tipo: str, desplazamiento_s, posicion_ms):
        ts = F.timestamp_millis(F.unix_millis("inicio") + desplazamiento_s * 1000)
        fmt = "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'"
        return base.select(
            F.lit("1.0").alias("schema_version"),
            _uuid_de(F, F.concat(F.lit(tipo), F.col("sesion"))).alias("event_id"),
            F.lit(tipo).alias("event_type"),
            F.col("usuario_uuid").alias("user_id"),
            F.concat(F.lit("dev-"), (F.col("usuario") % 3).cast("string")).alias("device_id"),
            F.col("pista").alias("track_id"),
            F.col("sesion").alias("session_id"),
            F.date_format(ts, fmt).alias("device_ts"),
            F.date_format(F.timestamp_millis(F.unix_millis(ts) + 200), fmt).alias("server_ts"),
            posicion_ms.cast("long").alias("position_ms"),
            F.col("pais").alias("country_playback"),
            F.lit(False).alias("is_offline"),
        )

    eventos = evento("start", F.lit(0), F.lit(0)).unionByName(
        evento("end", F.col("duracion_s"), F.col("duracion_s") * 1000)
    )
    duplicados = eventos.sample(False, p.tasa_duplicados, p.semilla).withColumn(
        "server_ts",
        F.date_format(
            F.to_timestamp("server_ts") + F.expr("INTERVAL 2 SECOND"),
            "yyyy-MM-dd'T'HH:mm:ss.SSS'Z'",
        ),
    )
    todo = eventos.unionByName(duplicados).withColumn("fecha", F.substring("server_ts", 1, 10))
    (
        todo.repartition("fecha")
        .write.mode("overwrite")
        .partitionBy("fecha")
        .json(f"{destino}/bronze")
    )
    return {
        "reproducciones": p.reproducciones,
        "eventos": todo.count(),
        "pistas": n_pistas,
        "parametros": p.__dict__,
    }
