"""EG-30: carga de F5, F6 y F7 en PostgreSQL en una sola transacción.

Todo entra o nada entra: si una fila falla, PostgreSQL deshace la carga completa.
Las llaves primarias y el UPSERT hacen que repetir la carga no duplique filas.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from sqlalchemy import Connection, Engine, MetaData, Table, func, select
from sqlalchemy.dialects.postgresql import insert

TABLAS = ("paises", "tasas_cambio", "ingresos_publicidad")


def _upsert(conn: Connection, tabla: Table, filas: list[dict], llave: tuple[str, ...]) -> None:
    if not filas:
        return
    stmt = insert(tabla)
    cambios = {c: stmt.excluded[c] for c in filas[0] if c not in llave}
    cambios["actualizado_en"] = func.now()
    conn.execute(stmt.on_conflict_do_update(index_elements=list(llave), set_=cambios), filas)


def filas_tasas(cierre: list[dict], diarias: list[dict] | None) -> list[dict]:
    """Convierte las tasas validadas de F6 al formato de `tasas_cambio`."""
    filas = [
        {
            "moneda": t["moneda"],
            "fecha": date.fromisoformat(t["fecha"]),
            "tipo": "cierre",
            "unidades_por_usd": Decimal(t["unidades_por_usd"]),
            "fecha_observacion": date.fromisoformat(t["fecha_observacion"]),
            "proveedor": t["proveedor"],
        }
        for t in cierre
    ]
    filas += [
        {
            "moneda": t["moneda"],
            "fecha": date.fromisoformat(t["fecha"]),
            "tipo": "diaria",
            "unidades_por_usd": Decimal(t["unidades_por_usd"]),
            "fecha_observacion": date.fromisoformat(t["fecha"]),
            "proveedor": t["proveedor"],
        }
        for t in diarias or []
    ]
    return filas


def filas_publicidad(f5: list[dict], semilla: int) -> list[dict]:
    """Convierte las filas del CSV F5 al formato de `ingresos_publicidad`."""
    return [
        {
            "periodo": date.fromisoformat(f["mes"] + "-01"),
            "pais": f["pais"],
            "moneda": f["moneda"],
            "ingresos": Decimal(f["ingresos_publicidad"]),
            "semilla": semilla,
        }
        for f in f5
    ]


def cargar(
    engine: Engine,
    paises: list[dict],
    tasas_cierre: list[dict],
    tasas_diarias: list[dict] | None,
    f5: list[dict],
    semilla: int,
) -> dict[str, int]:
    """Carga F7, F6 y F5 en una transacción y devuelve los conteos de cada tabla."""
    md = MetaData()
    with engine.begin() as conn:
        t = {n: Table(n, md, autoload_with=conn) for n in TABLAS}
        _upsert(
            conn,
            t["paises"],
            [{"pais": p["pais"], "region": p["region"], "monedas": p["monedas"]} for p in paises],
            ("pais",),
        )
        _upsert(
            conn,
            t["tasas_cambio"],
            filas_tasas(tasas_cierre, tasas_diarias),
            ("moneda", "fecha", "tipo"),
        )
        _upsert(conn, t["ingresos_publicidad"], filas_publicidad(f5, semilla), ("periodo", "pais"))
        return {n: conn.scalar(select(func.count()).select_from(t[n])) for n in TABLAS}
