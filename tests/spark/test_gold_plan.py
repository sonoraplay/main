"""EG-37 · Plan vigente por fecha, bolsas desde F5/F6, escritura append-only y CLI."""

import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from pyspark.sql import SparkSession

from sonoraplay.reglas.liquidacion import BolsaPais, CondicionContrato, Pago, TasaCambio
from sonoraplay.spark.gold import escribir_gold, liquidar
from sonoraplay.spark.gold_fuentes import bolsas_del_periodo, suscripciones_efectivas

SEPT = date(2026, 9, 1)
TITULAR = uuid.UUID(int=1)


@pytest.fixture(scope="module")
def spark():
    s = (
        SparkSession.builder.master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    yield s
    s.stop()


def _entradas(spark, plays, suscripciones):
    silver = spark.createDataFrame(
        [
            (pid, u, "t0", "CO", f"{dia}T10:00:00+00:00", "2026-09-01", True)
            for pid, u, dia in plays
        ],
        "play_id string, user_id string, track_id string, country string, "
        "inicio_utc string, mes_liquidacion string, pagable boolean",
    )
    usuarios = spark.createDataFrame(
        [(u, "CO") for u in {p[1] for p in plays}], "user_id string, pais_facturacion string"
    )
    cat = spark.createDataFrame([("t0", str(TITULAR))], "track_id string, titular_id string")
    sus = spark.createDataFrame(
        suscripciones,
        "user_id string, componente string, desde string, hasta string, prioridad int",
    )
    conds = [CondicionContrato(uuid.uuid4(), TITULAR, "t0", Decimal(50), date(2026, 1, 1))]
    return silver, usuarios, cat, conds, sus


def _componentes(plays):
    return {r["play_id"]: r["componente"] for r in plays.collect()}


def test_el_plan_se_toma_en_la_fecha_de_cada_reproduccion(spark):
    # uA: gratis hasta el 15 (exclusivo) y luego individual. uB: miembro de la familia de uT.
    plays = [
        ("a14", "uA", "2026-09-14"),
        ("a15", "uA", "2026-09-15"),
        ("a30", "uA", "2026-09-30"),
        ("b10", "uB", "2026-09-10"),
    ]
    sus = [
        ("uA", "publicidad", "2026-01-01", "2026-09-15", 0),
        ("uA", "suscripcion", "2026-09-15", None, 0),
        ("uB", "suscripcion", "2026-01-01", None, 1),  # la del titular de su familia
    ]
    silver, usr, cat, conds, s = _entradas(spark, plays, sus)
    bolsa = [BolsaPais("CO", Decimal(1000), Decimal(1000))]
    _, salida = liquidar(
                    spark,
                    silver,
                    usr,
                    cat,
                    conds,
                    bolsa,
                    SEPT,
                    "r1",
                    suscripciones=s,
                    fraude_verificado=False,
                )
    assert _componentes(salida) == {
        "a14": "publicidad",
        "a15": "suscripcion",
        "a30": "suscripcion",
        "b10": "suscripcion",
    }


def test_la_suscripcion_propia_gana_a_la_del_titular(spark):
    sus = [
        ("uA", "publicidad", "2026-01-01", None, 0),
        ("uA", "suscripcion", "2026-01-01", None, 1),
    ]
    silver, usr, cat, conds, s = _entradas(spark, [("p", "uA", "2026-09-05")], sus)
    _, salida = liquidar(
        spark, silver, usr, cat, conds, [BolsaPais("CO", Decimal(10), Decimal(10))], SEPT, "r", s
    , fraude_verificado=False)
    assert _componentes(salida) == {"p": "publicidad"}


def test_sin_plan_vigente_en_la_fecha_la_corrida_falla(spark):
    sus = [("uA", "suscripcion", "2026-09-10", None, 0)]
    silver, usr, cat, conds, s = _entradas(spark, [("p", "uA", "2026-09-05")], sus)
    with pytest.raises(ValueError, match="plan vigente"):
        liquidar(
            spark,
            silver,
            usr,
            cat,
            conds,
            [BolsaPais("CO", Decimal(10), Decimal(10))],
            SEPT,
            "r",
            s,
         fraude_verificado=False)


def test_gold_nunca_borra_otras_liquidaciones_y_repetir_es_idempotente(spark, tmp_path):
    sus = [("uA", "suscripcion", "2026-01-01", None, 0)]
    silver, usr, cat, conds, s = _entradas(spark, [("p", "uA", "2026-09-05")], sus)
    bolsa = [BolsaPais("CO", Decimal(10), Decimal(10))]
    destino = str(tmp_path / "gold")
    r1, p1 = liquidar(
                 spark,
                 silver,
                 usr,
                 cat,
                 conds,
                 bolsa,
                 SEPT,
                 "run-1",
                 suscripciones=s,
                 fraude_verificado=False,
             )
    r2, p2 = liquidar(
                 spark,
                 silver,
                 usr,
                 cat,
                 conds,
                 bolsa,
                 SEPT,
                 "run-2",
                 suscripciones=s,
                 fraude_verificado=False,
             )
    escribir_gold(r1, p1, destino)
    escribir_gold(r2, p2, destino)
    escribir_gold(r1, p1, destino)  # repetir run-1
    leidas = spark.read.parquet(f"{destino}/plays_liquidados")
    por_liquidacion = {
        r["liquidacion_id"]: r["n"]
        for r in leidas.groupBy("liquidacion_id").count().withColumnRenamed("count", "n").collect()
    }
    assert set(por_liquidacion) == {str(r1.liquidacion_id), str(r2.liquidacion_id)}
    assert set(por_liquidacion.values()) == {1}


def test_suscripciones_efectivas_incluye_las_del_titular_con_prioridad_1():
    filas = suscripciones_efectivas(
        {"t": [("individual", date(2026, 1, 1), None)], "m": [("free", date(2026, 1, 1), None)]},
        {"m": "t"},
        ["t", "m"],
    )
    assert ("t", "suscripcion", date(2026, 1, 1), None, 0) in filas
    assert ("m", "publicidad", date(2026, 1, 1), None, 0) in filas
    assert ("m", "suscripcion", date(2026, 1, 1), None, 1) in filas


def test_bolsas_convierten_f5_con_el_cierre_f6_y_exigen_los_datos():
    pagos = [Pago("u1", Decimal("10.00"), "aprobado"), Pago("u1", Decimal("99"), "rechazado")]
    tasa = {"COP": TasaCambio("COP", date(2026, 9, 30), Decimal("4000"))}
    (b,) = bolsas_del_periodo(SEPT, pagos, {"u1": "CO"}, {"CO": ("COP", Decimal("8000"))}, tasa)
    assert b.pais == "CO"
    assert b.suscripcion == Decimal("10.00") * Decimal("0.52")
    assert b.publicidad == Decimal("2") * Decimal("0.45")
    with pytest.raises(ValueError, match="F5"):
        bolsas_del_periodo(SEPT, pagos, {"u1": "CO"}, {}, tasa)
    with pytest.raises(ValueError, match="F6"):
        bolsas_del_periodo(SEPT, pagos, {"u1": "CO"}, {"CO": ("COP", Decimal("1"))}, {})


@pytest.mark.parametrize("periodo", ["2026-13", "2026-9", "septiembre"])
def test_cli_rechaza_un_periodo_invalido(periodo):
    from sonoraplay.spark.gold import main

    with pytest.raises(SystemExit) as exc:
        main(["--periodo", periodo])
    assert exc.value.code != 0


def test_url_de_la_base_desde_las_variables_db_de_ecs():
    from sonoraplay.spark.gold import url_desde_entorno

    env = {
        "DB_HOST": "rds.internal",
        "DB_PORT": "5432",
        "DB_NAME": "sonoraplay",
        "DB_USER": "sonora",
        "DB_PASSWORD": "p@ss/w:rd",
    }
    assert url_desde_entorno(env) == (
        "postgresql://sonora:p%40ss%2Fw%3Ard@rds.internal:5432/sonoraplay?sslmode=require"
    )
    assert url_desde_entorno({**env, "DATABASE_URL": "postgresql://x"}) == "postgresql://x"
    assert url_desde_entorno({}) is None


def test_el_catalogo_f1_tambien_se_lee_de_s3(tmp_path):
    import pandas as pd

    from sonoraplay.spark.gold_fuentes import leer_catalogo_f1

    parquet = tmp_path / "origen.parquet"
    pd.DataFrame({"track_id": ["t0", "t1"], "titular_id": ["a", "b"]}).to_parquet(parquet)

    class S3Falso:
        llamadas = []

        def download_file(self, bucket, clave, destino):
            self.llamadas.append((bucket, clave))
            Path(destino).write_bytes(parquet.read_bytes())

    s3 = S3Falso()
    assert leer_catalogo_f1("s3://bucket-bronze/catalogo", s3) == [("t0", "a"), ("t1", "b")]
    assert leer_catalogo_f1("s3://bucket-bronze/catalogo/catalogo_f1.parquet", s3)
    assert s3.llamadas == [
        ("bucket-bronze", "catalogo/catalogo_f1.parquet"),
        ("bucket-bronze", "catalogo/catalogo_f1.parquet"),
    ]


def _gold_y_silver(spark):
    sus = [("uA", "suscripcion", "2026-01-01", None, 0)]
    silver, usr, cat, conds, s = _entradas(
        spark, [("p1", "uA", "2026-09-05"), ("p2", "uA", "2026-09-06")], sus
    )
    bolsa = [BolsaPais("CO", Decimal(10), Decimal(10))]
    _, plays = liquidar(
                   spark,
                   silver,
                   usr,
                   cat,
                   conds,
                   bolsa,
                   SEPT,
                   "r",
                   suscripciones=s,
                   fraude_verificado=False,
               )
    return silver, plays


def test_la_conciliacion_por_play_id_cuadra_cuando_gold_liquida_todo_lo_pagable(spark):
    from sonoraplay.spark.gold import conciliar

    silver, plays = _gold_y_silver(spark)
    assert conciliar(silver, plays, SEPT) == {"silver_pagables": 2, "gold_liquidadas": 2}


def test_la_conciliacion_falla_si_gold_dejo_sin_liquidar_una_reproduccion(spark):
    from pyspark.sql import functions as F

    from sonoraplay.spark.gold import conciliar

    silver, plays = _gold_y_silver(spark)
    with pytest.raises(ValueError, match="sin liquidar"):
        conciliar(silver, plays.filter(F.col("play_id") != "p2"), SEPT)


def test_la_conciliacion_falla_si_gold_liquida_algo_que_no_es_pagable(spark):
    from pyspark.sql import functions as F

    from sonoraplay.spark.gold import conciliar

    silver, plays = _gold_y_silver(spark)
    extra = plays.limit(1).withColumn("play_id", F.lit("fantasma"))
    with pytest.raises(ValueError, match="liquidadas sin ser pagables"):
        conciliar(silver, plays.unionByName(extra), SEPT)


def test_la_conciliacion_falla_si_hay_play_id_repetidos_en_gold(spark):
    from sonoraplay.spark.gold import conciliar

    silver, plays = _gold_y_silver(spark)
    with pytest.raises(ValueError, match="repetidos"):
        conciliar(silver, plays.unionByName(plays.limit(1)), SEPT)
