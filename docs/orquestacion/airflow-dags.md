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

Mientras falte `SILVER_JOB_COMMAND`, el sensor mensual no se cumple: es el comportamiento buscado, para no liquidar con días sin procesar.

## Qué está probado y qué no

- Probado en CI/local: importación de todos los DAG (DagBag), reintentos ≥ 2, idempotencia de F6 y referencia contra PostgreSQL, espera de ingesta, versión nueva por corrida, registro de duración, aviso de fallo (SNS simulado).
- **No probado todavía:** el stack de Docker (`docker-compose.airflow.yml`) corriendo con los 2 workers, ni una corrida en la EC2. Requieren la ventana de pruebas de AWS.
