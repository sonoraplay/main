"""EG-34 · Tareas del DAG diario: F6 diaria, datos de referencia y lanzamiento de Silver.

Cada función es **idempotente por fecha lógica**: repetir una corrida de la misma fecha
reescribe las mismas filas (``ON CONFLICT DO UPDATE``) y nunca las duplica.
"""

from __future__ import annotations

import os
import shlex
import subprocess
from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from sonoraplay.fuentes.eg30 import obtener_json
from sonoraplay.fuentes.f5_publicidad import generar_f5
from sonoraplay.fuentes.f6_tasas import FRANKFURTER, MONEDAS, validar_tasas_diarias
from sonoraplay.fuentes.f7_paises import REST_COUNTRIES, validar_paises
from sonoraplay.fuentes.persistencia import guardar_fuentes

# Frankfurter no publica fines de semana ni festivos: se pide una semana hacia atrás para que
# un lunes (o un día 1 festivo) siempre traiga al menos una cotización por moneda.
VENTANA_F6_DIAS = 6
VARIABLE_COMANDO_SILVER = "SILVER_JOB_COMMAND"
SEMILLA_F5 = 2026

Obtener = Callable[[str], object]


class SilverNoConfigurado(Exception):
    """El job Bronze → Silver (EG-35) todavía no está conectado a este DAG."""


def a_fecha(valor: str | date) -> date:
    return valor if isinstance(valor, date) else date.fromisoformat(valor)


def fecha_procesada(logical_date: datetime | date) -> date:
    """Día UTC cerrado que procesa la corrida: la de las 02:00 del día D procesa D-1 (ADR-0002)."""
    dia = logical_date.date() if isinstance(logical_date, datetime) else logical_date
    return dia - timedelta(days=1)


def conexion_postgres(database_url: str | None = None):
    import psycopg

    url = database_url or os.environ["DATABASE_URL"]
    return psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1))


def cargar_f6_diaria(
    fecha: str | date, conexion, obtener: Obtener = obtener_json, ventana: int = VENTANA_F6_DIAS
) -> int:
    """Descarga las cotizaciones de ``fecha`` (y la semana previa) y las upserta. Devuelve filas."""
    cierre = a_fecha(fecha)
    inicio = cierre - timedelta(days=ventana)
    rango = f"from={inicio.isoformat()}&to={cierre.isoformat()}"
    url = f"{FRANKFURTER}?{rango}&base=USD&quotes={','.join(MONEDAS)}"
    filas = validar_tasas_diarias(obtener(url), MONEDAS, inicio, cierre)
    instante = datetime.now(UTC)
    with conexion.transaction(), conexion.cursor() as cursor:
        for fila in filas:
            cursor.execute(
                """INSERT INTO fuente_f6_tasas_diarias
                   (moneda, fecha_observacion, unidades_por_usd, proveedor, extraido_en_utc)
                   VALUES (%s, %s, %s, %s, %s)
                   ON CONFLICT (moneda, fecha_observacion) DO UPDATE
                   SET unidades_por_usd=EXCLUDED.unidades_por_usd,
                       proveedor=EXCLUDED.proveedor,
                       extraido_en_utc=EXCLUDED.extraido_en_utc""",
                (
                    fila["moneda"],
                    date.fromisoformat(fila["fecha"]),
                    Decimal(fila["unidades_por_usd"]),
                    fila["proveedor"],
                    instante,
                ),
            )
    return len(filas)


def refrescar_referencia(
    fecha: str | date, conexion, obtener: Obtener = obtener_json, semilla: int = SEMILLA_F5
) -> dict[str, int]:
    """Refresca F7 (países) y F5 (publicidad) del mes de ``fecha``, en una transacción."""
    dia = a_fecha(fecha)
    mes = f"{dia.year:04d}-{dia.month:02d}"
    paises = validar_paises(obtener(REST_COUNTRIES))
    publicidad = generar_f5(mes, paises, semilla)
    guardar_fuentes(
        conexion,
        mes=mes,
        paises=paises,
        tasas_cierre=[],
        tasas_diarias=[],
        publicidad=publicidad,
    )
    return {"paises": len(paises), "publicidad": len(publicidad)}


def lanzar_silver(
    fecha: str | date, entorno: dict[str, str] | None = None, run_id: str = ""
) -> int:
    """Lanza el job Bronze → Silver de ``fecha`` con el comando de ``SILVER_JOB_COMMAND``.

    Contrato con EG-35: el comando recibe ``{fecha}`` (AAAA-MM-DD, UTC, el día cerrado que se
    procesa) y ``{run_id}`` (ID de la corrida de Airflow, para el linaje). Repetir la misma fecha
    no debe duplicar ni fallar; cómo lo logra Silver (reconstruir el mes hasta la fecha) lo
    decide el job, no el DAG. Sin comando configurado lanza ``SilverNoConfigurado``:
    la integración no existe aún y no se finge.
    """
    env = os.environ if entorno is None else entorno
    plantilla = env.get(VARIABLE_COMANDO_SILVER, "").strip()
    if not plantilla:
        raise SilverNoConfigurado(
            f"{VARIABLE_COMANDO_SILVER} sin definir: el job Spark Bronze → Silver (EG-35) "
            "todavía no está conectado."
        )
    dia = a_fecha(fecha).isoformat()
    comando = [
        parte.replace("{fecha}", dia).replace("{run_id}", run_id)
        for parte in shlex.split(plantilla)
    ]
    return subprocess.run(comando, check=True).returncode
