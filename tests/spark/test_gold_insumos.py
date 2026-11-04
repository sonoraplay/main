"""EG-37 · Insumos de Gold desde RDS (F3, F4, F5, F6) y orquestación ``ejecutar``."""

import os
import uuid
from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

psycopg = pytest.importorskip("psycopg")

from sonoraplay.spark import insumos  # noqa: E402

SEPT = date(2026, 9, 1)
DDL = sorted(Path(__file__).resolve().parents[2].glob("db/ddl/00[1-4]_*.sql"))

U = {n: uuid.UUID(int=i + 1) for i, n in enumerate("ABCDEF")}
TIT = uuid.UUID(int=900)
GRUPO = uuid.UUID(int=700)


def _sus(n):
    return uuid.UUID(int=5000 + n)


@pytest.fixture
def pg():
    url = os.environ.get("EG30_DATABASE_URL")
    if not url:
        pytest.skip("requiere EG30_DATABASE_URL (PostgreSQL)")
    esquema = f"t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1)) as c:
        c.execute(f"CREATE SCHEMA {esquema}")
        c.execute(f"SET search_path TO {esquema}")
        for f in DDL:
            c.execute(f.read_text(encoding="utf-8"))
        _sembrar(c)
        c.commit()
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA {esquema} CASCADE")
        c.commit()


def _sembrar(c):
    for pid, codigo, precio, maxm in (
        (1, "free", 0, 1),
        (2, "individual", 10, 1),
        (3, "familiar", 20, 6),
        (4, "estudiante", 5, 1),
    ):
        c.execute(
            "INSERT INTO planes VALUES (%s, %s, %s, %s, %s)", (pid, codigo, codigo, precio, maxm)
        )
    paises = {"A": "CO", "B": "CO", "C": "MX", "D": "BR", "E": None, "F": "CO"}
    for n, u in U.items():
        c.execute(
            "INSERT INTO usuarios VALUES (%s, %s, %s, %s, '2026-01-01', NULL)",
            (u, n, f"{n}@x.co", paises[n]),
        )
    c.execute("INSERT INTO grupos_familiares VALUES (%s, %s, '2026-01-01')", (GRUPO, U["C"]))
    c.execute("INSERT INTO miembros_familia VALUES (%s, %s, 'titular', '2026-01-01')", (GRUPO, U["C"]))
    c.execute("INSERT INTO miembros_familia VALUES (%s, %s, 'miembro', '2026-02-01')", (GRUPO, U["D"]))
    # A free, B individual, C y D familiar, E individual; F no tiene suscripción.
    for n, plan, grupo in (("A", 1, None), ("B", 2, None), ("C", 3, GRUPO), ("D", 3, GRUPO), ("E", 2, None)):
        c.execute(
            "INSERT INTO suscripciones VALUES (%s, %s, %s, %s, '2026-01-01', NULL, NULL)",
            (_sus("ABCDEF".index(n)), U[n], plan, grupo),
        )
    # B pagó 10 aprobados en septiembre, 10 rechazados, y 10 en agosto (fuera del período).
    # C (titular de la familia) pagó 20. E (sin país) pagó 5: no entra a ninguna bolsa.
    for i, (n, fecha, monto, estado) in enumerate(
        [
            ("B", "2026-09-05", 10, "aprobado"),
            ("B", "2026-09-06", 10, "rechazado"),
            ("B", "2026-08-31", 10, "aprobado"),
            ("C", "2026-09-10", 20, "aprobado"),
            ("E", "2026-09-10", 5, "aprobado"),
        ]
    ):
        c.execute(
            "INSERT INTO pagos VALUES (%s, %s, %s, %s, %s)",
            (uuid.UUID(int=8000 + i), _sus("ABCDEF".index(n)), fecha, monto, estado),
        )
    for pais in ("CO", "MX"):
        c.execute("INSERT INTO fuente_f7_paises (pais, region, monedas) VALUES (%s, 'R', '{}')", (pais,))
    c.execute(
        "INSERT INTO fuente_f6_cierres VALUES ('COP', '2026-09-30', '2026-09-30', 4000, 'p', now())"
    )
    c.execute("INSERT INTO fuente_f5_publicidad VALUES ('2026-09-01', 'CO', 'COP', 4000000)")
    c.execute("INSERT INTO fuente_f5_publicidad VALUES ('2026-09-01', 'MX', 'USD', 100)")
    c.execute("INSERT INTO titulares_derechos VALUES (%s, 'Sello', 'sello', 'CO')", (TIT,))
    contrato = uuid.UUID(int=6000)
    c.execute(
        "INSERT INTO contratos VALUES (%s, %s, 'pista1', 70, NULL, '2026-01-01', NULL)",
        (contrato, TIT),
    )
    c.execute("INSERT INTO exclusiones_territoriales VALUES (%s, 'AR')", (contrato,))


