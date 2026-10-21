"""EG-29 · Prueba de reinicio del consumidor (criterios 2, 3 y 4).

1. Limpia las colas y el archivo Bronze de la prueba.
2. Publica N eventos válidos (con confirmación del broker) y 1 inválido.
3. Arranca el consumidor y lo mata con SIGKILL a mitad de la carga (sin cierre ordenado).
4. Lo vuelve a arrancar hasta vaciar la cola.
5. Verifica: guardados = publicados, 0 duplicados, 0 perdidos y el inválido en la DLQ.

Necesita RabbitMQ (``docker compose up -d rabbitmq``) y RABBITMQ_URL. Uso:
    python -m sonoraplay.streaming.prueba_reinicio --entrada data/processed/eventos_f2.jsonl
"""

import argparse
import dataclasses
import json
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

from sonoraplay.streaming.config import StreamingConfig
from sonoraplay.streaming.productor import publicar
from sonoraplay.streaming.topologia import declarar

# La prueba purga su cola al empezar: por defecto usa una propia, nunca eventos.f2 (revisión
# del PR #5). El exchange es el mismo; la llave de enrutamiento separa los mensajes.
COLA_DE_PRUEBA = "prueba.eventos.f2"


def config_de_prueba(cola: str, bronze: Path) -> StreamingConfig:
    base = StreamingConfig.desde_entorno()
    if cola == base.cola:
        print(f"AVISO: la prueba va a vaciar la cola real {cola}.", flush=True)
    return dataclasses.replace(
        base, cola=cola, cola_dlq=f"{cola}.dlq", llave=cola, destino_bronze=bronze
    )


def _contar_lineas(ruta: Path) -> int:
    return len(ruta.read_bytes().splitlines()) if ruta.exists() else 0


def _consumidor(cfg: StreamingConfig, *extra: str) -> subprocess.Popen:
    env = {
        **os.environ,
        "BRONZE_F2": str(cfg.destino_bronze),
        "RABBITMQ_URL": cfg.url,
        "RABBITMQ_LLAVE": cfg.llave,
        "RABBITMQ_COLA": cfg.cola,
        "RABBITMQ_COLA_DLQ": cfg.cola_dlq,
    }
    return subprocess.Popen(
        [sys.executable, "-m", "sonoraplay.streaming.consumidor", *extra], env=env
    )


def _profundidad(cfg: StreamingConfig) -> tuple[int, int]:
    import pika

    con = pika.BlockingConnection(pika.URLParameters(cfg.url))
    ch = con.channel()
    cola = ch.queue_declare(cfg.cola, passive=True).method.message_count
    dlq = ch.queue_declare(cfg.cola_dlq, passive=True).method.message_count
    con.close()
    return cola, dlq


def preparar(cfg: StreamingConfig) -> None:
    import pika

    con = pika.BlockingConnection(pika.URLParameters(cfg.url))
    ch = con.channel()
    declarar(ch, cfg)
    ch.queue_purge(cfg.cola)
    ch.queue_purge(cfg.cola_dlq)
    con.close()
    cfg.destino_bronze.unlink(missing_ok=True)


def ejecutar(cfg: StreamingConfig, eventos: list[str], cortar_en: int, retraso_ms: int) -> dict:
    print(f"== 1 · Limpieza de {cfg.cola}, {cfg.cola_dlq} y {cfg.destino_bronze}")
    preparar(cfg)

    invalido = json.loads(eventos[0])
    invalido["event_type"] = "rewind"  # no existe en el esquema F2 → DLQ
    invalido["event_id"] = "00000000-0000-4000-8000-000000000000"
    print(f"== 2 · Publicar {len(eventos)} válidos + 1 inválido (publisher confirms)")
    publicados = publicar(cfg, [*eventos, json.dumps(invalido)])
    print(f"   confirmados por el broker: {publicados}")

    print(f"== 3 · Consumidor #1 con {retraso_ms} ms por mensaje; SIGKILL al llegar a {cortar_en}")
    p1 = _consumidor(cfg, "--retraso-ms", str(retraso_ms))
    limite = time.monotonic() + 120
    while _contar_lineas(cfg.destino_bronze) < cortar_en and time.monotonic() < limite:
        time.sleep(0.05)
    p1.send_signal(signal.SIGKILL)
    p1.wait()
    en_disco = _contar_lineas(cfg.destino_bronze)
    time.sleep(1)  # el broker devuelve a la cola lo entregado sin ACK
    pendientes, _ = _profundidad(cfg)
    print(f"   matado (código {p1.returncode}); en Bronze: {en_disco}; en cola: {pendientes}")

    print("== 4 · Consumidor #2 hasta vaciar la cola")
    p2 = _consumidor(cfg, "--salir-si-vacia")
    p2.wait(timeout=300)

    ids = [
        json.loads(linea)["event_id"]
        for linea in cfg.destino_bronze.read_text(encoding="utf-8").splitlines()
    ]
    esperados = {json.loads(e)["event_id"] for e in eventos}
    cola, dlq = _profundidad(cfg)
    r = {
        "publicados_validos": len(esperados),
        "guardados_en_bronze": len(ids),
        "duplicados": len(ids) - len(set(ids)),
        "perdidos": len(esperados - set(ids)),
        "en_bronze_al_matar": en_disco,
        "cola_al_final": cola,
        "dlq_al_final": dlq,
    }
    r["resultado"] = (
        "OK"
        if r["guardados_en_bronze"] == r["publicados_validos"]
        and r["duplicados"] == 0
        and r["perdidos"] == 0
        and cola == 0
        and dlq == 1
        and 0 < en_disco < len(esperados)
        else "FALLA"
    )
    print("== 5 · Verificación")
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return r


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m sonoraplay.streaming.prueba_reinicio")
    p.add_argument("--entrada", type=Path, default=Path("data/processed/eventos_f2.jsonl"))
    p.add_argument("--bronze", type=Path, default=Path("data/bronze/prueba_reinicio/f2.jsonl"))
    p.add_argument("--cortar-en", type=int, default=0, help="Por defecto, un tercio de la carga")
    p.add_argument("--retraso-ms", type=int, default=50)
    p.add_argument(
        "--cola",
        default=COLA_DE_PRUEBA,
        help="Cola de la prueba (se vacía al empezar); nunca la de producción por defecto",
    )
    a = p.parse_args(argv)
    eventos = [ln for ln in a.entrada.read_text(encoding="utf-8").splitlines() if ln.strip()]
    cfg = config_de_prueba(a.cola, a.bronze)
    r = ejecutar(cfg, eventos, a.cortar_en or max(1, len(eventos) // 3), a.retraso_ms)
    sys.exit(0 if r["resultado"] == "OK" else 1)


if __name__ == "__main__":
    main()
