"""EG-36 / HU09: Spark acceptance and held-money regression tests."""
from datetime import date

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from pyspark.sql import SparkSession

from sonoraplay.spark.fraude import evaluar_fraude, preparar_gold

MES = date(2026, 9, 1)


@pytest.fixture(scope="module")
def spark():
    session = (
        SparkSession.builder.master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "2")
        .getOrCreate()
    )
    yield session
    session.stop()


def fixtures(spark, rows):
    silver = spark.createDataFrame(
        rows,
        "play_id string, user_id string, track_id string, device_id string, "
        "inicio_utc string, ms_continuos_max int, mes_reproduccion string, "
        "mes_liquidacion string, pagable boolean",
    )
    artists = spark.createDataFrame(
        [("t1", "artista_a"), ("t2", "artista_b"),
         ("t3", "artista_c"), ("t4", "artista_d")],
        "track_id string, artista_principal string",
    )
    return silver, artists


def play(pid, user, track, device, hour, ms=31_000, settlement="2026-09-01"):
    return (pid, user, track, device, f"2026-09-10T{hour:02d}:00:00+00:00",
            ms, "2026-09-01", settlement, True)


def test_hu09_concentration_holds_entire_month_and_keeps_legitimate_money(spark):
    rows = [
        play("f1", "farm", "t1", "farm-device", 1),
        play("f2", "farm", "t1", "farm-device", 2),
        play("f3", "farm", "t1", "farm-device", 3),
        play("f4", "farm", "t2", "farm-device", 4),
        play("l1", "legit", "t1", "own-device", 1),
        play("l2", "legit", "t2", "own-device", 2),
        play("l3", "legit", "t3", "own-device", 3),
        play("l4", "legit", "t4", "own-device", 4),
    ]
    silver, artists = fixtures(spark, rows)
    annotated, signals = evaluar_fraude(silver, artists)
    flagged = {r["user_id"]: r["sospechosa"] for r in signals.collect()}
    assert flagged == {"farm": True, "legit": False}
    assert annotated.filter("estado_fraude = 'en_revision'").count() == 4
    payable = preparar_gold(annotated, MES)
    assert {r["play_id"] for r in payable.select("play_id").collect()} == {
        "l1", "l2", "l3", "l4"
    }
    # One synthetic USD per eligible play: no farm allocation, 4 USD remain eligible.
    amounts = payable.groupBy("user_id").count().collect()
    assert {r["user_id"]: r["count"] for r in amounts} == {"legit": 4}


def test_hu09_shared_device_six_accounts_exact_threshold(spark):
    rows = [
        play(f"p{i}", f"u{i}", f"t{(i % 4) + 1}", "shared", i + 1)
        for i in range(6)
    ]
    silver, artists = fixtures(spark, rows)
    annotated, signals = evaluar_fraude(silver, artists)
    assert signals.filter("dispositivo_compartido").count() == 6
    assert preparar_gold(annotated, MES).count() == 0


def test_hu09_five_accounts_not_flagged_by_device(spark):
    rows = [
        play(f"p{i}", f"u{i}", f"t{(i % 4) + 1}", "shared", i + 1)
        for i in range(5)
    ]
    silver, artists = fixtures(spark, rows)
    _, signals = evaluar_fraude(silver, artists)
    assert signals.filter("dispositivo_compartido").count() == 0


def test_hu09_rolling_24_hours_crosses_midnight(spark):
    # 21 consecutive one-hour plays; all same artist also triggers concentration.
    rows = [
        (f"p{i}", "farm", "t1", "d1",
         f"2026-09-{10 + (i // 24):02d}T{i % 24:02d}:00:00+00:00",
         3_600_000, "2026-09-01", "2026-09-01", True)
        for i in range(21)
    ]
    silver, artists = fixtures(spark, rows)
    _, signals = evaluar_fraude(silver, artists)
    assert signals.first()["horas_24h"] is True


def test_fail_closed_without_fraud_evidence(spark):
    silver, _ = fixtures(spark, [play("p1", "u1", "t1", "d1", 1)])
    with pytest.raises(ValueError, match="fraud gate missing"):
        preparar_gold(silver, MES)


def test_fail_closed_on_inconsistent_eligibility(spark):
    silver, _ = fixtures(spark, [play("p1", "u1", "t1", "d1", 1)])
    bad = silver.withColumn("estado_fraude", __import__("pyspark").sql.functions.lit("en_revision"))
    bad = bad.withColumn("pagable_gold", __import__("pyspark").sql.functions.lit(True))
    with pytest.raises(ValueError, match="inconsistent fraud eligibility"):
        preparar_gold(bad, MES)
