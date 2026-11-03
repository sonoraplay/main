"""Consumidor F2 → Bronze con ACK manual (EG-29, criterios 2, 3 y 4).

Uso: python -m sonoraplay.streaming.consumidor [--salir-si-vacia] [--retraso-ms N]
"""

import argparse
import json
import time
from dataclasses import dataclass, field
from typing import Any

from jsonschema import Draft202012Validator

from sonoraplay.simulador.f2_minimo import validador
from sonoraplay.streaming.bronze import AlmacenBronze
from sonoraplay.streaming.bronze_s3 import AlmacenBronzeS3
from sonoraplay.streaming.config import StreamingConfig
from sonoraplay.streaming.topologia import declarar


@dataclass
class Conteo:
    guardados: int = 0
    duplicados: int = 0
    a_dlq: int = 0
    motivos_dlq: list[str] = field(default_factory=list)


def procesar(
    cuerpo: bytes,
    almacen: AlmacenBronze | AlmacenBronzeS3,
    esquema: Draft202012Validator,
    conteo: Conteo,
) -> str:
    """Decide qué hacer con un mensaje. Devuelve ``"ack"`` o ``"dlq"``; no habla con RabbitMQ.

    - JSON roto o que no cumple el esquema F2 → ``"dlq"`` (se rechaza sin reencolar).
    - Válido → se guarda (o se reconoce como duplicado) y luego ``"ack"``.
    """
    try:
        evento = json.loads(cuerpo)
    except (UnicodeDecodeError, json.JSONDecodeError) as e:
        conteo.a_dlq += 1
        conteo.motivos_dlq.append(f"json: {e}")
        return "dlq"
    errores = sorted(esquema.iter_errors(evento), key=lambda e: list(e.path))
    if errores:
        conteo.a_dlq += 1
        conteo.motivos_dlq.append(f"esquema: {errores[0].message}")
        return "dlq"
    if almacen.guardar(evento):
        conteo.guardados += 1
    else:
        conteo.duplicados += 1
    return "ack"


INTERVALO_VOLCADO_S = 2  # con poco tráfico, un lote parcial no espera más que esto


def crear_almacen(cfg: StreamingConfig):
    """Bronze local (EG-29) o en S3 por lotes (EG-33), según ``BRONZE_S3_BUCKET``."""
    if cfg.bronze_s3_bucket:
        import boto3

        return AlmacenBronzeS3(
            boto3.client("s3"), cfg.bronze_s3_bucket, cfg.bronze_s3_prefijo, cfg.bronze_lote
        )
    return AlmacenBronze(cfg.destino_bronze)


def consumir(cfg: StreamingConfig, salir_si_vacia: bool = False, retraso_ms: int = 0) -> Conteo:
    import pika

    conexion = pika.BlockingConnection(pika.URLParameters(cfg.url))
    canal = conexion.channel()
    declarar(canal, cfg)
    canal.basic_qos(prefetch_count=cfg.prefetch)
    almacen = crear_almacen(cfg)
    esquema = validador()
    conteo = Conteo()
    # Con S3 el ACK se difiere: solo se confirma lo que `volcar` ya escribió (EG-33).
    diferido = hasattr(almacen, "volcar")
    pendientes: list[int] = []

    def volcar_y_confirmar() -> None:
        almacen.volcar()  # si S3 falla, la excepción sube y NO se confirma nada
        if pendientes:
            canal.basic_ack(delivery_tag=pendientes[-1], multiple=True)
            pendientes.clear()

    def al_recibir(ch: Any, metodo: Any, _props: Any, cuerpo: bytes) -> None:
        if retraso_ms:
            time.sleep(retraso_ms / 1000)
        if procesar(cuerpo, almacen, esquema, conteo) != "ack":
            ch.basic_nack(delivery_tag=metodo.delivery_tag, requeue=False)  # → DLQ
        elif diferido:
            pendientes.append(metodo.delivery_tag)
            if almacen.listo():
                volcar_y_confirmar()
        else:
            ch.basic_ack(delivery_tag=metodo.delivery_tag)  # después de guardar, nunca antes

    def vaciar_periodicamente() -> None:
        volcar_y_confirmar()
        conexion.call_later(INTERVALO_VOLCADO_S, vaciar_periodicamente)

    try:
        if salir_si_vacia:
            # Itera hasta que la cola pase 2 s sin mensajes; útil para pruebas y cargas por lotes.
            for metodo, props, cuerpo in canal.consume(cfg.cola, inactivity_timeout=2):
                if metodo is None:
                    break
                al_recibir(canal, metodo, props, cuerpo)
            if diferido:
                volcar_y_confirmar()
            canal.cancel()
        else:
            canal.basic_consume(queue=cfg.cola, on_message_callback=al_recibir)
            if diferido:
                conexion.call_later(INTERVALO_VOLCADO_S, vaciar_periodicamente)
            canal.start_consuming()
    finally:
        # Cerrar vuelca lo pendiente, pero ya sin canal vivo: lo no confirmado vuelve a la cola
        # y se guardará otra vez (duplicado que se quita por event_id).
        almacen.cerrar()
        if conexion.is_open:
            conexion.close()
    return conteo


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m sonoraplay.streaming.consumidor")
    p.add_argument("--salir-si-vacia", action="store_true", help="Termina tras 2 s sin mensajes")
    p.add_argument("--retraso-ms", type=int, default=0, help="Pausa por mensaje (para pruebas)")
    a = p.parse_args(argv)
    cfg = StreamingConfig.desde_entorno()
    c = consumir(cfg, a.salir_si_vacia, a.retraso_ms)
    print(
        f"guardados={c.guardados} duplicados={c.duplicados} a_dlq={c.a_dlq} "
        f"destino={cfg.destino_bronze}",
        flush=True,
    )


if __name__ == "__main__":
    main()
