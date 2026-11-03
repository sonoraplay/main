"""Corre el job Silver y una agregación de liquidación con variantes y mide cada una.

Cada variante cambia **una sola** cosa respecto de la línea base (criterio 2 de la EG-39).
La etapa de liquidación es un *proxy*: une las reproducciones pagables con el catálogo para
agrupar por titular y país, que es donde el sesgo de los artistas populares duele. Cuando exista
el job real de liquidación (EG-37) se sustituye ``liquidar_proxy``.
"""

from __future__ import annotations

import platform
import statistics
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

SALES = 16  # cubetas de sal para los artistas populares


@dataclass(frozen=True)
class Variante:
    nombre: str
    descripcion: str
    conf: dict[str, str] = field(default_factory=dict)
    poda: bool = False  # filtra por la columna de partición `fecha` (poda) o por una expresión
    cache: bool = False  # reutiliza Silver en memoria para las etapas siguientes
    sal: bool = False  # sal en la unión con el catálogo (liquidación)
    difundir: bool = False  # difunde el catálogo en la unión (liquidación)


BASE_CONF = {
    "spark.sql.adaptive.enabled": "false",
    "spark.sql.autoBroadcastJoinThreshold": "-1",
    "spark.sql.shuffle.partitions": "200",
}

VARIANTES: dict[str, Variante] = {
    v.nombre: v
    for v in (
        Variante("base", "Línea base: sin AQE, sin difusión, 200 particiones, sin poda"),
        Variante("poda", "Filtra por la partición `fecha` (poda de particiones)", poda=True),
        Variante(
            "particiones",
            "shuffle.partitions ajustado a los núcleos (8)",
            {"spark.sql.shuffle.partitions": "8"},
        ),
        Variante(
            "aqe",
            "Adaptive Query Execution (une particiones pequeñas y trata el sesgo)",
            {"spark.sql.adaptive.enabled": "true"},
        ),
        Variante(
            "difusion",
            "Catálogo difundido (broadcast) en las uniones",
            {"spark.sql.autoBroadcastJoinThreshold": str(64 * 1024 * 1024)},
            difundir=True,
        ),
        Variante("sal", "Sal en la clave de pista para la unión de liquidación", sal=True),
        Variante("cache", "Silver en memoria para las etapas posteriores", cache=True),
    )
}


def sesion(
    variante: Variante,
    memoria: str = "6g",
    nucleos: int = 2,
    evento_log: str | None = None,
    base_conf: dict | None = None,
):
    from pyspark.sql import SparkSession

    b = (
        SparkSession.builder.master(f"local[{nucleos}]")
        .appName(f"eg39-{variante.nombre}")
        .config("spark.driver.memory", memoria)
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.ui.showConsoleProgress", "false")
    )
    if evento_log:
        b = b.config("spark.eventLog.enabled", "true").config("spark.eventLog.dir", evento_log)
    for k, v in {**BASE_CONF, **(base_conf or {}), **variante.conf}.items():
        b = b.config(k, v)
    return b.getOrCreate()


def leer_bronze(spark, ruta: str, variante: Variante, hasta: str | None):
    from pyspark.sql import functions as F

    from sonoraplay.spark.silver import event_schema

    esquema = event_schema().add("fecha", "string")
    df = spark.read.schema(esquema).json(ruta)
    if hasta is None:
        return df
    if variante.poda:
        return df.filter(F.col("fecha") <= hasta)
    # Mismo filtro, pero sobre una expresión: Spark no puede podar particiones con esto.
    return df.filter(F.substring("server_ts", 1, 10) <= hasta)


def liquidar_proxy(silver, catalogo, variante: Variante):
    """Pagables por titular y país: unión con el catálogo + agregación. Devuelve un DataFrame."""
    from pyspark.sql import functions as F

    pagables = silver.filter("pagable").select("track_id", "country")
    cat = catalogo.select("track_id", "titular_id")
    if variante.sal:
        cat_sal = cat.crossJoin(_sales(cat.sparkSession))
        pag = pagables.withColumn("sal", F.floor(F.rand(7) * SALES).cast("int"))
        unido = pag.join(cat_sal, ["track_id", "sal"])
    else:
        unido = pagables.join(F.broadcast(cat) if variante.difundir else cat, "track_id")
    return unido.groupBy("titular_id", "country").agg(F.count("*").alias("pagables"))


def _sales(spark):
    return spark.range(SALES).withColumnRenamed("id", "sal").selectExpr("cast(sal as int) as sal")


def huella(df, columnas: list[str]) -> dict:
    """Resumen independiente del orden: nº de filas y suma de un hash por fila.

    El hash se acota con ``pmod`` para que la suma no desborde en modo ANSI (Spark 4).
    """
    from pyspark.sql import functions as F

    fila = df.agg(
        F.count("*").alias("filas"),
        F.sum(F.pmod(F.xxhash64(*columnas), F.lit(1_000_000_007))).alias("hash"),
    ).first()
    return {"filas": fila["filas"], "hash": int(fila["hash"] or 0)}


