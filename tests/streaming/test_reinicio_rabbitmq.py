"""EG-29 · Prueba de integración del reinicio. Solo corre con RabbitMQ (RABBITMQ_URL definido)."""

import json
import os
import uuid
from pathlib import Path

import pytest

pytestmark = pytest.mark.skipif(
    not os.environ.get("RABBITMQ_URL"), reason="Necesita RabbitMQ: define RABBITMQ_URL"
)

VALIDOS = Path(__file__).resolve().parents[2] / "schemas" / "ejemplos" / "validos"


def test_reinicio_sin_perdidas_ni_duplicados(tmp_path):
    from sonoraplay.streaming.prueba_reinicio import config_de_prueba, ejecutar

    base = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(VALIDOS.glob("*.json"))]
    eventos = []
    for i in range(60):
        e = dict(base[i % len(base)], event_id=str(uuid.uuid4()))
        eventos.append(json.dumps(e))
    cfg = config_de_prueba("pytest.reinicio.consumidor", tmp_path / "f2.jsonl")
    r = ejecutar(cfg, eventos, cortar_en=20, retraso_ms=30)
    assert r["resultado"] == "OK", r


@pytest.mark.skipif(
    not os.environ.get("RABBITMQ_REINICIO"),
    reason="Necesita permiso para reiniciar RabbitMQ: define RABBITMQ_REINICIO "
    "(p. ej. 'docker restart sonoraplay-rabbitmq')",
)
def test_reinicio_del_broker_sin_perdidas_ni_duplicados(tmp_path):
    from sonoraplay.streaming.prueba_reinicio import config_de_prueba
    from sonoraplay.streaming.prueba_reinicio_broker import ejecutar

    base = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(VALIDOS.glob("*.json"))]
    eventos = [json.dumps(dict(base[i % len(base)], event_id=str(uuid.uuid4()))) for i in range(60)]
    cfg = config_de_prueba("pytest.reinicio.broker", tmp_path / "f2.jsonl")
    r = ejecutar(cfg, eventos, os.environ["RABBITMQ_REINICIO"], cortar_en=20, retraso_ms=30)
    assert r["resultado"] == "OK", r
