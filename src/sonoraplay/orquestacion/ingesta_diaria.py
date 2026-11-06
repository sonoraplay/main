"""EG-34 · Tareas del DAG diario: F6 diaria, datos de referencia y lanzamiento de Silver.

Cada función es **idempotente por fecha lógica**: repetir una corrida de la misma fecha
reescribe las mismas filas (``ON CONFLICT DO UPDATE``) y nunca las duplica.
"""

from __future__ import annotations

import json
import os
import re
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
VARIABLE_COMMITS_SILVER = "SILVER_COMMITS_URI"  # p. ej. s3://bucket/silver/commits
ESQUEMA_COMMIT_SILVER = "eg35-commit-v1"

Obtener = Callable[[str], object]


class SilverNoConfigurado(Exception):
    """El job Bronze → Silver (EG-35) todavía no está conectado a este DAG."""


class SilverNoPublicado(Exception):
    """Silver terminó pero no hay un marcador de commit válido para este intento."""


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


def run_id_silver(run_id_airflow: str, intento: int) -> str:
    """ID de intento para Silver: ``<run_id de Airflow saneado>.<nº de intento>``.

    Un intento nuevo usa siempre un prefijo nuevo (``runs/<id>`` es inmutable y no se
    sobrescribe); cumple ``[A-Za-z0-9][A-Za-z0-9_.-]{0,127}``.
    """
    base = re.sub(r"[^A-Za-z0-9_.-]", "-", run_id_airflow).lstrip("._-") or "run"
    sufijo = f".{int(intento)}"
    return base[: 128 - len(sufijo)] + sufijo


def leer_marcador_s3(uri_commits: str, run_id: str) -> dict:
    import boto3

    bucket, _, prefijo = uri_commits.removeprefix("s3://").partition("/")
    clave = f"{prefijo.rstrip('/')}/{run_id}.json"
    cuerpo = boto3.client("s3").get_object(Bucket=bucket, Key=clave)["Body"].read()
    return json.loads(cuerpo)


def leer_marcador(ubicacion: str, run_id: str) -> dict:
    """Lee ``commits/<run_id>.json`` de S3 (``s3://...``) o de un directorio local (pruebas)."""
    if ubicacion.startswith("s3://"):
        return leer_marcador_s3(ubicacion, run_id)
    from pathlib import Path

    return json.loads((Path(ubicacion) / f"{run_id}.json").read_text(encoding="utf-8"))


def verificar_silver_publicado(
    fecha: str | date,
    run_id: str,
    entorno: dict[str, str] | None = None,
    leer: Callable[[str, str], dict] = leer_marcador,
) -> dict:
    """Exige el marcador ``commits/<run_id>.json`` de EG-35 antes de dar el día por ingerido.

    Sin marcador, con otro ``run_id``/``fecha`` o sin filas, falla cerrado: el día no se marca.
    """
    env = os.environ if entorno is None else entorno
    uri = env.get(VARIABLE_COMMITS_SILVER, "").strip()
    if not uri:
        raise SilverNoConfigurado(f"{VARIABLE_COMMITS_SILVER} sin definir: no se puede verificar.")
    try:
        marca = leer(uri, run_id)
    except Exception as exc:
        raise SilverNoPublicado(f"Sin marcador de commit para {run_id}: {exc}") from exc
    esperado = {
        "schema_version": ESQUEMA_COMMIT_SILVER,
        "run_id": run_id,
        "fecha": a_fecha(fecha).isoformat(),
    }
    for campo, valor in esperado.items():
        if marca.get(campo) != valor:
            raise SilverNoPublicado(f"Marcador inválido: {campo}={marca.get(campo)!r} ≠ {valor!r}")
    filas = marca.get("silver_rows")
    if not isinstance(filas, int) or filas <= 0:
        raise SilverNoPublicado(f"Marcador inválido: silver_rows={filas!r}")
    return marca
