---
title: "EG-33 · Bronze en S3 / Bronze on S3"
---

# EG-33 · Eventos de RabbitMQ a S3 Bronze sin pérdidas

El consumidor de la EG-29 ahora puede escribir en S3 (`BRONZE_S3_BUCKET`). Sin esa variable sigue usando el archivo local.

| Variable | Qué hace | Por defecto |
|---|---|---|
| `BRONZE_S3_BUCKET` | Bucket de Bronze (`terraform output buckets`). Si existe, se usa S3 | vacío (archivo local) |
| `BRONZE_S3_PREFIX` | Prefijo dentro del bucket | `f2` |
| `BRONZE_LOTE` | Eventos por lote antes de escribir | `500` |

## Cómo queda en S3

`s3://<bronze>/f2/fecha=AAAA-MM-DD/lote-<huella>.jsonl`. La fecha es la del `server_ts` en UTC. Cada línea es el evento **tal como llegó** más `_ingested_at_utc` (criterio 4). Los objetos se cifran con SSE-S3 y nunca se reescriben ni se borran.

## Por qué no se pierde nada

- El consumidor **confirma (ACK) solo después de escribir el lote en S3**. Si S3 falla, la excepción sube, no se confirma nada y RabbitMQ re-entrega.
- La clave del lote sale de sus `event_id` y la marca de ingesta se fija al recibir el evento: reintentar el mismo lote produce el mismo objeto.
- Si la tarea muere entre `put_object` y el ACK (interrupción de Spot), esos eventos se escriben otra vez en un lote distinto. Los duplicados se quitan **por `event_id` al leer** (`leer_unicos`; Silver hace lo mismo).
- Con poco tráfico, un lote parcial se escribe cada 2 s.

## Qué está probado y qué no

| Criterio | Estado |
|---|---|
| 1 · Simulador en AWS → RabbitMQ en EC2 → consumidor en Fargate Spot → Bronze por fecha | **Sin probar en AWS.** La escritura particionada por fecha está probada con un S3 simulado. Falta la imagen del consumidor (EG-52), su servicio en ECS y la EC2 de RabbitMQ en Terraform |
| 2 · Ráfaga de ≥ 100 000 eventos: publicados = almacenados | Probado la **lógica** con 100 000 eventos y reintentos mezclados contra un S3 simulado (`tests/streaming/test_bronze_s3.py`). **No** se corrió contra RabbitMQ ni S3 reales |
| 3 · Consumidor detenido a mitad de carga: 0 pérdidas, duplicados quitados por `event_id` | Probado en simulación (muerte tras escribir y antes del ACK). Falta la prueba real deteniendo la tarea de Fargate |
| 4 · Evento original + marca de ingesta | Probado |
| 5 · Profundidad de cola y errores visibles | Código listo: con `METRICAS_CLOUDWATCH=1` el consumidor publica en `SonoraPlay/Mensajeria` la profundidad de la cola y de la DLQ, y los contadores (guardados, duplicados, a DLQ, fallos de escritura en S3). El rol de tarea tiene `PutMetricData` acotado a ese espacio de nombres. Probado con CloudWatch simulado; **sin verificar en AWS** (hay que ver las métricas en la consola). La consola privada de RabbitMQ (`:15672` por túnel SSM) sigue siendo la alternativa que acepta el criterio |
