"""EG-38 · Tareas del DAG mensual: esperar la ingesta, liquidar una versión nueva, medir.

La liquidación es append-only (ADR-0007): cada corrida del mismo mes debe crear una
``liquidacion`` nueva y dejar intactas las anteriores. Aquí se **verifica** esa propiedad
después del job; el cálculo lo hace el job de liquidación (EG-37), no este módulo.
"""

from __future__ import annotations

import calendar
import logging
import os
import shlex
import subprocess
import time
from datetime import UTC, date, datetime, timedelta

log = logging.getLogger(__name__)

VARIABLE_COMANDO = "LIQUIDACION_JOB_COMMAND"
VARIABLE_SNS = "ALERTA_SNS_TOPIC_ARN"
META_SEGUNDOS = 3600  # RNF-01
# RN-04 / ADR-0007: lo sincronizado hasta el día 2 (23:59 UTC) aún entra en el mes anterior.
DIAS_DE_GRACIA = 2


class LiquidacionNoConfigurada(Exception):
    """El job de liquidación en Spark (EG-37) todavía no está conectado a este DAG."""


class SilverRunIdFaltante(Exception):
    """No hay un run de Silver verificado para liquidar el periodo."""


class VersionNoCreada(Exception):
    """El job terminó pero no dejó exactamente una liquidación nueva publicada."""


def periodo_a_liquidar(logical_date: datetime | date) -> date:
    """Primer día del mes anterior a la fecha lógica: el día 3 de noviembre liquida octubre."""
    dia = logical_date.date() if isinstance(logical_date, datetime) else logical_date
    ultimo_del_anterior = dia.replace(day=1) - timedelta(days=1)
    return ultimo_del_anterior.replace(day=1)


def fechas_requeridas(periodo: date) -> list[date]:
    """Días cuya ingesta debe estar completa: todo el mes y los días de gracia siguientes."""
    n = calendar.monthrange(periodo.year, periodo.month)[1]
    return [periodo + timedelta(days=i) for i in range(n + DIAS_DE_GRACIA)]


def ingesta_pendiente(conexion, periodo: date) -> list[date]:
    requeridas = fechas_requeridas(periodo)
    hechas = {
        fila[0]
        for fila in conexion.execute(
            "SELECT fecha FROM ingesta_diaria_estado WHERE fecha BETWEEN %s AND %s",
            (requeridas[0], requeridas[-1]),
        )
    }
    return [d for d in requeridas if d not in hechas]


def ingesta_completa(conexion, periodo: date) -> bool:
    faltan = ingesta_pendiente(conexion, periodo)
    if faltan:
        log.info("Ingesta pendiente para %s: %s", periodo, ", ".join(d.isoformat() for d in faltan))
    return not faltan


def marcar_ingesta(conexion, fecha: date, run_id: str, silver_run_id: str | None = None) -> None:
    """Idempotente: repetir el día solo refresca ``completada_en`` y el ``silver_run_id``."""
    with conexion.transaction():
        conexion.execute(
            """INSERT INTO ingesta_diaria_estado (fecha, run_id, silver_run_id)
               VALUES (%s, %s, %s)
               ON CONFLICT (fecha) DO UPDATE
               SET completada_en = now(), run_id = EXCLUDED.run_id,
                   silver_run_id = EXCLUDED.silver_run_id""",
            (fecha, run_id, silver_run_id),
        )


def silver_run_id_del_periodo(conexion, periodo: date) -> str | None:
    """Run de Silver verificado del último día requerido (el que contiene todo el mes + gracia)."""
    ultimo = fechas_requeridas(periodo)[-1]
    fila = conexion.execute(
        "SELECT silver_run_id FROM ingesta_diaria_estado WHERE fecha = %s", (ultimo,)
    ).fetchone()
    return fila[0] if fila else None


def _versiones(conexion, periodo: date) -> set:
    return {
        fila[0]
        for fila in conexion.execute(
            "SELECT liquidacion_id FROM liquidaciones "
            "WHERE periodo = %s AND publicada_en IS NOT NULL",
            (periodo,),
        )
    }


