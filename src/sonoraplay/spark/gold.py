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
):
    """Liquida ``periodo``. Devuelve ``(SalidaGold, plays_liquidados: DataFrame)``.

    - ``silver``: salida de la EG-35 (``play_id, user_id, track_id, country, inicio_utc,
      mes_liquidacion, pagable``).
    - ``usuarios``: ``user_id, pais_facturacion, componente`` (F3: Q6, RN-10, Q8).
    - ``catalogo``: ``track_id, titular_id`` (F1).
    - ``bolsas``: una ``BolsaPais`` por país a liquidar.
    """
    from pyspark.sql import functions as F
    from pyspark.sql.types import LongType, StringType, StructField, StructType

    if periodo.day != 1:
        raise ValueError("periodo debe ser el primer día del mes")
    liquidacion_id = liquidacion_id_de(run_id, periodo)
    bolsas_por_pais = {b.pais: b for b in bolsas}
    indice = indexar_condiciones(condiciones)

    base = (
        silver.filter(F.col("pagable") & (F.col("mes_liquidacion") == periodo.isoformat()))
        .join(usuarios.select("user_id", "pais_facturacion", "componente"), "user_id", "left")
        .join(catalogo.select("track_id", "titular_id"), "track_id", "left")
        .cache()
    )
    huerfanas = base.filter(
        F.col("pais_facturacion").isNull() | F.col("titular_id").isNull()
    ).count()
    if huerfanas:
        base.unpersist()
        raise ValueError(
            f"{huerfanas} reproducciones pagables sin país de facturación o sin titular: "
            "no se inventa ninguno; se corrige en F3/F1 y se vuelve a correr"
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
        plays.write.mode("overwrite")
        .partitionBy("periodo", "pais_facturacion", "liquidacion_id")
        .parquet(f"{destino}/plays_liquidados")
    )
