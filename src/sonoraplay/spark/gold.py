"""EG-37 · Liquidación de regalías en Spark (capa Gold), con trazabilidad y carga idempotente.

Reutiliza las reglas puras de la EG-23 en lugar de reescribirlas:

1. **Distribuido:** las reproducciones pagables del período (Silver) se unen con el país de
   facturación/componente del usuario (F3) y el titular de la pista (F1), y se agrupan por
   (país, componente, titular, pista, fecha UTC, país de reproducción). Cada grupo pregunta su %
   a ``porcentaje_aplicable`` (RN-07, RN-08, Q7), igual que ``liquidar_pais``.
2. **En el driver (pocas filas):** los conteos por (componente, titular, %) de cada país se
   reparten con ``repartir_bolsa``, la misma función que usa ``liquidar_pais`` (RNF-02).
3. **Trazabilidad (RNF-03):** cada reproducción liquidada se escribe en Gold con el
   ``liquidacion_id`` en que se pagó.
4. **Append-only (ADR-0007, CA-07):** cada ``run_id`` produce un ``liquidacion_id`` propio
   (determinista). Una corrida nueva agrega una liquidación nueva y no toca las anteriores;
   repetir el mismo ``run_id`` no duplica nada y falla si el resultado difiere.

Las bolsas de cada país (Q8) llegan como argumento: se calculan con las funciones puras
``calcular_bolsa`` y compañía a partir de F3, F5 y F6.
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sonoraplay.reglas.liquidacion import (
    BolsaPais,
    CondicionContrato,
    Incidente,
    ReproduccionLiquidable,
    ResultadoLiquidacion,
    TipoIncidente,
    indexar_condiciones,
    porcentaje_aplicable,
    repartir_bolsa,
)
from sonoraplay.reporte_regalias import Componente, FilaReporte

NAMESPACE_LIQUIDACION = uuid.UUID("3f1c2a3e-6d0b-5b7e-9a58-0a5e6f4b5d10")
_TITULAR_VACIO = uuid.UUID(int=0)


def liquidacion_id_de(run_id: str, periodo: date) -> uuid.UUID:
    """ID determinista: el mismo ``run_id`` y período dan siempre el mismo ``liquidacion_id``."""
    if not run_id:
        raise ValueError("run_id no puede estar vacío")
    return uuid.uuid5(NAMESPACE_LIQUIDACION, f"{run_id}|{periodo.isoformat()}")


@dataclass(frozen=True)
class SalidaGold:
    liquidacion_id: uuid.UUID
    periodo: date
    run_id: str
    resultados: tuple[ResultadoLiquidacion, ...]
    reproducciones_liquidadas: int

    @property
    def filas(self) -> list[FilaReporte]:
        return [f for r in self.resultados for f in r.filas]

    @property
    def incidentes(self) -> list[Incidente]:
        return [i for r in self.resultados for i in r.incidentes]


# --- Entradas --------------------------------------------------------------------------------


def condiciones_desde_filas(filas: Iterable[Mapping]) -> list[CondicionContrato]:
    """Filas de F4 (como dicts) a ``CondicionContrato``. ``porcentaje`` llega como texto."""
    salida = []
    for f in filas:
        salida.append(
            CondicionContrato(
                contrato_id=uuid.UUID(str(f["contrato_id"])),
                titular_id=uuid.UUID(str(f["titular_id"])),
                track_id=f["track_id"],
                porcentaje=Decimal(str(f["porcentaje"])),
                valido_desde=_fecha(f["valido_desde"]),
                valido_hasta=_fecha(f["valido_hasta"]) if f.get("valido_hasta") else None,
                territorio=f.get("territorio"),
                exclusiones=frozenset(f.get("exclusiones") or ()),
            )
        )
    return salida


def _fecha(valor) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(str(valor))


# --- Job -------------------------------------------------------------------------------------


def liquidar(
    spark,
    silver,
    usuarios,
    catalogo,
    condiciones: list[CondicionContrato],
    bolsas: Iterable[BolsaPais],
    periodo: date,
    run_id: str,
    suscripciones=None,
    fraude_verificado=False,
):
    """Liquida ``periodo``. Devuelve ``(SalidaGold, plays_liquidados: DataFrame)``.

    - ``silver``: salida de la EG-35 (``play_id, user_id, track_id, country, inicio_utc,
      mes_liquidacion, pagable``).
    - ``usuarios``: ``user_id, pais_facturacion, componente`` (F3: Q6, RN-10, Q8).
    - ``catalogo``: ``track_id, titular_id`` (F1).
    - ``bolsas``: una ``BolsaPais`` por país a liquidar.
    - ``suscripciones`` (opcional): ``user_id, componente, desde, hasta, prioridad`` con ``hasta``
      **exclusivo**. Si se pasa, el componente de cada reproducción es el de la suscripción vigente
      **en su fecha UTC** (un usuario que cambia de plan a mitad de mes no queda mal liquidado) y
      se ignora ``usuarios.componente``. Sin suscripción vigente la corrida falla.
    """
    from pyspark.sql import functions as F
    from pyspark.sql.types import LongType, StringType, StructField, StructType

    if periodo.day != 1:
        raise ValueError("periodo debe ser el primer día del mes")
    liquidacion_id = liquidacion_id_de(run_id, periodo)
    bolsas_por_pais = {b.pais: b for b in bolsas}
    indice = indexar_condiciones(condiciones)

    if suscripciones is None:
        usuarios_cols = usuarios.select("user_id", "pais_facturacion", "componente")
    else:
        usuarios_cols = usuarios.select("user_id", "pais_facturacion")
    if fraude_verificado or "pagable_gold" in silver.columns or "estado_fraude" in silver.columns:
        from sonoraplay.spark.fraude import preparar_gold

        silver_pagable = preparar_gold(silver, periodo)
    else:
        # Backwards compatibility for EG-37 unit tests only.
        # Production CLI always requires the fraud gate.
        silver_pagable = silver.filter(
            F.col("pagable") & (F.col("mes_liquidacion") == periodo.isoformat())
        )
    base = silver_pagable.join(usuarios_cols, "user_id", "left")
    if suscripciones is not None:
        base = _con_componente_por_fecha(base, suscripciones)
    base = base.join(catalogo.select("track_id", "titular_id"), "track_id", "left").cache()
    huerfanas = base.filter(
        F.col("pais_facturacion").isNull()
        | F.col("titular_id").isNull()
        | F.col("componente").isNull()
    ).count()
    if huerfanas:
        base.unpersist()
        raise ValueError(
            f"{huerfanas} reproducciones pagables sin país de facturación, sin titular o sin "
            "plan vigente en su fecha: no se inventa ninguno; se corrige en F3/F1 y se vuelve "
            "a correr"
        )
    paises = {r[0] for r in base.select("pais_facturacion").distinct().collect()}
    sin_bolsa = sorted(paises - set(bolsas_por_pais))
    if sin_bolsa:
        base.unpersist()
        raise ValueError(f"faltan bolsas para los países: {', '.join(sin_bolsa)}")

    grupos = base.groupBy(
        "pais_facturacion",
        "componente",
        "titular_id",
        "track_id",
        F.substring("inicio_utc", 1, 10).alias("fecha"),
        F.col("country").alias("pais_reproduccion"),
    ).agg(F.count("*").alias("n"))

    esquema = StructType(
        [
            StructField("pais_facturacion", StringType()),
            StructField("componente", StringType()),
            StructField("titular_id", StringType()),
            StructField("track_id", StringType()),
            StructField("fecha", StringType()),
            StructField("pais_reproduccion", StringType()),
            StructField("n", LongType()),
            StructField("porcentaje", StringType()),
            StructField("incidente", StringType()),
            StructField("contrato_id", StringType()),
        ]
    )

    def con_porcentaje(lotes):
        for pdf in lotes:
            pcts, incs, contratos = [], [], []
            for r in pdf.itertuples(index=False):
                rep = ReproduccionLiquidable(
                    reproduccion_id="grupo",
                    usuario_id="grupo",
                    titular_id=uuid.UUID(r.titular_id),
                    track_id=r.track_id,
                    inicio=datetime.fromisoformat(r.fecha + "T12:00:00+00:00"),
                    pais_facturacion=r.pais_facturacion,
                    pais_reproduccion=r.pais_reproduccion,
                    componente=Componente(r.componente),
                )
                pct, cond, inc = porcentaje_aplicable(rep, indice)
                pcts.append(str(pct))
                incs.append(inc.tipo.value if inc else None)
                contratos.append(str(cond.contrato_id) if cond else None)
            pdf = pdf.assign(porcentaje=pcts, incidente=incs, contrato_id=contratos)
            yield pdf

    grupos = grupos.withColumn("titular_id", F.col("titular_id").cast("string"))
    con_pct = grupos.mapInPandas(con_porcentaje, esquema).cache()

    conteos_df = (
        con_pct.groupBy("pais_facturacion", "componente", "titular_id", "porcentaje")
        .agg(F.sum("n").alias("n"))
        .collect()
    )

    por_pais: dict[str, dict[tuple[Componente, uuid.UUID, Decimal], int]] = defaultdict(dict)
    for r in conteos_df:
        clave = (Componente(r["componente"]), uuid.UUID(r["titular_id"]), Decimal(r["porcentaje"]))
        por_pais[r["pais_facturacion"]][clave] = int(r["n"])
    inc_por_pais = _incidentes(con_pct)

    resultados = []
    total = 0
    for pais in sorted(por_pais):
        resultados.append(
            repartir_bolsa(periodo, bolsas_por_pais[pais], por_pais[pais], inc_por_pais[pais])
        )
        total += sum(por_pais[pais].values())

    claves = con_pct.select(
        F.col("pais_facturacion").alias("g_pais"),
        F.col("componente").alias("g_comp"),
        F.col("titular_id").alias("g_titular"),
        F.col("track_id").alias("g_track"),
        F.col("fecha").alias("g_fecha"),
        F.col("pais_reproduccion").alias("g_pais_rep"),
        "porcentaje",
    )
    plays = base.join(
        claves,
        (base["pais_facturacion"] == claves["g_pais"])
        & (base["componente"] == claves["g_comp"])
        & (base["titular_id"].cast("string") == claves["g_titular"])
        & (base["track_id"] == claves["g_track"])
        & (F.substring(base["inicio_utc"], 1, 10) == claves["g_fecha"])
        & (base["country"] == claves["g_pais_rep"]),
    ).select(
        "play_id",
        "user_id",
        "track_id",
        base["titular_id"].cast("string").alias("titular_id"),
        "pais_facturacion",
        "componente",
        "porcentaje",
        F.lit(str(liquidacion_id)).alias("liquidacion_id"),
        F.lit(periodo.isoformat()).alias("periodo"),
    )
    return SalidaGold(liquidacion_id, periodo, run_id, tuple(resultados), total), plays


def conciliar(silver, plays, periodo: date) -> dict:
    """Concilia por ``play_id`` las reproducciones pagables del período en Silver con las que
    Gold liquidó (condición 9 del ADR-0014, EG-31).

    Falla si Gold liquidó una reproducción que Silver no tiene como pagable, si dejó sin liquidar
    alguna que sí lo era, o si hay ``play_id`` repetidos en Gold. Devuelve los conteos.
    """
    from pyspark.sql import functions as F

    if "pagable_gold" in silver.columns or "estado_fraude" in silver.columns:
        from sonoraplay.spark.fraude import preparar_gold

        eligible = preparar_gold(silver, periodo)
    else:
        eligible = silver.filter(
            F.col("pagable") & (F.col("mes_liquidacion") == periodo.isoformat())
        )
    en_silver = eligible.select("play_id").distinct()
    en_gold = plays.select("play_id")
    n_silver, n_gold_filas = en_silver.count(), en_gold.count()
    n_gold = en_gold.distinct().count()
    faltan = en_silver.join(en_gold.distinct(), "play_id", "left_anti").limit(5).collect()
    sobran = en_gold.distinct().join(en_silver, "play_id", "left_anti").limit(5).collect()
    if n_gold_filas != n_gold:
        raise ValueError(f"Gold tiene {n_gold_filas - n_gold} play_id repetidos")
    if faltan or sobran:
        raise ValueError(
            "conciliación Silver ↔ Gold por play_id: "
            f"sin liquidar {[r['play_id'] for r in faltan]}, "
            f"liquidadas sin ser pagables {[r['play_id'] for r in sobran]}"
        )
    return {"silver_pagables": n_silver, "gold_liquidadas": n_gold}


def _con_componente_por_fecha(base, suscripciones):
    """Une cada reproducción con la suscripción vigente en su fecha UTC (``desde <= f < hasta``).

    Igual que ``plan_vigente`` del esqueleto: la propia del usuario gana (prioridad 0) sobre la
    del titular de su familia (prioridad 1); a igual prioridad, la que empezó antes.
    """
    from pyspark.sql import Window
    from pyspark.sql import functions as F

    sus = suscripciones.select(
        F.col("user_id").alias("s_user"),
        F.col("componente"),
        F.to_date("desde").alias("s_desde"),
        F.to_date("hasta").alias("s_hasta"),
        F.col("prioridad").alias("s_prio"),
    )
    fecha = F.to_date(F.substring(base["inicio_utc"], 1, 10))
    unido = base.join(
        sus,
        (base["user_id"] == sus["s_user"])
        & (fecha >= sus["s_desde"])
        & (sus["s_hasta"].isNull() | (fecha < sus["s_hasta"])),
        "left",
    )
    orden = Window.partitionBy("play_id").orderBy(
        F.col("s_prio").asc_nulls_last(), F.col("s_desde").asc_nulls_last()
    )
    return (
        unido.withColumn("_rn", F.row_number().over(orden))
        .filter(F.col("_rn") == 1)
        .drop("_rn", "s_user", "s_desde", "s_hasta", "s_prio")
    )


def _incidentes(con_pct) -> dict[str, list[Incidente]]:
    """Un incidente por reproducción afectada (como ``liquidar_pais``), por país de facturación."""
    por_pais: dict[str, list[Incidente]] = defaultdict(list)
    for r in con_pct.filter("incidente is not null").collect():
        for i in range(int(r["n"])):
            por_pais[r["pais_facturacion"]].append(
                Incidente(
                    tipo=TipoIncidente(r["incidente"]),
                    reproduccion_id=f"{r['track_id']}:{r['fecha']}:{i}",
                    titular_id=uuid.UUID(r["titular_id"]),
                    track_id=r["track_id"],
                    fecha=date.fromisoformat(r["fecha"]),
                    pais_reproduccion=r["pais_reproduccion"],
                    contrato_id=uuid.UUID(r["contrato_id"]) if r["contrato_id"] else None,
                )
            )
    return por_pais


# --- Carga a RDS (idempotente por run_id) ---------------------------------------------------


def cargar_rds(conexion, salida: SalidaGold) -> str:
    """Inserta la liquidación y sus filas en **una** transacción.

    - Primera vez: crea la liquidación sin publicar, sus filas, y al final pone ``publicada_en``.
    - Mismo ``run_id`` otra vez: no duplica nada. Si el resultado difiere de lo ya cargado, lanza
      ``ValueError`` (no sobrescribe: ADR-0007). Devuelve ``"creada"`` o ``"ya_existia"``.
    """
    filas = salida.filas
    if not filas:
        raise ValueError("una liquidación sin filas no se publica")
    with conexion.transaction():
        previa = conexion.execute(
            "SELECT publicada_en FROM liquidaciones WHERE liquidacion_id = %s",
            (salida.liquidacion_id,),
        ).fetchone()
        if previa is not None:
            existentes = {
                (str(r[0]), r[1], r[2], r[3], Decimal(r[4]), Decimal(r[5]))
                for r in conexion.execute(
                    "SELECT titular_id, pais, componente, reproducciones_validas, "
                    "porcentaje_contractual, regalia_usd FROM reporte_regalias "
                    "WHERE liquidacion_id = %s",
                    (salida.liquidacion_id,),
                )
            }
            nuevas = {
                (
                    str(f.titular_id),
                    f.pais,
                    str(f.componente),
                    f.reproducciones_validas,
                    f.porcentaje_contractual,
                    f.regalia_usd,
                )
                for f in filas
            }
            if existentes != nuevas:
                raise ValueError(
                    f"el run_id {salida.run_id!r} ya tiene la liquidación {salida.liquidacion_id} "
                    "con otro resultado; usa un run_id nuevo para crear una versión nueva"
                )
            return "ya_existia"
        conexion.execute(
            "INSERT INTO liquidaciones (liquidacion_id, periodo) VALUES (%s, %s)",
            (salida.liquidacion_id, salida.periodo),
        )
        with conexion.cursor() as cur:
            cur.executemany(
                "INSERT INTO reporte_regalias (liquidacion_id, titular_id, periodo, pais, "
                "componente, reproducciones_validas, participacion, porcentaje_contractual, "
                "regalia_usd) VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)",
                [
                    (
                        salida.liquidacion_id,
                        f.titular_id,
                        f.periodo,
                        f.pais,
                        str(f.componente),
                        f.reproducciones_validas,
                        f.participacion,
                        f.porcentaje_contractual,
                        f.regalia_usd,
                    )
                    for f in filas
                ],
            )
        conexion.execute(
            "UPDATE liquidaciones SET publicada_en = %s WHERE liquidacion_id = %s",
            (datetime.now(UTC), salida.liquidacion_id),
        )
    return "creada"


def escribir_gold(salida: SalidaGold, plays, destino: str) -> None:
    """Escribe en Gold las reproducciones liquidadas, particionadas por período, país y
    liquidación. Cada ``liquidacion_id`` es una partición nueva: nunca se sobrescribe otra."""
    (
        # dynamic: solo se reemplazan las particiones de ESTA liquidación (repetir el mismo
        # run_id es idempotente); con el modo estático se borraría todo el árbol (ADR-0007).
        plays.write.mode("overwrite")
        .option("partitionOverwriteMode", "dynamic")
        .partitionBy("periodo", "pais_facturacion", "liquidacion_id")
        .parquet(f"{destino}/plays_liquidados")
    )


# --- CLI -------------------------------------------------------------------------------------


def url_desde_entorno(env) -> str | None:
    """``DATABASE_URL`` o, en ECS, las variables ``DB_*`` que inyecta la tarea desde SSM."""
    if env.get("DATABASE_URL"):
        return env["DATABASE_URL"]
    faltan = [k for k in ("DB_HOST", "DB_NAME", "DB_USER", "DB_PASSWORD") if not env.get(k)]
    if faltan:
        return None
    from urllib.parse import quote

    return (
        f"postgresql://{quote(env['DB_USER'], safe='')}:{quote(env['DB_PASSWORD'], safe='')}"
        f"@{env['DB_HOST']}:{env.get('DB_PORT', '5432')}/{env['DB_NAME']}"
        f"?sslmode={env.get('DB_SSLMODE', 'require')}"
    )


def main(argv=None) -> int:
    """Job mensual: lee un run de Silver **verificado**, liquida y carga en RDS (idempotente).

    Código de salida 0 solo si Gold se escribió y la liquidación quedó publicada en RDS (o ya
    existía idéntica para el mismo ``--run-id``). Cualquier fallo sale con código ≠ 0.
    """
    import argparse
    import json
    import os

    parser = argparse.ArgumentParser(description="EG-37 liquidación mensual (Gold)")
    parser.add_argument("--periodo", required=True, help="Mes a liquidar, AAAA-MM")
    parser.add_argument("--silver-run-id", default=os.getenv("SONORAPLAY_SILVER_RUN_ID"))
    parser.add_argument("--run-id", default=os.getenv("SONORAPLAY_RUN_ID"))
    parser.add_argument("--silver", default=os.getenv("SONORAPLAY_SILVER_PATH"))
    parser.add_argument("--cuarentena", default=os.getenv("SONORAPLAY_QUARANTINE_PATH"))
    parser.add_argument("--gold", default=os.getenv("SONORAPLAY_GOLD_PATH"))
    parser.add_argument("--catalogo", default=os.getenv("SONORAPLAY_CATALOG_PATH"))
    parser.add_argument("--database-url", default=url_desde_entorno(os.environ))
    args = parser.parse_args(argv)
    try:
        anio, mes = args.periodo.split("-")
        periodo = date(int(anio), int(mes), 1)
        if f"{periodo:%Y-%m}" != args.periodo:
            raise ValueError("formato no canónico")
    except ValueError:
        parser.error("--periodo debe ser un mes válido AAAA-MM")
    for nombre in ("silver_run_id", "run_id", "silver", "cuarentena", "gold", "catalogo"):
        if not getattr(args, nombre):
            parser.error(f"--{nombre.replace('_', '-')} o su variable de entorno es obligatorio")
    if not args.database_url:
        parser.error("--database-url o DATABASE_URL es obligatorio")

    import psycopg
    from pyspark.sql import SparkSession

    from sonoraplay.spark.fraude import evaluar_fraude
    from sonoraplay.spark.gold_fuentes import leer_artistas_f1, leer_entradas
    from sonoraplay.spark.silver import read_verified_snapshot

    url = args.database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    spark = (
        SparkSession.builder.appName("sonoraplay-gold")
        .config("spark.sql.session.timeZone", "UTC")
        .getOrCreate()
    )
    silver, _cuarentena, marcador = read_verified_snapshot(
        spark, args.silver, args.cuarentena, args.silver_run_id
    )
    with psycopg.connect(url) as conexion:
        entradas = leer_entradas(conexion, periodo, args.catalogo)
        usuarios = spark.createDataFrame(
            entradas.usuarios, "user_id string, pais_facturacion string"
        )
        suscripciones = spark.createDataFrame(
            [
                (u, c, d.isoformat(), h.isoformat() if h else None, p)
                for u, c, d, h, p in entradas.suscripciones
            ],
            "user_id string, componente string, desde string, hasta string, prioridad int",
        )
        catalogo = spark.createDataFrame(entradas.catalogo, "track_id string, titular_id string")
        artistas = spark.createDataFrame(
            leer_artistas_f1(args.catalogo), "track_id string, artista_principal string"
        )
        # RN-03 runs before any Gold allocation; fail closed on incomplete F1/Silver.
        silver_fraude, senales_fraude = evaluar_fraude(silver, artistas)
        salida, plays = liquidar(
            spark,
            silver_fraude,
            usuarios,
            catalogo,
            entradas.condiciones,
            entradas.bolsas,
            periodo,
            args.run_id,
            suscripciones=suscripciones,
            fraude_verificado=True,
        )
        conciliacion = conciliar(silver_fraude, plays, periodo)
        escribir_gold(salida, plays, args.gold)
        estado = cargar_rds(conexion, salida)
    print(
        json.dumps(
            {
                "estado": estado,
                "liquidacion_id": str(salida.liquidacion_id),
                "periodo": args.periodo,
                "run_id": args.run_id,
                "silver_run_id": marcador["run_id"],
                "reproducciones_liquidadas": salida.reproducciones_liquidadas,
                "conciliacion": conciliacion,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