def correr(
    variante: Variante,
    entrada: str,
    catalogo_ruta: str,
    salida: str,
    *,
    hasta: str | None = None,
    repeticiones: int = 3,
    memoria: str = "6g",
    nucleos: int = 2,
    evento_log: str | None = None,
    base_conf: dict | None = None,
    reloj: Callable[[], float] = time.perf_counter,
) -> dict:
    from sonoraplay.spark.silver import transform

    spark = sesion(variante, memoria, nucleos, evento_log, base_conf)
    try:
        cat = spark.read.parquet(catalogo_ruta)
        tiempos: dict[str, list[float]] = {"silver": [], "liquidacion": []}
        h_silver = h_liq = None
        for i in range(repeticiones):
            destino = f"{salida}/{variante.nombre}/silver_{i}"
            t0 = reloj()
            eventos = leer_bronze(spark, entrada, variante, hasta)
            silver, cuarentena = transform(eventos, cat)
            if variante.cache:
                silver = silver.cache()
            silver.write.mode("overwrite").partitionBy("year", "month", "country").parquet(destino)
            cuarentena.write.mode("overwrite").parquet(f"{destino}_cuarentena")
            tiempos["silver"].append(reloj() - t0)

            t1 = reloj()
            liq = liquidar_proxy(silver, cat, variante)
            h_liq = huella(liq, ["titular_id", "country", "pagables"])
            tiempos["liquidacion"].append(reloj() - t1)
            h_silver = huella(silver, ["play_id", "country", "pagable", "motivo_validez"])
            silver.unpersist()
        return {
            "variante": variante.nombre,
            "descripcion": variante.descripcion,
            "segundos": {k: [round(x, 3) for x in v] for k, v in tiempos.items()},
            "mediana": {k: round(statistics.median(v), 3) for k, v in tiempos.items()},
            "huella_silver": h_silver,
            "huella_liquidacion": h_liq,
            "spark_ui": spark.sparkContext.uiWebUrl,
        }
    finally:
        spark.stop()


def entorno(nucleos: int, memoria: str) -> dict:
    import pyspark

    return {
        "pyspark": pyspark.__version__,
        "python": platform.python_version(),
        "so": platform.platform(),
        "nucleos_spark": nucleos,
        "memoria_driver": memoria,
        "nota": "local[N] aproxima, no reproduce, una tarea de Fargate del mismo tamaño",
    }


def verificar_identico(resultados: list[dict]) -> list[str]:
    """Criterio 4: toda variante debe dar el mismo Silver y la misma liquidación que la base."""
    base = next(r for r in resultados if r["variante"] == "base")
    problemas = []
    for r in resultados:
        for clave in ("huella_silver", "huella_liquidacion"):
            if r[clave] != base[clave]:
                problemas.append(f"{r['variante']}: {clave} distinta de la base")
    return problemas


def informe(
    resultados: list[dict],
    meta: dict,
    precio_vcpu_h: float | None = None,
    precio_gb_h: float | None = None,
    vcpu: int = 2,
    gb: int = 8,
    objetivo_s: float = 3600.0,
) -> str:
    """Tabla antes/después en Markdown. Los precios son datos de entrada, no se inventan."""
    base = next(r for r in resultados if r["variante"] == "base")
    total_base = base["mediana"]["silver"] + base["mediana"]["liquidacion"]
    filas = [
        "| Variante | Silver (s) | Liquidación (s) | Total (s) | vs base | Resultado idéntico |",
        "|---|---:|---:|---:|---:|:--:|",
    ]
    for r in resultados:
        total = r["mediana"]["silver"] + r["mediana"]["liquidacion"]
        igual = (
            r["huella_silver"] == base["huella_silver"]
            and r["huella_liquidacion"] == base["huella_liquidacion"]
        )
        delta = (total / total_base - 1) * 100
        marca = "sí" if igual else "**NO**"
        m = r["mediana"]
        filas.append(
            f"| `{r['variante']}` | {m['silver']:.1f} | {m['liquidacion']:.1f} "
            f"| {total:.1f} | {delta:+.0f} % | {marca} |"
        )
    texto = ["\n".join(filas), ""]
    if precio_vcpu_h is not None and precio_gb_h is not None:
        horas = total_base / 3600
        costo = horas * (vcpu * precio_vcpu_h + gb * precio_gb_h)
        texto.append(
            f"Costo de una corrida de la línea base con {vcpu} vCPU / {gb} GB: "
            f"{costo:.4f} USD (precios de entrada: {precio_vcpu_h} USD/vCPU-h, "
            f"{precio_gb_h} USD/GB-h)."
        )
    else:
        texto.append("Costo por corrida: **pendiente** (faltan los precios de entrada).")
    texto.append(
        f"Meta RNF-01: {objetivo_s:.0f} s. "
        f"Total de la base en este volumen: {total_base:.1f} s "
        f"({'dentro' if total_base < objetivo_s else 'FUERA'} de la meta **a este volumen**; "
        "no se extrapola al volumen completo)."
    )
    texto.append(f"\nEntorno: `{meta['entorno']}`. Datos: `{meta['datos']}`.")
    return "\n".join(texto)


def guardar(ruta: Path, contenido: str) -> None:
    ruta.parent.mkdir(parents=True, exist_ok=True)
    ruta.write_text(contenido, encoding="utf-8")
