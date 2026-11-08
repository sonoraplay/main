"""Integración EG-33 → EG-35 → EG-37: Bronze en S3 → Silver verificado → liquidación Gold.

Corre cuando coexisten las tres piezas (Bronze en S3 de la EG-33, Silver de la EG-35 y la
liquidación de la EG-37); mientras alguna no esté en la rama, se salta. El S3 es un directorio
local: lo que se prueba es el **contrato entre las tres etapas**, no AWS.
"""

import uuid
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from pathlib import Path

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")
silver = pytest.importorskip("sonoraplay.spark.silver", reason="falta Silver (EG-35, PR #38)")
bronze_s3 = pytest.importorskip("sonoraplay.streaming.bronze_s3", reason="falta Bronze (EG-33)")
gold = pytest.importorskip("sonoraplay.spark.gold", reason="falta Gold (EG-37)")

from pyspark.sql import SparkSession  # noqa: E402

from sonoraplay.reglas.liquidacion import (  # noqa: E402
    BolsaPais,
    CondicionContrato,
    ReproduccionLiquidable,
    indexar_condiciones,
    liquidar_pais,
)
from sonoraplay.reporte_regalias import Componente  # noqa: E402

SEPT = date(2026, 9, 1)
HASTA = date(2026, 9, 14)
TITULAR = uuid.UUID(int=1)
PISTAS = [f"pista{i}" for i in range(6)]


class S3Directorio:
    """Cliente S3 mínimo que escribe los objetos como archivos de un directorio."""

    def __init__(self, raiz: Path):
        self.raiz = raiz

    def put_object(self, Bucket, Key, Body, **_):  # noqa: N803
        destino = self.raiz / Key
        destino.parent.mkdir(parents=True, exist_ok=True)
        destino.write_bytes(Body)


def _ts(dt: datetime) -> str:
    return dt.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def reproducciones(n: int = 400):
    """n reproducciones con duración conocida; a lo sumo 1 por usuario, pista y día (sin RN-02)."""
    out = []
    for i in range(n):
        inicio = datetime(2026, 9, 1 + i % 14, 10, tzinfo=UTC) + timedelta(seconds=i * 7)
        out.append(
            {
                "id": i,
                "usuario": str(uuid.UUID(int=1000 + i)),  # un usuario distinto por reproducción
                "pista": PISTAS[i % len(PISTAS)],
                "pais": ("CO", "MX")[i % 2],
                "inicio": inicio,
                "duracion_s": 10 + (i * 13) % 230,  # 10 a 239 s: unas < 30 s (inválidas, RN-01)
                "sesion": str(uuid.UUID(int=500_000 + i)),
            }
        )
    return out


def eventos(r: dict) -> list[dict]:
    base = {
        "schema_version": "1.0",
        "user_id": r["usuario"],
        "device_id": "dev-1",
        "track_id": r["pista"],
        "session_id": r["sesion"],
        "country_playback": r["pais"],
        "is_offline": False,
    }
    fin = r["inicio"] + timedelta(seconds=r["duracion_s"])
    return [
        {
            **base,
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, r["sesion"] + "s")),
            "event_type": "start",
            "device_ts": _ts(r["inicio"]),
            "server_ts": _ts(r["inicio"] + timedelta(milliseconds=200)),
            "position_ms": 0,
        },
        {
            **base,
            "event_id": str(uuid.uuid5(uuid.NAMESPACE_URL, r["sesion"] + "e")),
            "event_type": "end",
            "device_ts": _ts(fin),
            "server_ts": _ts(fin + timedelta(milliseconds=200)),
            "position_ms": r["duracion_s"] * 1000,
        },
    ]


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


@pytest.fixture(scope="module")
def cadena(spark, tmp_path_factory):
    """Bronze (con reintentos duplicados) → snapshot de Silver publicado y verificado."""
    raiz = tmp_path_factory.mktemp("integracion")
    reps = reproducciones()
    evs = [e for r in reps for e in eventos(r)]
    # Consumidor 1 escribe todo en lotes de 100; consumidor 2 re-entrega los primeros 250 con
    # otros límites de lote: duplicados reales entre objetos de Bronze (criterio 3 de la EG-33).
    cliente = S3Directorio(raiz)
    for lote, lista in ((100, evs), (70, evs[:250])):
        a = bronze_s3.AlmacenBronzeS3(cliente, "bronze", "f2", tam_lote=lote)
        for e in lista:
            a.guardar(e)
        a.cerrar()
    bronce = str(raiz / "f2")
    silver_raiz, cuarentena_raiz = str(raiz / "silver"), str(raiz / "quarantine")
    catalogo = spark.createDataFrame([(p,) for p in PISTAS], ["track_id"])
    silver.write_historical_snapshot(
        spark,
        bronce,
        catalogo,
        silver_raiz,
        cuarentena_raiz,
        fecha=HASTA,
        run_id="run-1",
        source_version="prueba",
    )
    silver.publish_verified_snapshot(
        spark, silver_raiz, cuarentena_raiz, "run-1", fecha=HASTA, source_version="prueba"
    )
    return {
        "spark": spark,
        "reps": reps,
        "raiz": raiz,
        "silver_raiz": silver_raiz,
        "cuarentena_raiz": cuarentena_raiz,
    }


