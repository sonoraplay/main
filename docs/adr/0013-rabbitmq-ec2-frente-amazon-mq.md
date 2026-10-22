# ADR-0013 · RabbitMQ autogestionado en EC2 (una instancia ARM) frente a Amazon MQ

| Campo | Valor |
|---|---|
| Estado | **Aceptado** (aprobado por Julián el 2026-10-21 tras fusionar el PR #5) |
| Fecha | 2026-10-21 |
| Historia que lo origina | HU 20 · EG-29 |
| Responsable | Andrea |
| Revisó | Julián: aprobó el ADR el 2026-10-21, incluido el riesgo residual de un solo nodo y de perder el volumen EBS |
| Referencias | RNF-04, RF-01, tema 10, tema 12 (broker de Celery), [ADR-0001](0001-arquitectura-base-aws.md), [ADR-0004](0004-esquema-eventos-f2.md), [ADR-0020](0020-ventanas-encendido-aws.md), [mensajería F2](../servicios/mensajeria-rabbitmq.md) |

## 1. Contexto

Los eventos de reproducción (F2) llegan por una cola antes de guardarse en Bronze. RNF-04 exige **cero eventos perdidos**, y el tema 10 pide RabbitMQ. El mismo broker sirve después como broker de Celery para Airflow (tema 12, ADR-0015).

En local, la EG-29 ya usa RabbitMQ 4.1 con colas durables, mensajes persistentes, publisher confirms, ACK manual después de guardar y DLQ. Falta decidir **dónde corre el broker en AWS**. Según ADR-0020, el entorno solo se prende en ventanas de prueba y de forma continua en la última semana, así que el costo que importa es el **por hora**.

## 2. Qué debe cumplir la decisión

- **Requisito RNF-04:** ningún evento se pierde si se reinicia el consumidor o el broker.
- **Tema 10 y tema 12:** RabbitMQ real (AMQP 0-9-1). Celery lo usa como broker.
- **Costo:** el menor costo justificable (ADR-0001). El broker queda prendido en cada ventana.
- **Seguridad:** sin IP pública; solo los SG del consumidor, el simulador y Airflow llegan al puerto 5672.
- **Equipo:** se crea y destruye con el mismo Terraform de la EG-26 (ADR-0011).

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. USD/mes (730 h) |
|---|---|---|---|
| **A · RabbitMQ en EC2 `t4g.small`, 1 nodo, colas classic durables, EBS gp3 20 GB** | El más barato que cumple. La misma imagen y configuración que en local (docker compose). El equipo controla la versión y los plugins | Nosotros parcheamos y monitoreamos. Un solo nodo es un punto único de falla (sin alta disponibilidad) | ≈ 14 (12 instancia + 1,6 disco) |
| B · Amazon MQ for RabbitMQ, `mq.t3.micro`, instancia única | Administrado: parches, consola y métricas incluidos | Pensado para evaluación, también de un solo nodo. Cuesta más por hora y es otro servicio que aprender y destruir | ≈ 20–22 |
| C · Amazon MQ en clúster (3 nodos `mq.m5.large`) | Alta disponibilidad administrada | Muy por encima del presupuesto para un proyecto de 6 semanas | ≈ 700 |
| D · Amazon SQS | Sin servidor y casi gratis a este volumen | No es RabbitMQ: no cumple el tema 10. Cambia el código del productor y del consumidor | < 1 |
| E · RabbitMQ como tarea Fargate con EFS | Sin EC2 que parchear | Persistencia sobre EFS más lenta y frágil para un broker. Más piezas que la opción A sin ahorro real | ≈ 10–12 + EFS |

Los precios son de lista en us-east-1 y salen del [presupuesto del equipo](../arquitectura/arquitectura-v1.md). Se confirman con AWS Pricing Calculator en la HU 23 (EG-32).

## 4. Decisión

**Elegimos la opción A:** RabbitMQ 4.1 en una EC2 `t4g.small` (ARM) de una subred privada, con colas **classic durables**, mensajes persistentes en EBS, publisher confirms, ACK manual después de guardar y DLQ. Es la opción más barata que cumple el tema 10 y RNF-04. Un solo nodo es aceptable porque las pruebas de la EG-29 muestran que **reiniciar el broker no pierde mensajes** (sección 6). Lo que no protege un solo nodo es la pérdida del disco, y eso se mitiga abajo.

**Classic y no quorum:** una cola quorum replica en 3 nodos. Con un solo nodo no agrega tolerancia a fallas y sí consume más memoria y disco. Si el broker pasa a clúster, la cola pasa a quorum (`x-queue-type`) sin cambiar el productor ni el consumidor.

## 5. Consecuencias

- **Positivas:**
  - ≈ 6–8 USD/mes menos que Amazon MQ con lo mismo de durabilidad en un nodo.
  - La misma topología en local y en AWS: la prueba de docker compose vale como evidencia.
  - El broker de Celery sale gratis.
- **Negativas / lo que aceptamos:**
  - Mantener una EC2 (AMI, parches de seguridad).
  - Sin alta disponibilidad. Mientras el broker se reinicia (≈ 3 s en la prueba), el productor recibe error y debe reintentar.
- **Riesgos y mitigación:**
  - **Pérdida del volumen EBS:** el productor solo da por publicado un evento con confirmación del broker, y el simulador puede volver a emitir el lote. Bronze descarta duplicados por `event_id` (ADR-0004).
  - **Caída del consumidor durante un reinicio del broker:** termina con error y ECS lo reinicia. Lo que no confirmó vuelve a la cola, y Bronze absorbe la reentrega.
  - **Cola llena por un consumidor caído:** alarma de CloudWatch sobre la profundidad de la cola (pendiente para la HU de observabilidad).

## 6. Cómo sabremos que funciona

Pruebas de la EG-29 con los 100 eventos del simulador (semilla 42) y RabbitMQ 4.1.8 en docker compose:

| Prueba | Resultado |
|---|---|
| Consumidor con SIGKILL a mitad de la carga (20 oct) | 100/100 en Bronze, 0 duplicados, 0 perdidos, 1 inválido en la DLQ |
| Broker reiniciado con la cola llena (21 oct) | 101 mensajes antes y 101 después del reinicio (≈ 3 s) |
| Broker reiniciado a mitad del consumo (21 oct) | El consumidor termina con error con 35 en Bronze. Un mensaje guardado sin ACK se reentrega y la deduplicación lo descarta. Resultado: 100/100, 0 duplicados, 0 perdidos, 1 en la DLQ |
| `pytest tests/streaming` con RabbitMQ | 22 passed (incluye las dos pruebas de reinicio) |

En AWS: repetir `prueba_reinicio_broker` contra la EC2 en la siguiente ventana (ADR-0020), con `--reinicio "aws ssm send-command … systemctl restart rabbitmq-server"` o el equivalente con docker.

## 7. Fuentes

- RabbitMQ, *Reliability Guide* (confirms, ACK manual, durabilidad): https://www.rabbitmq.com/docs/reliability
- RabbitMQ, *Publisher Confirms and Consumer Acknowledgements*: https://www.rabbitmq.com/docs/confirms
- RabbitMQ, *Quorum Queues* (cuándo usarlas): https://www.rabbitmq.com/docs/quorum-queues
- RabbitMQ, *Dead Letter Exchanges*: https://www.rabbitmq.com/docs/dlx
- Amazon MQ, precios: https://aws.amazon.com/amazon-mq/pricing/
- Amazon MQ, tipos de instancia de broker: https://docs.aws.amazon.com/amazon-mq/latest/developer-guide/rmq-broker-instance-types.html
- Amazon EC2, precios bajo demanda: https://aws.amazon.com/ec2/pricing/on-demand/

---

## English — Decision summary

**Accepted (proposed October 21, 2026; approved by Julián on October 21, 2026, after PR #5 was merged; EG-29).** RabbitMQ 4.1 runs self-managed on one ARM EC2 `t4g.small` in a private subnet. It uses classic durable queues, persistent messages on EBS, publisher confirms, manual ACK after storing, and a dead-letter queue. This is the cheapest option that meets topic 10 and RNF-04 (≈ 14 USD/month versus ≈ 20–22 for Amazon MQ `mq.t3.micro`; list prices to confirm in HU 23). Quorum queues are left for a future cluster, because on a single node they add no fault tolerance.

The EG-29 tests in docker compose support the single-node choice:

- A consumer SIGKILL and a broker restart (with a full queue and mid-consumption) lost no events and left no duplicates.
- The one redelivered message was discarded by `event_id` deduplication.

The residual risk is losing the EBS volume. It is mitigated by publisher confirms plus re-emitting the batch, since Bronze is idempotent.

**Traceability:** The Spanish sections above are the full decision record. This summary introduces no new decision.
