# Orquestación con Airflow (EG-34 y EG-38)

Airflow 3.1 con **CeleryExecutor**, 2 workers y RabbitMQ como broker ([ADR-0015](../adr/0015-airflow-ec2-celery-frente-mwaa.md)).
Stack: `docker-compose.airflow.yml`. La lógica de cada tarea está en `src/sonoraplay/orquestacion/` (se prueba sin Airflow); `dags/` solo la cablea.

```bash
docker compose -f docker-compose.yml -f docker-compose.airflow.yml up -d --build
```

## DAG diario · `sonoraplay_ingesta_diaria` (EG-34)

Corre a las 02:00 UTC y procesa el **día UTC anterior ya cerrado** (ADR-0002).

| Tarea | Qué hace | Idempotencia |
|---|---|---|
| `cargar_tasas_f6` | Descarga las cotizaciones F6 de la semana que termina en el día procesado y las upserta | `ON CONFLICT (moneda, fecha_observacion)` |
| `refrescar_referencia` | Refresca F7 (países) y F5 (publicidad) del mes en una transacción | upsert por país / (mes, país) |
| `spark_bronze_a_silver` | Ejecuta `SILVER_JOB_COMMAND` con `{fecha}` y `{run_id}` | repetir la fecha no debe duplicar ni fallar. María Clara lo resolverá reconstruyendo el mes hasta la fecha, sin `dynamic overwrite` sobre un lote de un solo día (comentario en el PR #38) |
| `verificar_silver_publicado` | Lee `commits/<run_id>.json` (`SILVER_COMMITS_URI`) y exige `schema_version=eg35-commit-v1`, `run_id` y `fecha` iguales y `silver_rows > 0` | sin marcador válido falla y el día **no** se marca; el `run_id` de Silver es `<run_id de Airflow saneado>.<intento>`: un intento nuevo usa siempre un prefijo nuevo |
| `marcar_ingesta_completa` | Anota el día en `ingesta_diaria_estado` | upsert por fecha |

Reintentos: 2, con 5 min de espera y retroceso exponencial.

## DAG mensual · `sonoraplay_liquidacion_mensual` (EG-38)

Corre el **día 3 a las 06:00 UTC** y liquida el mes anterior.

| Tarea | Qué hace |
|---|---|
| `esperar_ingesta_diaria` | Sensor (modo `reschedule`, cada 15 min, tope 12 h) hasta que `ingesta_diaria_estado` tenga todo el mes **más los 2 días de gracia** de RN-04 |
| `liquidar_mes` | Ejecuta `LIQUIDACION_JOB_COMMAND` con `{periodo}` (AAAA-MM), exige **exactamente una liquidación publicada nueva** con las anteriores intactas (ADR-0007) y registra la duración en `corridas_liquidacion` frente a la meta de 3 600 s (RNF-01) |

Reintentos: 2 con 10 min. Al agotarlos, `on_failure_callback` deja el error en el log y publica en el tema SNS `ALERTA_SNS_TOPIC_ARN` si está definido.

## Contratos con trabajo que aún no existe

| Variable | Dueño | Contrato | Sin definir |
|---|---|---|---|
| `SILVER_JOB_COMMAND` | EG-35 | Recibe `{fecha}` (día UTC cerrado) y `{run_id}`; el job reconstruye el mes hasta esa fecha. Pendiente en su PR (#38): `--fecha`, idempotencia, publicación segura en S3 y pruebas de reproceso | La tarea queda **omitida** y el día **no** se marca como ingerido |
| `LIQUIDACION_JOB_COMMAND` | EG-37 | Recibe `{periodo}`; crea una `liquidaciones` nueva y la publica (`publicada_en`) | La tarea queda **omitida** |

El `run_id` de Silver verificado de cada día se guarda en `ingesta_diaria_estado.silver_run_id`; la liquidación mensual toma el del último día requerido y lo pasa al job como `{silver_run_id}` (EG-37 lo lee con `read_verified_snapshot`). Preguntas abiertas para María Clara en el PR #38: retención de `runs/`, semántica de `fecha` y cuándo se habilita `main`.

Mientras falte `SILVER_JOB_COMMAND`, el sensor mensual no se cumple: es el comportamiento buscado, para no liquidar con días sin procesar.

## Qué está probado y qué no

- Probado en CI/local: importación de todos los DAG (DagBag), reintentos ≥ 2, idempotencia de F6 y referencia contra PostgreSQL, espera de ingesta, versión nueva por corrida, registro de duración, aviso de fallo (SNS simulado).
- **Probado con Airflow 3.1.3 real (2026-11-07, ejecutor local, sin Celery ni RabbitMQ; Silver y la liquidación simulados con `pruebas/airflow-local/`)**, ejecutando los DAG verdaderos con `dag.test()` contra PostgreSQL (`pruebas/airflow-local/dags_local.py`):
  - **Diario, ejecución normal:** las 5 tareas en `success`; `silver_run_id` = `<run_id de Airflow saneado>.<intento>` y una fila en `ingesta_diaria_estado`.
  - **Diario, misma fecha otra vez:** sigue habiendo una sola fila por fecha; su `silver_run_id` se actualiza.
  - **Diario, Silver sale con 0 pero no deja marcador:** `verificar_silver_publicado` falla, reintenta con la espera real (3 intentos en total, ≈ 20 min con retroceso exponencial) y termina en `failed`; `marcar_ingesta_completa` queda en `upstream_failed` y **no** se crea la fila del día.
  - **Mensual, con los 33 días de octubre cargados:** el sensor pasa, `liquidar_mes` recibe `{silver_run_id}` del **último día requerido** (2 de noviembre) y registra `ok` y su duración en `corridas_liquidacion`; repetirlo crea una **segunda** liquidación publicada y deja intacta la primera.
  - **Mensual, el job termina sin crear versión:** la corrida queda con `estado = error` y `VersionNoCreada` en el detalle, y la tarea pasa a `up_for_retry`.
  - **Mensual sin los días del mes (noviembre):** el sensor queda en `up_for_reschedule` y no se liquida nada.
- **No probado todavía:** el stack de Docker (`docker-compose.airflow.yml`) con los 2 workers de Celery y RabbitMQ, ni una corrida en la EC2 (Airflow en EC2 aún no está en Terraform). La guía para hacerlo en Docker está en `pruebas/airflow-local/README.md`.
