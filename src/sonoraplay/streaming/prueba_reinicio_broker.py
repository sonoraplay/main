"""EG-29 · Prueba de reinicio del broker (RNF-04).

Dos escenarios sobre el mismo lote:

A. **Broker reiniciado con la cola llena.** Se publican N válidos + 1 inválido (con confirmación)
   y se reinicia RabbitMQ antes de consumir. Como las colas son durables y los mensajes
   persistentes, al volver siguen los N + 1.
B. **Broker reiniciado a mitad del consumo.** Un consumidor empieza a guardar en Bronze y se
   reinicia el broker. El consumidor pierde la conexión y termina; lo que no alcanzó a confirmar
   sigue en la cola. Un consumidor nuevo vacía la cola.

Verificación final: guardados = publicados, 0 duplicados, 0 perdidos, cola vacía y el inválido
en la DLQ. Necesita RabbitMQ y permiso para reiniciarlo (por defecto
``docker restart sonoraplay-rabbitmq``). Uso:
    python -m sonoraplay.streaming.prueba_reinicio_broker --entrada data/processed/eventos_f2.jsonl
"""

import argparse
import json
import shlex
import subprocess
import sys
import time
from pathlib import Path

from sonoraplay.streaming.config import StreamingConfig
from sonoraplay.streaming.productor import publicar
from sonoraplay.streaming.prueba_reinicio import (
    COLA_DE_PRUEBA,
    _consumidor,
    _contar_lineas,
    _profundidad,
    config_de_prueba,
    preparar,
)

REINICIO_POR_DEFECTO = "docker restart sonoraplay-rabbitmq"


def esperar_broker(cfg: StreamingConfig, limite_s: float = 90) -> float:
    """Reintenta la conexión hasta que el broker responde. Devuelve los segundos de espera."""
    import pika

    inicio = time.monotonic()
    while True:
        try:
            pika.BlockingConnection(pika.URLParameters(cfg.url)).close()
            return time.monotonic() - inicio
        except pika.exceptions.AMQPError:
            if time.monotonic() - inicio > limite_s:
                raise
            time.sleep(1)


def reiniciar_broker(cfg: StreamingConfig, comando: str) -> float:
    subprocess.run(shlex.split(comando), check=True, capture_output=True)
    return esperar_broker(cfg)


def ejecutar(
    cfg: StreamingConfig, eventos: list[str], comando: str, cortar_en: int, retraso_ms: int
) -> dict:
    print(f"== 1 · Limpieza de {cfg.cola}, {cfg.cola_dlq} y {cfg.destino_bronze}")
    preparar(cfg)

    invalido = json.loads(eventos[0])
    invalido["event_type"] = "rewind"  # no existe en el esquema F2 → DLQ al consumirlo
    invalido["event_id"] = "00000000-0000-4000-8000-000000000001"
    print(f"== 2 · Publicar {len(eventos)} válidos + 1 inválido (publisher confirms)")
    confirmados = publicar(cfg, [*eventos, json.dumps(invalido)])
    antes, _ = _profundidad(cfg)
    print(f"   confirmados por el broker: {confirmados}; en cola: {antes}")

    print(f"== 3 · Escenario A: reiniciar el broker con la cola llena ({comando})")
    t_a = reiniciar_broker(cfg, comando)
    despues, _ = _profundidad(cfg)
    print(f"   broker de vuelta en {t_a:.1f} s; en cola tras el reinicio: {despues}")

    print(f"== 4 · Escenario B: consumidor a {retraso_ms} ms por mensaje; reinicio en {cortar_en}")
    p1 = _consumidor(cfg, "--retraso-ms", str(retraso_ms))
    limite = time.monotonic() + 120
    while _contar_lineas(cfg.destino_bronze) < cortar_en and time.monotonic() < limite:
        time.sleep(0.05)
    t_b = reiniciar_broker(cfg, comando)
    try:
        p1.wait(timeout=30)
    except subprocess.TimeoutExpired:
        p1.kill()
        p1.wait()
    en_disco = _contar_lineas(cfg.destino_bronze)
    pendientes, _ = _profundidad(cfg)
    print(
        f"   broker de vuelta en {t_b:.1f} s; consumidor #1 terminó con código {p1.returncode}; "
        f"en Bronze: {en_disco}; en cola: {pendientes}"
    )

    print("== 5 · Consumidor #2 hasta vaciar la cola")
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
        "en_cola_antes_reinicio_A": antes,
        "en_cola_despues_reinicio_A": despues,
        "en_bronze_al_reiniciar_B": en_disco,
        "codigo_consumidor_1": p1.returncode,
        "guardados_en_bronze": len(ids),
        "duplicados": len(ids) - len(set(ids)),
        "perdidos": len(esperados - set(ids)),
        "cola_al_final": cola,
        "dlq_al_final": dlq,
    }
    r["resultado"] = (
        "OK"
        if despues == antes == len(eventos) + 1
        and 0 < en_disco < len(esperados)
        and r["guardados_en_bronze"] == r["publicados_validos"]
        and r["duplicados"] == 0
        and r["perdidos"] == 0
        and cola == 0
        and dlq == 1
        else "FALLA"
    )
    print("== 6 · Verificación")
    print(json.dumps(r, indent=2, ensure_ascii=False))
    return r


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="python -m sonoraplay.streaming.prueba_reinicio_broker")
    p.add_argument("--entrada", type=Path, default=Path("data/processed/eventos_f2.jsonl"))
    p.add_argument("--bronze", type=Path, default=Path("data/bronze/prueba_broker/f2.jsonl"))
    p.add_argument("--reinicio", default=REINICIO_POR_DEFECTO, help="Comando que reinicia RabbitMQ")
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
    r = ejecutar(cfg, eventos, a.reinicio, a.cortar_en or max(1, len(eventos) // 3), a.retraso_ms)
    sys.exit(0 if r["resultado"] == "OK" else 1)


if __name__ == "__main__":
    main()