def liquidar(
    periodo: date,
    conexion,
    run_id: str,
    entorno: dict[str, str] | None = None,
    reloj=time.monotonic,
    silver_run_id: str | None = None,
) -> dict:
    """Corre el job de ``periodo``, verifica la versión nueva y registra la duración."""
    env = os.environ if entorno is None else entorno
    plantilla = env.get(VARIABLE_COMANDO, "").strip()
    if not plantilla:
        raise LiquidacionNoConfigurada(
            f"{VARIABLE_COMANDO} sin definir: el job de liquidación en Spark (EG-37) "
            "todavía no está conectado."
        )
    mes = f"{periodo.year:04d}-{periodo.month:02d}"
    if "{silver_run_id}" in plantilla and not silver_run_id:
        raise SilverRunIdFaltante(
            f"{mes}: el comando pide {{silver_run_id}} pero el último día requerido "
            "no tiene un run de Silver verificado en ingesta_diaria_estado."
        )
    comando = [
        p.replace("{periodo}", mes).replace("{silver_run_id}", silver_run_id or "")
        for p in shlex.split(plantilla)
    ]
    antes = _versiones(conexion, periodo)
    inicio = datetime.now(UTC)
    t0 = reloj()
    corrida = conexion.execute(
        """INSERT INTO corridas_liquidacion (periodo, run_id, inicio_utc, estado)
           VALUES (%s, %s, %s, 'en_curso') RETURNING corrida_id""",
        (periodo, run_id, inicio),
    ).fetchone()[0]
    conexion.commit()
    estado, detalle, nueva = "ok", None, None
    try:
        subprocess.run(comando, check=True)
        despues = _versiones(conexion, periodo)
        creadas = despues - antes
        if not antes <= despues or len(creadas) != 1:
            raise VersionNoCreada(
                f"{mes}: se esperaba 1 liquidación nueva y las anteriores intactas; "
                f"antes={len(antes)}, después={len(despues)}, nuevas={len(creadas)}"
            )
        nueva = next(iter(creadas))
    except Exception as exc:
        estado, detalle = "error", f"{type(exc).__name__}: {exc}"
        raise
    finally:
        duracion = reloj() - t0
        conexion.rollback()
        conexion.execute(
            """UPDATE corridas_liquidacion
               SET fin_utc = now(), duracion_s = %s, estado = %s, liquidacion_id = %s, detalle = %s
               WHERE corrida_id = %s""",
            (round(duracion, 3), estado, nueva, detalle, corrida),
        )
        conexion.commit()
        log.info(
            "Liquidación %s: %s en %.1f s (meta %d s, RNF-01: %s)",
            mes,
            estado,
            duracion,
            META_SEGUNDOS,
            "cumple" if duracion < META_SEGUNDOS else "NO cumple",
        )
    return {
        "periodo": mes,
        "liquidacion_id": str(nueva),
        "duracion_s": round(duracion, 3),
        "cumple_rnf01": duracion < META_SEGUNDOS,
    }


def mensaje_de_fallo(dag_id: str, task_id: str, run_id: str, error: object) -> str:
    return f"[SonoraPlay] Falló {dag_id}.{task_id} (run {run_id}) tras agotar reintentos: {error}"


def notificar_fallo(contexto: dict, entorno: dict[str, str] | None = None, cliente=None) -> str:
    """Registra el fallo final y, si hay tema SNS configurado, avisa por correo."""
    env = os.environ if entorno is None else entorno
    ti = contexto.get("task_instance")
    texto = mensaje_de_fallo(
        getattr(ti, "dag_id", contexto.get("dag_id", "?")),
        getattr(ti, "task_id", contexto.get("task_id", "?")),
        contexto.get("run_id", "?"),
        contexto.get("exception", "sin detalle"),
    )
    log.error(texto)
    topico = env.get(VARIABLE_SNS, "").strip()
    if topico:
        if cliente is None:
            import boto3

            cliente = boto3.client("sns")
        cliente.publish(TopicArn=topico, Subject="SonoraPlay: fallo de liquidación", Message=texto)
    return texto
