---
title: "EG-29 · Mensajería F2 con RabbitMQ / F2 messaging with RabbitMQ"
---

# EG-29 · Mensajería F2 con RabbitMQ / F2 messaging with RabbitMQ

## Español

Los eventos de reproducción (F2) viajan del productor a Bronze por RabbitMQ sin perder ninguno (RNF-04). Esta primera entrega cubre el productor, el consumidor, la DLQ y la **prueba de reinicio del consumidor**. La decisión de broker y topología queda para el ADR-0013.

- **Código:** `src/sonoraplay/streaming/` (`config.py`, `topologia.py`, `productor.py`, `consumidor.py`, `bronze.py`, `prueba_reinicio.py`).
- **Pruebas:** `tests/streaming/`. La de integración se salta si no hay `RABBITMQ_URL` (por eso la CI no necesita RabbitMQ).
- **Docker:** servicio `rabbitmq` (`rabbitmq:4.1.8-management-alpine`), volumen `rabbitmq-datos`, consola en `http://localhost:15672`.

### Cómo no se pierde ningún evento

| Riesgo | Defensa |
|---|---|
| El broker se cae con mensajes dentro | Exchange y colas **durables**, mensajes **persistentes** (`delivery_mode=2`) en un volumen |
| El productor cree que publicó y no fue así | **Publisher confirms** (`confirm_delivery`) y `mandatory=True`: sin confirmación, el productor falla en ese evento |
| El consumidor muere a mitad del lote | **ACK manual después de `fsync`** en Bronze. Lo no confirmado vuelve a la cola. `prefetch=50` acota cuánto vuelve |
| Un mensaje se guardó pero murió antes del ACK | Bronze es **idempotente por `event_id`**: la segunda entrega se confirma sin escribir |
| Corte a mitad de una escritura | Al abrir, Bronze descarta la última línea incompleta; ese mensaje no tenía ACK y se recibe otra vez |
| Evento con JSON roto o fuera del esquema F2 | `basic_nack(requeue=False)` → dead-letter exchange → `eventos.f2.dlq`. No bloquea la cola y queda para revisión |

Topología: `sonoraplay.eventos` (direct) —`f2`→ `eventos.f2` (classic, durable, con DLX) · `sonoraplay.eventos.dlx` —`f2`→ `eventos.f2.dlq`.

### Cómo correrlo

```bash
# .env: RABBITMQ_USER, RABBITMQ_PASSWORD y RABBITMQ_URL (ver .env.example)
docker compose up -d rabbitmq
uv run --env-file .env python -m sonoraplay.streaming.productor --entrada data/processed/eventos_f2.jsonl
uv run --env-file .env python -m sonoraplay.streaming.consumidor --salir-si-vacia
# Prueba de reinicio (criterios 2, 3 y 4):
uv run --env-file .env python -m sonoraplay.streaming.prueba_reinicio
uv run --env-file .env python -m pytest tests/streaming -v
```

### Evidencia: primera prueba de reinicio (20 oct 2026)

Con los 100 eventos del simulador (semilla 42) que produjo la corrida del esqueleto (EG-24), en una Mac con Docker y RabbitMQ 4.1.8:

```text
== 2 · Publicar 100 válidos + 1 inválido (publisher confirms)
   confirmados por el broker: 101
== 3 · Consumidor #1 con 50 ms por mensaje; SIGKILL al llegar a 33
   matado (código -9); en Bronze: 33; en cola: 68
== 4 · Consumidor #2 hasta vaciar la cola
== 5 · Verificación
  publicados_validos: 100   guardados_en_bronze: 100   duplicados: 0   perdidos: 0
  en_bronze_al_matar: 33    cola_al_final: 0           dlq_al_final: 1
  resultado: OK
```

- El consumidor se mató con **SIGKILL** (sin cierre ordenado). Las 68 entregas sin ACK volvieron a la cola y el segundo consumidor las guardó: **100 de 100, 0 duplicados, 0 perdidos**.
- El evento inválido (`event_type` desconocido) terminó en la DLQ y no en Bronze.
- `pytest tests/streaming`: **21 passed** (20 unitarias + la de integración con RabbitMQ). Suite completa: **483 passed**; `ruff check` y `ruff format --check` limpios.

### Pendiente en la EG-29

- ADR-0013: broker, colas classic frente a quorum, `prefetch` y la DLQ.
- Prueba de **reinicio del broker** (`docker compose restart rabbitmq` con mensajes en cola).
- Pasar el destino Bronze de un JSON Lines local a S3 (capa Bronze de la EG-26) y el consumidor a un contenedor.

## English

F2 play events travel from the producer to Bronze through RabbitMQ without losing any (RNF-04). This first delivery covers the producer, the consumer, the DLQ and the **consumer restart test**. The broker and topology decision goes into ADR-0013.

- **Durability:** durable exchange and queues, persistent messages, publisher confirms with `mandatory=True`.
- **At-least-once plus idempotency:** manual ACK only after the event is `fsync`ed to Bronze; Bronze skips `event_id`s it already stored and drops a truncated last line on open.
- **Invalid events:** broken JSON or F2-schema errors are rejected without requeue and routed to `eventos.f2.dlq` through the dead-letter exchange.

**First restart test (Oct 20, 2026):** 100 valid events plus 1 invalid were published and confirmed by the broker. The consumer was killed with SIGKILL after storing 33; 68 unacknowledged messages went back to the queue. A second consumer drained it. Result: **100/100 stored, 0 duplicates, 0 lost, 1 message in the DLQ**. `tests/streaming`: 21 passed; full suite: 483 passed.

**Still open in EG-29:** ADR-0013, a broker-restart test, and moving the Bronze sink to S3 with the consumer in a container.
