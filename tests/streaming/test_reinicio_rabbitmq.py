"""EG-29 · Prueba de integración del reinicio. Solo corre con RabbitMQ (RABBITMQ_URL definido)."""

import dataclasses
import json
import os
import uuid
from pathlib import Path

import pytest

from sonoraplay.streaming.config import StreamingConfig

pytestmark = pytest.mark.skipif(
    not os.environ.get("RABBITMQ_URL"), reason="Necesita RabbitMQ: define RABBITMQ_URL"
)

VALIDOS = Path(__file__).resolve().parents[2] / "schemas" / "ejemplos" / "validos"


def test_reinicio_sin_perdidas_ni_duplicados(tmp_path):
    from sonoraplay.streaming.prueba_reinicio import ejecutar

    base = [json.loads(p.read_text(encoding="utf-8")) for p in sorted(VALIDOS.glob("*.json"))]
    eventos = []
    for i in range(60):
        e = dict(base[i % len(base)], event_id=str(uuid.uuid4()))
        eventos.append(json.dumps(e))
    cfg = dataclasses.replace(
        StreamingConfig.desde_entorno(),
        cola="prueba.eventos.f2",
        cola_dlq="prueba.eventos.f2.dlq",
        llave="prueba.f2",
        destino_bronze=tmp_path / "f2.jsonl",
    )
    r = ejecutar(cfg, eventos, cortar_en=20, retraso_ms=30)
    assert r["resultado"] == "OK", r