def pagables_esperadas(reps):
    return {r["sesion"] for r in reps if r["duracion_s"] >= 30}  # RN-01: ≥ 30 s continuos


def test_silver_lee_el_bronze_de_la_eg33_y_quita_los_duplicados(cadena):
    s, _, marcador = silver.read_verified_snapshot(
        cadena["spark"], cadena["silver_raiz"], cadena["cuarentena_raiz"], "run-1"
    )
    assert marcador["run_id"] == "run-1" and marcador["fecha"] == HASTA.isoformat()
    por_id = {r["play_id"]: r for r in s.collect()}
    assert len(por_id) == len(cadena["reps"])  # una por sesión: los duplicados no inflan nada
    pagables = {pid for pid, r in por_id.items() if r["pagable"]}
    assert pagables == pagables_esperadas(cadena["reps"])


def test_gold_liquida_exactamente_lo_que_silver_publico(cadena):
    spark = cadena["spark"]
    s, _, _ = silver.read_verified_snapshot(
        spark, cadena["silver_raiz"], cadena["cuarentena_raiz"], "run-1"
    )
    reps = cadena["reps"]
    pais_de = {"CO": "CO", "MX": "MX"}
    usuarios = {
        r["usuario"]: (
            pais_de[r["pais"]],
            Componente.SUSCRIPCION if i % 3 else Componente.PUBLICIDAD,
        )
        for i, r in enumerate(reps)
    }
    usr = spark.createDataFrame(
        [(u, p, str(c)) for u, (p, c) in usuarios.items()],
        "user_id string, pais_facturacion string, componente string",
    )
    cat = spark.createDataFrame(
        [(p, str(TITULAR)) for p in PISTAS], "track_id string, titular_id string"
    )
    conds = [
        CondicionContrato(uuid.uuid4(), TITULAR, p, Decimal(80), date(2026, 1, 1)) for p in PISTAS
    ]
    bolsas = [
        BolsaPais("CO", Decimal("1000.005"), Decimal("200.333")),
        BolsaPais("MX", Decimal("800.50"), Decimal("90.10")),
    ]
    salida, trazas = gold.liquidar(
        spark,
        s,
        usr,
        cat,
        conds,
        bolsas,
        SEPT,
        "run-gold-1",
        fraude_verificado=False,
    )

    esperadas = pagables_esperadas(reps)
    assert salida.reproducciones_liquidadas == len(esperadas)
    filas = trazas.collect()
    assert {f["play_id"] for f in filas} == esperadas
    assert {f["liquidacion_id"] for f in filas} == {str(salida.liquidacion_id)}

    # Verdad de campo con las funciones puras, sin pasar por Spark.
    liquidables = [
        ReproduccionLiquidable(
            r["sesion"],
            r["usuario"],
            TITULAR,
            r["pista"],
            r["inicio"],
            usuarios[r["usuario"]][0],
            r["pais"],
            usuarios[r["usuario"]][1],
        )
        for r in reps
        if r["sesion"] in esperadas
    ]
    puro = [liquidar_pais(SEPT, b, liquidables, indexar_condiciones(conds)) for b in bolsas]
    clave = lambda f: (str(f.titular_id), f.pais, str(f.componente), f.porcentaje_contractual)  # noqa: E731
    spark_filas = {clave(f): f for f in salida.filas}
    puro_filas = {clave(f): f for res in puro for f in res.filas}
    assert spark_filas.keys() == puro_filas.keys()
    for k, f in puro_filas.items():
        assert spark_filas[k].regalia_usd == f.regalia_usd, k
        assert spark_filas[k].reproducciones_validas == f.reproducciones_validas, k
    for res in salida.resultados:  # RNF-02
        assert res.total_usd() <= res.bolsa.total + Decimal("0.01")
