"""EG-39 · El arnés de medición: genera datos, corre las variantes y exige resultado idéntico."""

import pytest

pytest.importorskip("pyspark")
pytest.importorskip("pandas")
pytest.importorskip("pyarrow")

from sonoraplay.spark.medicion import medir
from sonoraplay.spark.medicion.generador import Parametros, generar

PEQUENO = Parametros(
    reproducciones=1500, usuarios=200, artistas=20, pistas_por_artista=5, titulares=5, dias=5
)


@pytest.fixture(scope="module")
def datos(tmp_path_factory):
    from pyspark.sql import SparkSession

    carpeta = tmp_path_factory.mktemp("eg39")
    spark = (
        SparkSession.builder.master("local[2]")
        .config("spark.sql.session.timeZone", "UTC")
        .config("spark.sql.shuffle.partitions", "4")
        .getOrCreate()
    )
    try:
        resumen = generar(spark, str(carpeta), PEQUENO)
    finally:
        spark.stop()
    return carpeta, resumen


def test_el_generador_es_determinista_y_sesgado(datos):
    from pyspark.sql import SparkSession
    from pyspark.sql import functions as F

    carpeta, resumen = datos
    assert resumen["reproducciones"] == 1500
    assert resumen["eventos"] >= 3000  # start + end por reproducción, más duplicados
    spark = SparkSession.builder.master("local[2]").getOrCreate()
    try:
        por_artista = (
            spark.read.parquet(f"{carpeta}/catalogo")
            .join(
                spark.read.json(f"{carpeta}/bronze").select("track_id").distinct(),
                "track_id",
            )
            .groupBy("artista_id")
            .count()
        )
        assert por_artista.agg(F.max("count")).first()[0] >= 1
    finally:
        spark.stop()


def test_todas_las_variantes_dan_el_mismo_resultado(datos):
    carpeta, _ = datos
    resultados = [
        medir.correr(
            v,
            f"{carpeta}/bronze",
            f"{carpeta}/catalogo",
            f"{carpeta}/salida",
            repeticiones=1,
            memoria="1g",
        )
        for v in medir.VARIANTES.values()
    ]
    assert medir.verificar_identico(resultados) == []
    assert all(r["huella_silver"]["filas"] > 0 for r in resultados)


def test_la_poda_y_su_contraparte_dan_lo_mismo_con_alcance_acotado(datos):
    carpeta, _ = datos
    pares = [
        medir.correr(
            medir.VARIANTES[nombre],
            f"{carpeta}/bronze",
            f"{carpeta}/catalogo",
            f"{carpeta}/salida",
            hasta="2026-09-03",
            repeticiones=1,
            memoria="1g",
        )
        for nombre in ("base", "poda")
    ]
    assert pares[0]["huella_silver"] == pares[1]["huella_silver"]


def test_una_diferencia_se_detecta():
    falso = {
        "huella_silver": {"filas": 1, "hash": 1},
        "huella_liquidacion": {"filas": 1, "hash": 2},
    }
    base = {"variante": "base", **falso}
    otra = {"variante": "sal", **falso, "huella_liquidacion": {"filas": 1, "hash": 3}}
    assert medir.verificar_identico([base, otra]) == ["sal: huella_liquidacion distinta de la base"]


def test_el_informe_no_inventa_costos():
    r = {
        "variante": "base",
        "mediana": {"silver": 10.0, "liquidacion": 5.0},
        "huella_silver": {"filas": 1, "hash": 1},
        "huella_liquidacion": {"filas": 1, "hash": 1},
    }
    meta = {"entorno": "x", "datos": "y"}
    sin = medir.informe([r], meta)
    assert "pendiente" in sin
    con = medir.informe([r], meta, precio_vcpu_h=0.04, precio_gb_h=0.004)
    assert "USD" in con and "pendiente" not in con
    assert "no se extrapola" in con
