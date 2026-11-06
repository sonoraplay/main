"""Bronze F2 en S3 (EG-33): lotes JSON Lines particionados por fecha, con ACK diferido.

Cada objeto es un lote ``<prefijo>/fecha=AAAA-MM-DD/lote-<huella>.jsonl``. Cada línea es el
evento **tal como llegó** más ``_ingested_at_utc`` (criterio 4). La fecha es la del ``server_ts``
en UTC (ADR-0002, ADR-0014).

Garantías:

- **Sin pérdidas.** El consumidor confirma (ACK) a RabbitMQ solo después de que ``volcar`` terminó
  todas las escrituras; si S3 falla, la excepción sube y nada se confirma: RabbitMQ re-entrega.
- **Reintentos idempotentes.** La clave del objeto sale de los ``event_id`` del lote, y la marca de
  ingesta se fija al recibir el evento: reescribir el mismo lote produce el mismo objeto.
- **Duplicados.** Si el consumidor muere entre ``put_object`` y el ACK, esos eventos se guardan
  otra vez en otro lote. Se eliminan por ``event_id`` al leer (``leer_unicos``; Silver hace lo
  mismo, EG-35). Bronze nunca se reescribe ni se borra.
"""

from __future__ import annotations

import hashlib
import json
from collections import defaultdict
from collections.abc import Callable, Iterator
from datetime import UTC, datetime
from typing import Any

LOTE_POR_DEFECTO = 500


def _ahora() -> str:
    return datetime.now(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


class AlmacenBronzeS3:
    """Acumula eventos y los escribe a S3 por lotes. Misma interfaz de ``guardar`` que el local."""

    def __init__(
        self,
        cliente: Any,
        bucket: str,
        prefijo: str = "f2",
        tam_lote: int = LOTE_POR_DEFECTO,
        reloj: Callable[[], str] = _ahora,
    ) -> None:
        if tam_lote < 1:
            raise ValueError("tam_lote debe ser >= 1")
        self.cliente = cliente
        self.bucket = bucket
        self.prefijo = prefijo.strip("/")
        self.tam_lote = tam_lote
        self.reloj = reloj
        self.vistos: set[str] = set()
        self._buffer: list[tuple[dict, str]] = []
        self.objetos_escritos = 0

    @property
    def pendientes(self) -> int:
        return len(self._buffer)

    def guardar(self, evento: dict) -> bool:
        """Encola el evento. Devuelve False si ya estaba en este proceso (no lo encola de nuevo)."""
        if evento["event_id"] in self.vistos:
            return False
        self._buffer.append((evento, self.reloj()))
        self.vistos.add(evento["event_id"])
        return True

    def listo(self) -> bool:
        return len(self._buffer) >= self.tam_lote

    def volcar(self) -> int:
        """Escribe todo lo pendiente. Solo vacía el búfer si TODAS las escrituras tuvieron éxito."""
        if not self._buffer:
            return 0
        por_fecha: dict[str, list[tuple[dict, str]]] = defaultdict(list)
        for evento, ingesta in self._buffer:
            por_fecha[evento["server_ts"][:10]].append((evento, ingesta))
        for fecha, items in sorted(por_fecha.items()):
            ids = sorted(e["event_id"] for e, _ in items)
            huella = hashlib.sha256("\n".join(ids).encode()).hexdigest()[:16]
            cuerpo = "".join(
                json.dumps({**e, "_ingested_at_utc": t}, ensure_ascii=False, separators=(",", ":"))
                + "\n"
                for e, t in sorted(items, key=lambda x: x[0]["event_id"])
            )
            self.cliente.put_object(
                Bucket=self.bucket,
                Key=f"{self.prefijo}/fecha={fecha}/lote-{huella}.jsonl",
                Body=cuerpo.encode("utf-8"),
                ContentType="application/x-ndjson",
                ServerSideEncryption="AES256",
            )
            self.objetos_escritos += 1
        n = len(self._buffer)
        self._buffer.clear()
        return n

    def cerrar(self) -> None:
        self.volcar()


def leer_lineas(cliente: Any, bucket: str, prefijo: str) -> Iterator[dict]:
    """Todas las líneas de todos los lotes, sin quitar duplicados."""
    token = None
    while True:
        kw = {"Bucket": bucket, "Prefix": prefijo.strip("/") + "/"}
        if token:
            kw["ContinuationToken"] = token
        pagina = cliente.list_objects_v2(**kw)
        for obj in pagina.get("Contents", []):
            cuerpo = cliente.get_object(Bucket=bucket, Key=obj["Key"])["Body"].read()
            for linea in cuerpo.decode("utf-8").splitlines():
                if linea.strip():
                    yield json.loads(linea)
        if not pagina.get("IsTruncated"):
            return
        token = pagina["NextContinuationToken"]


def leer_unicos(cliente: Any, bucket: str, prefijo: str) -> dict[str, dict]:
    """Un evento por ``event_id`` (el de menor ``_ingested_at_utc``), como hace Silver."""
    unicos: dict[str, dict] = {}
    for e in leer_lineas(cliente, bucket, prefijo):
        previo = unicos.get(e["event_id"])
        if previo is None or e["_ingested_at_utc"] < previo["_ingested_at_utc"]:
            unicos[e["event_id"]] = e
    return unicos
