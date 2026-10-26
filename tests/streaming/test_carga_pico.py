"""EG-51 criterio 1 · carga pico: >= 100 eventos/s de media durante 60 s hacia RabbitMQ (CT-06)."""

import json
import os

import pytest

from sonoraplay.streaming.carga_pico import ResultadoPico, publicar_a_ritmo


class RelojFalso:
    """Reloj y sueño simulados: el tiempo solo avanza cuando alguien duerme o publica."""

    def __init__(self, costo_publicar: float = 0.0) -> None:
        self.t = 0.0
        self.costo = costo_publicar

    def reloj(self) -> float:
        return self.t

    def dormir(self, s: float) -> None:
        self.t += max(s, 0.001)

    def publicar(self, _linea: str) -> None:
        self.t += self.costo


def _correr(tasa, duracion, costo=0.0, n=None):
    f = RelojFalso(costo)
    lineas = [str(i) for i in range(n or int(tasa * duracion) + 1)]
    return publicar_a_ritmo(f.publicar, lineas, tasa, duracion, f.reloj, f.dormir), lineas


def test_publica_a_la_tasa_pedida_durante_la_duracion():
    r, _ = _correr(120, 60)
    assert r.segundos >= 60
    assert 119 <= r.tasa_media <= 121
    assert r.cumple()
    # Ningún segundo completo se queda por debajo de 100 eventos.
    assert min(n for s, n in r.por_segundo.items() if s < 60) >= 100


def test_publica_cada_linea_una_sola_vez_y_en_orden():
    f = RelojFalso()
    vistas: list[str] = []
    lineas = [str(i) for i in range(500)]
    publicar_a_ritmo(lambda x: vistas.append(x), lineas, 100, 4, f.reloj, f.dormir)
    assert vistas == lineas[: len(vistas)] and len(vistas) == len(set(vistas)) >= 399


def test_un_broker_lento_no_cumple():
    r, _ = _correr(120, 5, costo=0.02, n=2_000)  # 20 ms por confirmación: máx. 50/s
    assert r.tasa_media < 60 and not r.cumple(tasa=100, duracion=5)


def test_un_broker_con_pausas_se_recupera_sin_pasarse_del_total():
    r, _ = _correr(100, 10)
    assert r.publicados <= 100 * 10 + 1


def test_cumple_exige_la_duracion_y_la_tasa_minimas():
    assert ResultadoPico(6_000, 60.0, 100).cumple()
    assert not ResultadoPico(6_000, 59.0, 100).cumple()  # menos de 60 s
    assert not ResultadoPico(5_000, 60.0, 100).cumple()  # menos de 100/s


def test_pocas_lineas_o_tasa_invalida_lanzan_error():
    with pytest.raises(ValueError, match="hacen falta"):
        publicar_a_ritmo(print, ["x"], 100, 60)
    with pytest.raises(ValueError, match="positivas"):
        publicar_a_ritmo(print, ["x"], 0, 60)


# --- Con RabbitMQ real -----------------------------------------------------------------------

rabbit = pytest.mark.skipif(
    not os.environ.get("RABBITMQ_URL"), reason="Necesita RabbitMQ: define RABBITMQ_URL"
)


def _eventos(n: int) -> list[str]:
    import uuid
    from pathlib import Path

    base = json.loads(
        (Path(__file__).resolve().parents[2] / "schemas/ejemplos/validos/start.json").read_text()
    )
    return [json.dumps(dict(base, event_id=str(uuid.uuid4()))) for _ in range(n)]


def _publicar_en_cola_de_prueba(nombre, tasa, duracion, tmp_path):
    from sonoraplay.streaming.carga_pico import publicar_pico
    from sonoraplay.streaming.prueba_reinicio import _profundidad, config_de_prueba, preparar

    cfg = config_de_prueba(nombre, tmp_path / "bronze.jsonl")
    preparar(cfg)
    lineas = _eventos(int(tasa * duracion) + int(tasa))
    r = publicar_pico(cfg, lineas, tasa, duracion)
    return r, _profundidad(cfg)


@rabbit
def test_carga_pico_corta_contra_rabbitmq_real(tmp_path):
    r, (en_cola, en_dlq) = _publicar_en_cola_de_prueba("pytest.pico.corto", 150, 4, tmp_path)
    assert r.tasa_media >= 100
    assert en_cola == r.publicados and en_dlq == 0  # lo confirmado está en la cola durable


@rabbit
@pytest.mark.skipif(
    not os.environ.get("PICO_60S"), reason="Corre 60 s: define PICO_60S=1 (criterio 1 completo)"
)
def test_carga_pico_de_60_s_contra_rabbitmq_real(tmp_path):
    r, (en_cola, en_dlq) = _publicar_en_cola_de_prueba("pytest.pico.completo", 120, 60, tmp_path)
    assert r.cumple(), r.como_dict()
    assert en_cola == r.publicados and en_dlq == 0