def test_usuarios_pais_y_componente(pg):
    r = insumos.cargar_usuarios(pg, SEPT)
    por_usuario = {u: (p, c) for u, p, c in r.filas}
    assert por_usuario[str(U["A"])] == ("CO", "publicidad")
    assert por_usuario[str(U["B"])] == ("CO", "suscripcion")
    # RN-10: el miembro D usa el país del titular de su familia, no el suyo (BR).
    assert por_usuario[str(U["D"])] == ("MX", "suscripcion")
    # Sin país no se inventa uno; sin suscripción vigente tampoco hay componente.
    assert r.sin_pais == [str(U["E"])]
    assert r.sin_suscripcion == [str(U["F"])]
    assert str(U["E"]) not in por_usuario and str(U["F"]) not in por_usuario


def test_usuario_con_plan_cambiado_usa_el_vigente_al_cierre(pg):
    pg.execute("UPDATE suscripciones SET fecha_fin = '2026-09-10', motivo_fin = 'cambio_plan' "
               "WHERE usuario_id = %s", (U["B"],))
    pg.execute("INSERT INTO suscripciones VALUES (%s, %s, 1, NULL, '2026-09-11', NULL, NULL)",
               (uuid.UUID(int=5999), U["B"]))
    r = insumos.cargar_usuarios(pg, SEPT)
    assert {u: c for u, _, c in r.filas}[str(U["B"])] == "publicidad"


def test_condiciones_traen_exclusiones(pg):
    (c,) = insumos.cargar_condiciones(pg)
    assert c.titular_id == TIT and c.track_id == "pista1" and c.porcentaje == Decimal(70)
    assert c.exclusiones == frozenset({"AR"})


def test_bolsas_suscripcion_y_publicidad(pg):
    r = insumos.cargar_bolsas(pg, SEPT)
    por_pais = {b.pais: b for b in r.bolsas}
    # CO: B pagó 10 aprobados en septiembre; los rechazados y los de agosto no cuentan.
    assert por_pais["CO"].suscripcion == Decimal("10") * Decimal("0.52")
    # 4 000 000 COP / 4 000 = 1 000 USD de publicidad × 45 %.
    assert por_pais["CO"].publicidad == Decimal("450")
    assert por_pais["MX"].suscripcion == Decimal("20") * Decimal("0.52")
    assert por_pais["MX"].publicidad == Decimal("45")  # USD: sin tasa
    assert r.pagos_sin_pais == 1  # el pago aprobado de E


def test_bolsas_sin_tasa_de_cierre_falla(pg):
    pg.execute("DELETE FROM fuente_f6_cierres")
    with pytest.raises(ValueError, match="COP"):
        insumos.cargar_bolsas(pg, SEPT)


def test_periodo_debe_ser_primer_dia(pg):
    with pytest.raises(ValueError):
        insumos.cargar_usuarios(pg, date(2026, 9, 2))


# --- ejecutar: RDS + Spark + Gold -------------------------------------------------------------


