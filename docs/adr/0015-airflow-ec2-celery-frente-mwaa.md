# ADR-0015 · Airflow en EC2 con CeleryExecutor y RabbitMQ, frente a MWAA

| Campo | Valor |
|---|---|
| Estado | **Propuesto** (pendiente de revisión por María Clara y Andrea) |
| Fecha | 2026-11-03 |
| Historia que lo origina | HU 25 · EG-34 |
| Responsable | Julián |
| Revisó | Pendiente |
| Referencias | Temas 11–12, RF-04, ADR-0001, ADR-0013, ADR-0020, EG-32 |

## 1. Contexto

Hace falta orquestar la ingesta diaria (EG-34) y la liquidación mensual del día 3 (EG-38). La arquitectura v1 ya reserva una EC2 `t4g.medium` para Airflow en la subred privada, con el Security Group `airflow` (sin entrada; se accede por túnel SSM) y una regla `airflow → rabbitmq:5672` para el broker de Celery. El entorno está apagado por defecto y se enciende solo en ventanas (ADR-0020).

## 2. Qué debe cumplir la decisión

- **Requisito (EG-34):** CeleryExecutor, al menos 2 workers en contenedores, RabbitMQ como broker.
- **Costo:** MWAA tiene un costo mínimo por hora del entorno que no se puede apagar entre ventanas sin destruirlo y recrearlo; con ventanas de ~3 h, la EC2 que ya está presupuestada es mucho más barata.
- **Operación:** `terraform destroy` debe dejar cero recursos (EG-47); una EC2 con `docker compose` se destruye con el resto.
- **Equipo:** el curso (temas 11–12) pide operar el executor y el broker, no consumirlos como servicio gestionado.

## 3. Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| **A · Airflow en EC2 con `docker compose`, CeleryExecutor + RabbitMQ (elegida)** | Cumple el criterio literal; costo = horas de la EC2 ya presupuestada; se destruye con Terraform; reutiliza el RabbitMQ del ADR-0013 | Hay que operar la actualización, los backups de metadatos y los workers |
| B · MWAA | Gestionado, sin mantenimiento | Cobra por hora de entorno aunque no haya DAGs; no cumple "workers en contenedores" propios; más difícil de apagar entre ventanas |
| C · LocalExecutor en una sola EC2 | Más simple | No cumple CeleryExecutor ni los 2 workers |

## 4. Decisión

Airflow 3.1 con **CeleryExecutor**, **2 workers** (`deploy.replicas: 2`), el RabbitMQ existente como broker en un **vhost propio `airflow`** (no mezcla colas con la mensajería F2) y una base PostgreSQL de metadatos independiente de la de la plataforma. Definición en `docker-compose.airflow.yml` y `docker/airflow/Dockerfile`; los DAG viven en `dags/` y la lógica de las tareas en `src/sonoraplay/orquestacion/` para probarla sin Airflow.

## 5. Consecuencias

- Los DAG son idempotentes por fecha lógica, así que un reintento o una corrida repetida no duplica datos.
- La tarea Bronze → Silver depende de `SILVER_JOB_COMMAND` (EG-35). Sin él, la tarea se **omite** con un mensaje explícito; no se finge éxito.
- Las versiones de Airflow se fijan con las restricciones oficiales y no con `uv.lock`; el CI importa los DAG en un job aparte.
- Los metadatos viven en un contenedor PostgreSQL en la misma EC2: se pierden con el `destroy`. Es aceptable porque los DAG y los datos de negocio están en el repositorio, en RDS y en S3.

## 6. Pendiente de comprobar

Este ADR no afirma que el stack haya corrido en AWS. Falta: levantar `docker-compose.airflow.yml` en la EC2 (ventana de pruebas), ver los dos workers registrados en Celery y forzar un fallo para observar los reintentos.
