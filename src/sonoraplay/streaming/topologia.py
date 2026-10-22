"""Declaración idempotente de exchanges y colas (EG-29, criterios 1 y 4)."""

from typing import Any

from sonoraplay.streaming.config import StreamingConfig


def declarar(canal: Any, cfg: StreamingConfig) -> None:
    """Declara todo como durable. Repetirlo no cambia nada (RabbitMQ compara los argumentos).

    Un mensaje rechazado con ``requeue=False`` va por el dead-letter exchange a ``cola_dlq``,
    así que un evento inválido queda guardado para revisarlo en vez de perderse.
    """
    canal.exchange_declare(exchange=cfg.exchange, exchange_type="direct", durable=True)
    canal.exchange_declare(exchange=cfg.exchange_dlx, exchange_type="direct", durable=True)
    canal.queue_declare(queue=cfg.cola_dlq, durable=True)
    canal.queue_bind(queue=cfg.cola_dlq, exchange=cfg.exchange_dlx, routing_key=cfg.llave)
    canal.queue_declare(
        queue=cfg.cola,
        durable=True,
        arguments={
            "x-dead-letter-exchange": cfg.exchange_dlx,
            "x-dead-letter-routing-key": cfg.llave,
            # Quorum o classic: classic durable basta para un nodo (ADR-0013).
            "x-queue-type": "classic",
        },
    )
    canal.queue_bind(queue=cfg.cola, exchange=cfg.exchange, routing_key=cfg.llave)
