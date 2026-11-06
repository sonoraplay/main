"""EG-37/EG-34 · Lanza un job de Spark como tarea de ECS Fargate y espera su resultado.

Airflow no ejecuta Spark en su propia máquina: ``SILVER_JOB_COMMAND`` y
``LIQUIDACION_JOB_COMMAND`` apuntan a este módulo, que hace ``RunTask`` sobre la definición
``<proyecto>-<entorno>-spark`` (spark.tf) con el comando del job, espera a que la tarea termine y
sale con código 0 **solo si el contenedor salió con 0**. Cualquier otra cosa (no arrancó, se
detuvo, venció el plazo, salió con error) sale con código ≠ 0 para que Airflow reintente.

Ejemplo de ``SILVER_JOB_COMMAND``::

    python -m sonoraplay.orquestacion.ecs_job -- python -m sonoraplay.spark.silver \\
        --fecha {fecha} --run-id {run_id} --bronze s3a://<bronze>/f2 --catalogo s3a://<...> \\
        --silver s3a://<bucket-silver> --cuarentena s3a://<bucket-silver>/quarantine \\
        --source-version <sha>

Configuración por variables de entorno: ``ECS_CLUSTER``, ``ECS_SPARK_FAMILY``, ``ECS_SUBNETS``
y ``ECS_SECURITY_GROUPS`` (listas separadas por comas), ``ECS_JOB_TIMEOUT_S`` (opcional).
"""

from __future__ import annotations

import os
import sys

CONTENEDOR = "spark"
PLAZO_POR_DEFECTO_S = 3 * 3600
ESPERA_S = 20


class EcsJobFallo(Exception):
    """La tarea de ECS no terminó bien."""


def _lista(valor: str) -> list[str]:
    return [p.strip() for p in valor.split(",") if p.strip()]


def ejecutar_job(
    cliente,
    *,
    cluster: str,
    familia: str,
    subredes: list[str],
    security_groups: list[str],
    comando: list[str],
    plazo_s: int = PLAZO_POR_DEFECTO_S,
    espera_s: int = ESPERA_S,
) -> str:
    """Lanza ``comando`` en la tarea, espera y devuelve el ARN. Lanza ``EcsJobFallo`` si falla."""
    if not comando:
        raise ValueError("falta el comando del job")
    if not subredes or not security_groups:
        raise ValueError("ECS_SUBNETS y ECS_SECURITY_GROUPS son obligatorios")
    r = cliente.run_task(
        cluster=cluster,
        taskDefinition=familia,
        count=1,
        networkConfiguration={
            "awsvpcConfiguration": {
                "subnets": subredes,
                "securityGroups": security_groups,
                "assignPublicIp": "DISABLED",
            }
        },
        overrides={"containerOverrides": [{"name": CONTENEDOR, "command": comando}]},
    )
    if r.get("failures") or not r.get("tasks"):
        raise EcsJobFallo(f"RunTask no arrancó la tarea: {r.get('failures')}")
    arn = r["tasks"][0]["taskArn"]
    print(f"Tarea de ECS lanzada: {arn}", flush=True)
    try:
        cliente.get_waiter("tasks_stopped").wait(
            cluster=cluster,
            tasks=[arn],
            WaiterConfig={"Delay": espera_s, "MaxAttempts": max(1, plazo_s // espera_s)},
        )
    except Exception as exc:
        # Plazo vencido o error del waiter: no se deja una tarea huérfana cobrando.
        cliente.stop_task(cluster=cluster, task=arn, reason="plazo del job vencido")
        raise EcsJobFallo(f"la tarea {arn} no terminó a tiempo: {exc}") from exc
    tarea = cliente.describe_tasks(cluster=cluster, tasks=[arn])["tasks"][0]
    contenedor = next((c for c in tarea.get("containers", []) if c["name"] == CONTENEDOR), None)
    codigo = None if contenedor is None else contenedor.get("exitCode")
    if codigo != 0:
        raise EcsJobFallo(
            f"la tarea {arn} terminó con exitCode={codigo!r}; "
            f"motivo: {tarea.get('stoppedReason') or (contenedor or {}).get('reason')}"
        )
    return arn


def main(argv: list[str] | None = None, entorno=None, cliente=None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    env = os.environ if entorno is None else entorno
    if "--" not in argv or not argv[argv.index("--") + 1 :]:
        print(
            "uso: python -m sonoraplay.orquestacion.ecs_job -- <comando del job>", file=sys.stderr
        )
        return 2
    comando = argv[argv.index("--") + 1 :]
    faltan = [v for v in ("ECS_CLUSTER", "ECS_SPARK_FAMILY") if not env.get(v)]
    if faltan:
        print(f"Faltan variables: {', '.join(faltan)}", file=sys.stderr)
        return 2
    if cliente is None:
        import boto3

        cliente = boto3.client("ecs")
    try:
        ejecutar_job(
            cliente,
            cluster=env["ECS_CLUSTER"],
            familia=env["ECS_SPARK_FAMILY"],
            subredes=_lista(env.get("ECS_SUBNETS", "")),
            security_groups=_lista(env.get("ECS_SECURITY_GROUPS", "")),
            comando=comando,
            plazo_s=int(env.get("ECS_JOB_TIMEOUT_S", PLAZO_POR_DEFECTO_S)),
        )
    except (EcsJobFallo, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