@pytest.fixture(scope="module")
def spark():
    pytest.importorskip("pyspark")
    pytest.importorskip("pandas")
    pytest.importorskip("pyarrow")
    from pyspark.sql import SparkSession

    s = (
        SparkSession.builder.master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    yield s
    s.stop()


def _silver(spark):
    filas = []
    # A (CO, publicidad) y B (CO, suscripción) reproducen pista1; D (familia MX) también.
    for i, (n, pais) in enumerate([("A", "CO"), ("B", "CO"), ("B", "AR"), ("C", "MX"), ("D", "BR")]):
        filas.append((f"play{i}", str(U[n]), "pista1", pais, "2026-09-12T10:00:00Z", "2026-09-01", True))
    return spark.createDataFrame(
        filas,
        "play_id string, user_id string, track_id string, country string, "
        "inicio_utc string, mes_liquidacion string, pagable boolean",
    )


def test_ejecutar_liquida_carga_y_escribe_gold(spark, pg, tmp_path):
    from sonoraplay.spark.gold import ejecutar

    cat = spark.createDataFrame([("pista1", str(TIT))], "track_id string, titular_id string")
    resumen = ejecutar(spark, _silver(spark), cat, pg, SEPT, "run-a", str(tmp_path))
    assert resumen["rds"] == "creada"
    assert resumen["reproducciones_liquidadas"] == 5
    assert resumen["paises"] == ["CO", "MX"]
    assert resumen["usuarios_sin_pais"] == 1 and resumen["pagos_aprobados_sin_pais"] == 1
    filas = pg.execute(
        "SELECT pais, componente, reproducciones_validas, porcentaje_contractual, regalia_usd "
        "FROM reporte_regalias ORDER BY pais, componente, porcentaje_contractual"
    ).fetchall()
    # Una fila por (país, componente, %): la jugada excluida (AR, RN-08) cuenta en el denominador
    # y queda en su propia fila al 0 %. Bolsas a mano (Q8): CO susc. 10 × 52 % = 5,20; CO publ.
    # 1 000 × 45 % = 450; MX susc. 20 × 52 % = 10,40 (D, de BR, paga en MX por RN-10).
    assert filas == [
        ("CO", "publicidad", 1, Decimal("70.00"), Decimal("315.00")),  # 450 × 1/1 × 70 %
        ("CO", "suscripcion", 1, Decimal("0.00"), Decimal("0.00")),
        ("CO", "suscripcion", 1, Decimal("70.00"), Decimal("1.82")),  # 5,20 × 1/2 × 70 %
        ("MX", "suscripcion", 2, Decimal("70.00"), Decimal("7.28")),  # 10,40 × 2/2 × 70 %
    ]
    assert resumen["incidentes"] == 1
    assert (tmp_path / "plays_liquidados").is_dir()


def test_repetir_run_id_no_duplica_y_otro_run_id_conserva_el_anterior(spark, pg, tmp_path):
    from sonoraplay.spark.gold import ejecutar

    cat = spark.createDataFrame([("pista1", str(TIT))], "track_id string, titular_id string")
    silver = _silver(spark)
    a = ejecutar(spark, silver, cat, pg, SEPT, "run-a", str(tmp_path))
    de_nuevo = ejecutar(spark, silver, cat, pg, SEPT, "run-a", str(tmp_path))
    assert de_nuevo["rds"] == "ya_existia"
    assert pg.execute("SELECT count(*) FROM liquidaciones").fetchone()[0] == 1
    b = ejecutar(spark, silver, cat, pg, SEPT, "run-b", str(tmp_path))
    assert b["liquidacion_id"] != a["liquidacion_id"]
    assert pg.execute("SELECT count(*) FROM liquidaciones").fetchone()[0] == 2
    # Gold conserva ambas liquidaciones (partitionOverwriteMode=dynamic): no se borró la primera.
    leidas = spark.read.parquet(str(tmp_path / "plays_liquidados"))
    por_liq = {r["liquidacion_id"]: r["n"] for r in leidas.groupBy("liquidacion_id").count()
               .withColumnRenamed("count", "n").collect()}
    assert por_liq == {a["liquidacion_id"]: 5, b["liquidacion_id"]: 5}
