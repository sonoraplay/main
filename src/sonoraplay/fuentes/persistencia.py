"""EG-30: transactional, idempotent PostgreSQL persistence for validated sources.

Call this only after all remote responses have been fetched and validated.
No database credentials are stored in the repository.
"""

from datetime import UTC, date, datetime
from decimal import Decimal

from psycopg import Connection


def guardar_fuentes(
    conexion: Connection,
    *,
    mes: str,
    paises: list[dict],
    tasas_cierre: list[dict],
    tasas_diarias: list[dict],
    publicidad: list[dict],
) -> None:
    """Upsert one monthly batch atomically; a failure rolls back all changes."""
    periodo = date.fromisoformat(f"{mes}-01")
    if len({p["pais"] for p in paises}) != len(paises) or len(paises) < 200:
        raise ValueError("F7 requiere al menos 200 países únicos")
    if len({t["moneda"] for t in tasas_cierre}) != len(tasas_cierre):
        raise ValueError("F6 contiene monedas de cierre duplicadas")
    if len({(t["moneda"], t["fecha"]) for t in tasas_diarias}) != len(tasas_diarias):
        raise ValueError("F6 contiene tasas diarias duplicadas")
    if len({f["pais"] for f in publicidad}) != len(publicidad):
        raise ValueError("F5 contiene países duplicados")
    instante = datetime.now(UTC)
    with conexion.transaction():
        with conexion.cursor() as cursor:
            for p in paises:
                cursor.execute(
                    """INSERT INTO fuente_f7_paises(pais, region, monedas)
                       VALUES (%s, %s, %s)
                       ON CONFLICT (pais) DO UPDATE
                       SET region=EXCLUDED.region, monedas=EXCLUDED.monedas,
                           actualizado_en=now()""",
                    (p["pais"], p["region"], p["monedas"]),
                )
            for t in tasas_diarias:
                cursor.execute(
                    """INSERT INTO fuente_f6_tasas_diarias
                       (moneda, fecha_observacion, unidades_por_usd, proveedor, extraido_en_utc)
                       VALUES (%s, %s, %s, %s, %s)
                       ON CONFLICT (moneda, fecha_observacion) DO UPDATE
                       SET unidades_por_usd=EXCLUDED.unidades_por_usd,
                           proveedor=EXCLUDED.proveedor,
                           extraido_en_utc=EXCLUDED.extraido_en_utc""",
                    (
                        t["moneda"],
                        date.fromisoformat(t["fecha"]),
                        Decimal(t["unidades_por_usd"]),
                        t["proveedor"],
                        instante,
                    ),
                )
            for t in tasas_cierre:
                cursor.execute(
                    """INSERT INTO fuente_f6_cierres
                       (moneda, fecha_cierre, fecha_observacion, unidades_por_usd,
                        proveedor, extraido_en_utc)
                       VALUES (%s, %s, %s, %s, %s, %s)
                       ON CONFLICT (moneda, fecha_cierre) DO UPDATE
                       SET fecha_observacion=EXCLUDED.fecha_observacion,
                           unidades_por_usd=EXCLUDED.unidades_por_usd,
                           proveedor=EXCLUDED.proveedor,
                           extraido_en_utc=EXCLUDED.extraido_en_utc""",
                    (
                        t["moneda"],
                        date.fromisoformat(t["fecha"]),
                        date.fromisoformat(t["fecha_observacion"]),
                        Decimal(t["unidades_por_usd"]),
                        t["proveedor"],
                        instante,
                    ),
                )
            for f in publicidad:
                cursor.execute(
                    """INSERT INTO fuente_f5_publicidad
                       (mes, pais, moneda, ingresos_publicidad)
                       VALUES (%s, %s, %s, %s)
                       ON CONFLICT (mes, pais) DO UPDATE
                       SET moneda=EXCLUDED.moneda,
                           ingresos_publicidad=EXCLUDED.ingresos_publicidad""",
                    (
                        periodo,
                        f["pais"],
                        f["moneda"],
                        Decimal(f["ingresos_publicidad"]),
                    ),
                )
