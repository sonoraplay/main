"""Configuración de la mensajería F2 (EG-29). Todo sale de variables de entorno."""

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StreamingConfig:
    """Nombres y límites de la topología de RabbitMQ (RNF-04, ADR-0013).

    - ``exchange``: direct y durable; el productor publica ahí con la llave ``llave``.
    - ``cola``: durable, con dead-letter exchange para los mensajes inválidos (criterio 4).
    - ``prefetch``: mensajes sin ACK que el consumidor tiene a la vez. Acota lo que vuelve a la
      cola si el consumidor muere (criterio 2).
    """

    url: str = "amqp://guest:guest@localhost:5672/%2F"
    exchange: str = "sonoraplay.eventos"
    llave: str = "f2"
    cola: str = "eventos.f2"
    exchange_dlx: str = "sonoraplay.eventos.dlx"
    cola_dlq: str = "eventos.f2.dlq"
    prefetch: int = 50
    destino_bronze: Path = Path("data/bronze/f2/eventos_f2.jsonl")

    @classmethod
    def desde_entorno(cls) -> "StreamingConfig":
        base = cls()
        return cls(
            url=os.environ.get("RABBITMQ_URL", base.url),
            llave=os.environ.get("RABBITMQ_LLAVE", base.llave),
            cola=os.environ.get("RABBITMQ_COLA", base.cola),
            cola_dlq=os.environ.get("RABBITMQ_COLA_DLQ", base.cola_dlq),
            prefetch=int(os.environ.get("RABBITMQ_PREFETCH", base.prefetch)),
            destino_bronze=Path(os.environ.get("BRONZE_F2", str(base.destino_bronze))),
        )
