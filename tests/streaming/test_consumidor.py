"""EG-29 · Lógica del consumidor sin RabbitMQ: idempotencia, DLQ y recuperación tras un corte."""

import json
from pathlib import Path

import pytest

from sonoraplay.simulador.f2_minimo import validador
from sonoraplay.streaming.bronze import AlmacenBronze
from sonoraplay.streaming.consumidor import Conteo, procesar

EJEMPLOS = Path(__file__).resolve().parents[2] / "schemas" / "ejemplos"


def _validos() -> list[bytes]:
    return [p.read_bytes() for p in sorted((EJEMPLOS / "validos").glob("*.json"))]


@pytest.fixture
def almacen(tmp_path: Path):
    a = AlmacenBronze(tmp_path / "bronze" / "eventos_f2.jsonl")
    yield a
    a.cerrar()


def test_valido_se_guarda_y_se_confirma(almacen):
    conteo = Conteo()
    for cuerpo in _validos():
        assert procesar(cuerpo, almacen, validador(), conteo) == "ack"
    assert conteo.guardados == len(_validos())
    lineas = almacen.ruta.read_text(encoding="utf-8").splitlines()
    assert len(lineas) == len(_validos())


def test_duplicado_se_confirma_sin_escribir(almacen):
    cuerpo = _validos()[0]
    conteo = Conteo()
    assert procesar(cuerpo, almacen, validador(), conteo) == "ack"
    assert procesar(cuerpo, almacen, validador(), conteo) == "ack"
    assert (conteo.guardados, conteo.duplicados) == (1, 1)
    assert len(almacen.ruta.read_text(encoding="utf-8").splitlines()) == 1


@pytest.mark.parametrize(
    "ruta", sorted((EJEMPLOS / "invalidos").glob("*.json")), ids=lambda p: p.stem
)
def test_invalido_va_a_dlq(almacen, ruta):
    conteo = Conteo()
    assert procesar(ruta.read_bytes(), almacen, validador(), conteo) == "dlq"
    assert conteo.a_dlq == 1 and conteo.guardados == 0
    assert almacen.ruta.read_text(encoding="utf-8") == ""


def test_json_roto_va_a_dlq(almacen):
    conteo = Conteo()
    assert procesar(b"{no es json", almacen, validador(), conteo) == "dlq"
    assert conteo.motivos_dlq[0].startswith("json:")


def test_reabrir_recuerda_lo_guardado(tmp_path):
    """Reinicio del consumidor: lo ya guardado se reconoce como duplicado al reentregarse."""
    ruta = tmp_path / "eventos_f2.jsonl"
    a = AlmacenBronze(ruta)
    evento = json.loads(_validos()[0])
    assert a.guardar(evento)
    a.cerrar()
    b = AlmacenBronze(ruta)
    assert evento["event_id"] in b.vistos
    assert not b.guardar(evento)
    b.cerrar()


def test_linea_truncada_se_descarta_al_abrir(tmp_path):
    """Corte a mitad de una escritura: esa línea no tuvo ACK, se descarta y se vuelve a recibir."""
    ruta = tmp_path / "eventos_f2.jsonl"
    completo, cortado = (json.loads(c) for c in _validos()[:2])
    linea = json.dumps(completo, separators=(",", ":")) + "\n"
    ruta.write_text(linea + json.dumps(cortado)[:25], encoding="utf-8")
    a = AlmacenBronze(ruta)
    assert a.vistos == {completo["event_id"]}
    assert ruta.read_text(encoding="utf-8") == linea
    assert a.guardar(cortado)
    a.cerrar()
    assert len(ruta.read_text(encoding="utf-8").splitlines()) == 2
