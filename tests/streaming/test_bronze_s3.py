"""EG-33 · Bronze en S3: lotes por fecha, evento intacto + marca de ingesta, ráfaga y corte."""

import json
import uuid
from datetime import UTC, datetime, timedelta

import pytest

from sonoraplay.simulador.f2_minimo import validador
from sonoraplay.streaming.bronze_s3 import AlmacenBronzeS3, leer_lineas, leer_unicos
from sonoraplay.streaming.consumidor import Conteo, procesar

BUCKET = "bronze-prueba"


class S3Falso:
    """Lo mínimo de boto3 que usa el almacén; guarda los objetos en memoria."""

    def __init__(self):
        self.objetos: dict[str, bytes] = {}
        self.fallar_en: int | None = None
        self.puts = 0

    def put_object(self, Bucket, Key, Body, **kw):  # noqa: N803
        self.puts += 1
        if self.fallar_en is not None and self.puts == self.fallar_en:
            raise OSError("S3 no responde")
        assert kw.get("ServerSideEncryption") == "AES256"
        self.objetos[Key] = Body

    def list_objects_v2(self, Bucket, Prefix, **kw):  # noqa: N803
        return {"Contents": [{"Key": k} for k in sorted(self.objetos) if k.startswith(Prefix)]}

    def get_object(self, Bucket, Key):  # noqa: N803
        cuerpo = self.objetos[Key]

        class _Cuerpo:
            def read(self):
                return cuerpo

        return {"Body": _Cuerpo()}


def evento(i: int, dia: int = 17) -> dict:
    ts = datetime(2026, 9, dia, 12, tzinfo=UTC) + timedelta(milliseconds=i)
    return {
        "schema_version": "1.0",
        "event_id": str(uuid.UUID(int=i)),
        "event_type": "start",
        "user_id": str(uuid.UUID(int=10_000_000 + i % 1000)),
        "device_id": "dev-1",
        "track_id": "23Mcmg5O8rBKAOzxvrTjnD",
        "session_id": str(uuid.UUID(int=20_000_000 + i)),
        "device_ts": ts.isoformat(timespec="milliseconds").replace("+00:00", "Z"),
        "server_ts": (ts + timedelta(milliseconds=200))
        .isoformat(timespec="milliseconds")
        .replace("+00:00", "Z"),
        "position_ms": 0,
        "country_playback": "CO",
        "is_offline": False,
    }


@pytest.fixture
def s3():
    return S3Falso()


def test_particiona_por_fecha_y_guarda_el_evento_intacto_con_su_ingesta(s3):
    almacen = AlmacenBronzeS3(s3, BUCKET, "f2", reloj=lambda: "2026-09-18T00:00:00.000Z")
    e1, e2 = evento(1, dia=17), evento(2, dia=18)
    almacen.guardar(e1)
    almacen.guardar(e2)
    assert almacen.volcar() == 2
    claves = sorted(s3.objetos)
    assert [k.split("/")[1] for k in claves] == ["fecha=2026-09-17", "fecha=2026-09-18"]
    linea = json.loads(s3.objetos[claves[0]].decode().splitlines()[0])
    assert linea.pop("_ingested_at_utc") == "2026-09-18T00:00:00.000Z"
    assert linea == e1  # criterio 4: el evento original no cambia


def test_un_fallo_de_s3_no_pierde_ni_duplica(s3):
    almacen = AlmacenBronzeS3(s3, BUCKET, tam_lote=10)
    for i in range(5):
        almacen.guardar(evento(i))
    s3.fallar_en = 1
    with pytest.raises(OSError):
        almacen.volcar()
    assert almacen.pendientes == 5  # no se descartó nada
    s3.fallar_en = None
    assert almacen.volcar() == 5
    assert len(leer_unicos(s3, BUCKET, "f2")) == 5
    # Reintentar el mismo lote cae en la misma clave: no crea otro objeto.
    assert len(s3.objetos) == 1


def test_duplicado_en_el_mismo_proceso_no_se_encola_dos_veces(s3):
    almacen = AlmacenBronzeS3(s3, BUCKET)
    assert almacen.guardar(evento(1)) is True
    assert almacen.guardar(evento(1)) is False
    assert almacen.pendientes == 1


def test_rafaga_de_100000_eventos_publicados_igual_almacenados(s3):
    """Criterio 2 (lógica del consumidor): una ráfaga con reintentos mezclados."""
    almacen = AlmacenBronzeS3(s3, BUCKET, tam_lote=5_000)
    esquema, conteo = validador(), Conteo()
    publicados = 100_000
    for i in range(publicados):
        assert procesar(json.dumps(evento(i)).encode(), almacen, esquema, conteo) == "ack"
        if i % 50 == 0:  # reintento del dispositivo: mismo evento otra vez
            procesar(json.dumps(evento(i)).encode(), almacen, esquema, conteo)
        if almacen.listo():
            almacen.volcar()
    almacen.cerrar()
    unicos = leer_unicos(s3, BUCKET, "f2")
    assert len(unicos) == publicados
    assert conteo.guardados == publicados and conteo.a_dlq == 0
    assert conteo.duplicados == publicados // 50 + (1 if publicados % 50 else 0)


def test_consumidor_interrumpido_no_pierde_y_los_duplicados_se_quitan(s3):
    """Criterio 3 (lógica): muere tras escribir un lote pero antes del ACK; RabbitMQ re-entrega."""
    total = 1_000
    eventos = [evento(i) for i in range(total)]
    # Proceso 1: escribe un lote de 300 y muere ANTES de confirmar; otros 100 quedan en memoria.
    p1 = AlmacenBronzeS3(s3, BUCKET, tam_lote=300)
    for e in eventos[:400]:
        p1.guardar(e)
        if p1.listo():
            p1.volcar()
    # (muerte del proceso: p1 no se cierra; los 100 pendientes se pierden de memoria)
    sin_ack = eventos  # nada se confirmó: RabbitMQ re-entrega TODO
    # Proceso 2 (la tarea que reemplaza a la interrumpida):
    # La tarea nueva arma lotes con otros límites, así que el reproceso no cae en las mismas claves.
    p2 = AlmacenBronzeS3(s3, BUCKET, tam_lote=250)
    for e in sin_ack:
        p2.guardar(e)
        if p2.listo():
            p2.volcar()
    p2.cerrar()
    lineas = list(leer_lineas(s3, BUCKET, "f2"))
    unicos = leer_unicos(s3, BUCKET, "f2")
    assert {e["event_id"] for e in eventos} == set(unicos)  # 0 perdidos
    assert len(unicos) == total
    assert len(lineas) > total  # hubo duplicados, y se quitan por event_id


def test_bronze_no_borra_ni_sobrescribe_lotes_distintos(s3):
    a = AlmacenBronzeS3(s3, BUCKET)
    a.guardar(evento(1))
    a.volcar()
    b = AlmacenBronzeS3(s3, BUCKET)
    b.guardar(evento(2))
    b.volcar()
    assert len(s3.objetos) == 2


def test_tam_lote_invalido():
    with pytest.raises(ValueError):
        AlmacenBronzeS3(S3Falso(), BUCKET, tam_lote=0)
