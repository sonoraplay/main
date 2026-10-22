"""Productor F2 con publisher confirms y mensajes persistentes (EG-29, criterio 1).

Uso: python -m sonoraplay.streaming.productor --entrada data/processed/eventos_f2.jsonl
"""

import argparse
import json
from pathlib import Path
from typing import Any

from sonoraplay.streaming.config import StreamingConfig
from sonoraplay.streaming.topologia import declarar


def publicar(cfg: StreamingConfig, lineas: list[str]) -> int:
    """Publica cada línea JSON como un mensaje persistente y espera la confirmación del broker.

    Con ``confirm_delivery`` cada ``basic_publish`` bloquea hasta que RabbitMQ confirma que el
    mensaje quedó en una cola durable; si el broker lo rechaza o no tiene ruta (``mandatory``),
    pika lanza una excepción y el productor se detiene en ese evento en vez de perderlo en
    silencio. El ``message_id`` es el ``event_id`` cuando la línea lo trae.
    """
    import pika

    conexion = pika.BlockingConnection(pika.URLParameters(cfg.url))
    canal = conexion.channel()
    declarar(canal, cfg)
    canal.confirm_delivery()
    publicados = 0
    try:
        for linea in lineas:
            if publicar_linea(canal, cfg, linea):
                publicados += 1
    finally:
        conexion.close()
    return publicados


def publicar_linea(canal: Any, cfg: StreamingConfig, linea: str) -> bool:
    """Publica una línea como mensaje persistente y obligatorio. Devuelve False si está vacía.

    El canal debe tener ``confirm_delivery``: así ``basic_publish`` bloquea hasta la confirmación.
    """
    import pika

    linea = linea.strip()
    if not linea:
        return False
    try:
        message_id = json.loads(linea).get("event_id")
    except (json.JSONDecodeError, AttributeError):
        message_id = None  # el consumidor lo mandará a la DLQ
    canal.basic_publish(
        exchange=cfg.exchange,
        routing_key=cfg.llave,
        body=linea.encode("utf-8"),
        properties=pika.BasicProperties(
            delivery_mode=pika.DeliveryMode.Persistent,
            content_type="application/json",
            message_id=message_id,
        ),
        mandatory=True,
    )
    return True


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m sonoraplay.streaming.productor")
    p.add_argument("--entrada", type=Path, default=Path("data/processed/eventos_f2.jsonl"))
    a = p.parse_args(argv)
    n = publicar(
        StreamingConfig.desde_entorno(), a.entrada.read_text(encoding="utf-8").splitlines()
    )
    print(f"publicados={n} con confirmación del broker", flush=True)


if __name__ == "__main__":
    main()
