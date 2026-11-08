"""EG-37 · La liquidación en Spark da lo mismo que las funciones puras de la EG-23."""

import os
import random
import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

import psycopg
from pyspark.sql import SparkSession

from sonoraplay.reglas.liquidacion import (
    BolsaPais,
    CondicionContrato,
    ReproduccionLiquidable,
    indexar_condiciones,
    liquidar_pais,
)
from sonoraplay.reporte_regalias import Componente
from sonoraplay.spark.gold import cargar_rds, liquidacion_id_de, liquidar

SEPT = date(2026, 9, 1)
TITULARES = [uuid.UUID(int=i + 1) for i in range(4)]
PAISES = ("CO", "MX", "AR")
DDL = sorted(Path(__file__).resolve().parents[2].glob("db/ddl/00[1-3]_*.sql"))


@pytest.fixture(scope="module")
def spark():
    s = (
        SparkSession.builder.master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    yield s
    s.stop()


def condiciones() -> list[CondicionContrato]:
    """Cambio de % a mitad de mes (RN-07), territorial (Q7) y exclusión (RN-08)."""
    out = []
    for t_i, t in enumerate(TITULARES):
        for k in range(6):
            track = f"t{k}"
            out.append(
                CondicionContrato(
                    uuid.uuid4(),
                    t,
                    track,
                    Decimal(50 + t_i * 5),
                    date(2026, 1, 1),
                    date(2026, 9, 14),
                )
            )
            out.append(
                CondicionContrato(uuid.uuid4(), t, track, Decimal(40 + t_i * 5), date(2026, 9, 15))
            )
    # Un territorio con % propio y otro excluido, solo para el titular 0 y la pista t0.
    out.append(
        CondicionContrato(
            uuid.uuid4(), TITULARES[0], "t0", Decimal(90), date(2026, 1, 1), None, "MX"
        )
    )
    return out


def datos(n: int, semilla: int = 7):
    """n reproducciones: (play_id, usuario, pista, titular, inicio, país de reproducción)."""
    r = random.Random(semilla)
    usuarios = {
        f"u{i}": (r.choice(PAISES), r.choice([Componente.SUSCRIPCION, Componente.PUBLICIDAD]))
        for i in range(60)
    }
    plays = []
    base = datetime(2026, 9, 1, tzinfo=UTC)
    for i in range(n):
        u = r.choice(list(usuarios))
        track = f"t{r.randrange(6)}"
        # sesgo: el primer titular concentra la mitad de las reproducciones
        titular = TITULARES[0] if r.random() < 0.5 else r.choice(TITULARES)
        inicio = base + timedelta(seconds=r.randrange(30 * 86_400))
        plays.append((f"p{i}", u, track, titular, inicio, r.choice(PAISES)))
    return usuarios, plays


def a_dataframes(spark, usuarios, plays, titular_de_pista):
    silver = spark.createDataFrame(
        [
            (pid, u, tr, pais_rep, ini.isoformat(), SEPT.isoformat(), True)
            for pid, u, tr, _, ini, pais_rep in plays
        ],
        "play_id string, user_id string, track_id string, country string, "
        "inicio_utc string, mes_liquidacion string, pagable boolean",
    )
    usr = spark.createDataFrame(
        [(u, p, str(c)) for u, (p, c) in usuarios.items()],
        "user_id string, pais_facturacion string, componente string",
    )
    cat = spark.createDataFrame(
        [(tr, str(t)) for tr, t in titular_de_pista.items()], "track_id string, titular_id string"
    )
    return silver, usr, cat


def esperado(usuarios, plays, titular_de_pista, conds, bolsas):
    """La misma liquidación con las funciones puras, reproducción por reproducción."""
    reps = [
        ReproduccionLiquidable(
            pid, u, titular_de_pista[tr], tr, ini, usuarios[u][0], pais_rep, usuarios[u][1]
        )
        for pid, u, tr, _, ini, pais_rep in plays
    ]
    indice = indexar_condiciones(conds)
    return [liquidar_pais(SEPT, b, reps, indice) for b in bolsas]


def clave(f):
    return (str(f.titular_id), f.pais, str(f.componente), f.porcentaje_contractual)


def bolsas():
    return [
        BolsaPais("CO", Decimal("100.005"), Decimal("33.333")),
        BolsaPais("MX", Decimal("5000.50"), Decimal("1234.567")),
        BolsaPais("AR", Decimal("777.777"), Decimal("0.01")),
    ]


def test_spark_da_lo_mismo_que_las_funciones_puras(spark):
    usuarios, plays = datos(1500)
    # Una pista pertenece a un titular: el titular del catálogo manda.
    titular_de_pista = {f"t{k}": TITULARES[k % len(TITULARES)] for k in range(6)}
    plays = [(pid, u, tr, titular_de_pista[tr], ini, pr) for pid, u, tr, _, ini, pr in plays]
    conds = [c for c in condiciones() if titular_de_pista[c.track_id] == c.titular_id]
    silver, usr, cat = a_dataframes(spark, usuarios, plays, titular_de_pista)

    salida, _ = liquidar(spark, silver, usr, cat, conds, bolsas(), SEPT, "run-1")
    puro = esperado(usuarios, plays, titular_de_pista, conds, bolsas())

    spark_filas = {clave(f): f for f in salida.filas}
    puro_filas = {clave(f): f for r in puro for f in r.filas}
    assert spark_filas.keys() == puro_filas.keys()
    for k, f in puro_filas.items():
        g = spark_filas[k]
        assert g.regalia_usd == f.regalia_usd, k
        assert g.reproducciones_validas == f.reproducciones_validas, k
        assert g.participacion == f.participacion, k
    assert sum(len(r.incidentes) for r in salida.resultados) == sum(len(r.incidentes) for r in puro)


def test_la_suma_por_pais_no_supera_la_bolsa_rnf02(spark):
    usuarios, plays = datos(800, semilla=11)
    titular_de_pista = {f"t{k}": TITULARES[k % len(TITULARES)] for k in range(6)}
    plays = [(pid, u, tr, titular_de_pista[tr], ini, pr) for pid, u, tr, _, ini, pr in plays]
    conds = [c for c in condiciones() if titular_de_pista[c.track_id] == c.titular_id]
    silver, usr, cat = a_dataframes(spark, usuarios, plays, titular_de_pista)
    salida, _ = liquidar(spark, silver, usr, cat, conds, bolsas(), SEPT, "run-rnf02")
    for r in salida.resultados:
        for comp in Componente:
            assert r.total_usd(comp) <= r.bolsa.de(comp) + Decimal("0.01"), (r.bolsa.pais, comp)
        assert r.total_usd() <= r.bolsa.total + Decimal("0.01")


def test_cada_reproduccion_liquidada_lleva_su_liquidacion_id(spark):
    """RNF-03: la regalía se rastrea hasta sus reproducciones por el ID de la liquidación."""
    usuarios, plays = datos(400, semilla=3)
    titular_de_pista = {f"t{k}": TITULARES[k % len(TITULARES)] for k in range(6)}
    plays = [(pid, u, tr, titular_de_pista[tr], ini, pr) for pid, u, tr, _, ini, pr in plays]
    conds = [c for c in condiciones() if titular_de_pista[c.track_id] == c.titular_id]
    silver, usr, cat = a_dataframes(spark, usuarios, plays, titular_de_pista)
    salida, trazas = liquidar(spark, silver, usr, cat, conds, bolsas(), SEPT, "run-traza")
    filas = trazas.collect()
    assert len(filas) == len(plays) == salida.reproducciones_liquidadas
    assert {r["liquidacion_id"] for r in filas} == {str(salida.liquidacion_id)}
    assert len({r["play_id"] for r in filas}) == len(plays)  # ninguna repetida ni perdida
    # Las reproducciones de una fila del reporte suman exactamente su conteo.
    for f in salida.filas:
        n = sum(
            1
            for r in filas
            if (r["titular_id"], r["pais_facturacion"], r["componente"])
            == (str(f.titular_id), f.pais, str(f.componente))
            and Decimal(r["porcentaje"]) == f.porcentaje_contractual
        )
        assert n == f.reproducciones_validas


def test_falla_si_un_pais_no_tiene_bolsa_o_un_usuario_no_tiene_pais(spark):
    usuarios, plays = datos(50, semilla=5)
    titular_de_pista = {f"t{k}": TITULARES[0] for k in range(6)}
    plays = [(pid, u, tr, TITULARES[0], ini, pr) for pid, u, tr, _, ini, pr in plays]
    silver, usr, cat = a_dataframes(spark, usuarios, plays, titular_de_pista)
    with pytest.raises(ValueError, match="faltan bolsas"):
        liquidar(spark, silver, usr, cat, [], [BolsaPais("CO", Decimal(1), Decimal(1))], SEPT, "r")
    huerfano = usr.filter(f"user_id != '{plays[0][1]}'")  # el usuario de la primera reproducción
    with pytest.raises(ValueError, match="sin país de facturación"):
        liquidar(spark, silver, huerfano, cat, [], bolsas(), SEPT, "r")


def test_el_run_id_fija_el_liquidacion_id():
    assert liquidacion_id_de("a", SEPT) == liquidacion_id_de("a", SEPT)
    assert liquidacion_id_de("a", SEPT) != liquidacion_id_de("b", SEPT)
    assert liquidacion_id_de("a", SEPT) != liquidacion_id_de("a", date(2026, 10, 1))
    with pytest.raises(ValueError):
        liquidacion_id_de("", SEPT)


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
        for t in TITULARES:  # titulares_derechos exige estas filas (FK de reporte_regalias)
            c.execute(
                "INSERT INTO titulares_derechos (titular_id, nombre, tipo, pais) "
                "VALUES (%s, %s, 'sello', 'CO')",
                (t, f"Sello {t.int}"),
            )
        c.commit()
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA {esquema} CASCADE")
        c.commit()


def _liquidar_para_bd(spark, run_id):
    usuarios, plays = datos(300, semilla=9)
    titular_de_pista = {f"t{k}": TITULARES[k % len(TITULARES)] for k in range(6)}
    plays = [(pid, u, tr, titular_de_pista[tr], ini, pr) for pid, u, tr, _, ini, pr in plays]
    conds = [c for c in condiciones() if titular_de_pista[c.track_id] == c.titular_id]
    silver, usr, cat = a_dataframes(spark, usuarios, plays, titular_de_pista)
    return liquidar(spark, silver, usr, cat, conds, bolsas(), SEPT, run_id)[0]


def test_repetir_el_mismo_run_id_no_duplica_filas(spark, pg):
    s = _liquidar_para_bd(spark, "run-bd")
    assert cargar_rds(pg, s) == "creada"
    filas = pg.execute("SELECT count(*) FROM reporte_regalias").fetchone()[0]
    assert filas == len(s.filas) > 0
    assert cargar_rds(pg, _liquidar_para_bd(spark, "run-bd")) == "ya_existia"
    assert pg.execute("SELECT count(*) FROM reporte_regalias").fetchone()[0] == filas
    assert pg.execute("SELECT count(*) FROM liquidaciones").fetchone()[0] == 1
    assert pg.execute("SELECT publicada_en IS NOT NULL FROM liquidaciones").fetchone()[0]


def test_un_run_id_nuevo_agrega_una_version_y_no_toca_la_original(spark, pg):
    """CA-07 / RF-09: re-liquidar agrega filas; las originales no se actualizan."""
    cargar_rds(pg, _liquidar_para_bd(spark, "run-original"))
    antes = pg.execute(
        "SELECT liquidacion_id, titular_id, pais, componente, porcentaje_contractual, "
        "regalia_usd, reproducciones_validas FROM reporte_regalias ORDER BY 1,2,3,4,5"
    ).fetchall()
    cargar_rds(pg, _liquidar_para_bd(spark, "run-ajuste"))
    assert pg.execute("SELECT count(*) FROM liquidaciones").fetchone()[0] == 2
    despues = pg.execute(
        "SELECT liquidacion_id, titular_id, pais, componente, porcentaje_contractual, "
        "regalia_usd, reproducciones_validas FROM reporte_regalias WHERE liquidacion_id = %s "
        "ORDER BY 1,2,3,4,5",
        (liquidacion_id_de("run-original", SEPT),),
    ).fetchall()
    assert despues == antes  # la versión original quedó intacta


def test_mismo_run_id_con_otro_resultado_no_sobrescribe(spark, pg):
    s = _liquidar_para_bd(spark, "run-x")
    cargar_rds(pg, s)
    usuarios, plays = datos(100, semilla=1)
    titular_de_pista = {f"t{k}": TITULARES[k % len(TITULARES)] for k in range(6)}
    plays = [(pid, u, tr, titular_de_pista[tr], ini, pr) for pid, u, tr, _, ini, pr in plays]
    conds = [c for c in condiciones() if titular_de_pista[c.track_id] == c.titular_id]
    silver, usr, cat = a_dataframes(spark, usuarios, plays, titular_de_pista)
    otra = liquidar(spark, silver, usr, cat, conds, bolsas(), SEPT, "run-x")[0]
    with pytest.raises(ValueError, match="otro resultado"):
        cargar_rds(pg, otra)


def test_eg36_retained_plays_never_enter_gold_or_published_rds(spark, pg):
    """RN-03: validate actual Spark Gold traces and PostgreSQL published rows."""
    holder = TITULARES[0]
    silver = spark.createDataFrame(
        [
            (
                "farm-1",
                "farm",
                "t0",
                "CO",
                "2026-09-10T01:00:00+00:00",
                SEPT.isoformat(),
                True,
                "en_revision",
                False,
            ),
            (
                "farm-2",
                "farm",
                "t0",
                "CO",
                "2026-09-10T02:00:00+00:00",
                SEPT.isoformat(),
                True,
                "en_revision",
                False,
            ),
            (
                "legit-1",
                "legit",
                "t0",
                "CO",
                "2026-09-10T03:00:00+00:00",
                SEPT.isoformat(),
                True,
                "valida_para_fraude",
                True,
            ),
        ],
        "play_id string, user_id string, track_id string, country string, "
        "inicio_utc string, mes_liquidacion string, pagable boolean, "
        "estado_fraude string, pagable_gold boolean",
    )
    users = spark.createDataFrame(
        [
            ("farm", "CO", str(Componente.SUSCRIPCION)),
            ("legit", "CO", str(Componente.SUSCRIPCION)),
        ],
        "user_id string, pais_facturacion string, componente string",
    )
    cat = spark.createDataFrame([("t0", str(holder))], "track_id string, titular_id string")
    contracts = [
        CondicionContrato(uuid.uuid4(), holder, "t0", Decimal("50"), date(2026, 1, 1), None)
    ]
    pools = [BolsaPais("CO", Decimal("100.00"), Decimal("0.00"))]
    result, trace = liquidar(spark, silver, users, cat, contracts, pools, SEPT, "eg36-published")
    assert {r["play_id"] for r in trace.select("play_id").collect()} == {"legit-1"}
    assert result.reproducciones_liquidadas == 1
    assert sum((r.regalia_usd for r in result.filas), Decimal("0")) == Decimal("50.00")
    assert cargar_rds(pg, result) == "creada"
    published = pg.execute(
        "SELECT regalia_usd, reproducciones_validas FROM reporte_regalias "
        "WHERE liquidacion_id = %s",
        (result.liquidacion_id,),
    ).fetchall()
    assert len(published) == 1
    assert published[0] == (Decimal("50.00"), 1)
    assert pg.execute(
        "SELECT publicada_en IS NOT NULL FROM liquidaciones WHERE liquidacion_id = %s",
        (result.liquidacion_id,),
    ).fetchone()[0]
