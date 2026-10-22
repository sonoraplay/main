"""Almacén Bronze de F2 en JSON Lines, idempotente por ``event_id`` (EG-29, criterio 3)."""

import json
import os
from pathlib import Path


class AlmacenBronze:
    """Agrega eventos a un archivo JSON Lines y los fuerza a disco antes de confirmar.

    - **Durable:** cada escritura hace ``flush`` y ``os.fsync``. El consumidor manda el ACK solo
      después de que ``guardar`` retorna, así que un ACK nunca precede al dato en disco.
    - **Idempotente:** al abrir carga los ``event_id`` ya guardados. Si un mensaje llega dos
      veces (se guardó, pero el consumidor murió antes del ACK), la segunda vez no se escribe.
      Así, tras un reinicio, guardados = publicados y hay 0 duplicados.
    - Una línea final incompleta (corte a mitad de una escritura) se descarta al abrir: ese
      mensaje no tenía ACK y RabbitMQ lo vuelve a entregar.
    """

    def __init__(self, ruta: Path) -> None:
        self.ruta = ruta
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        self.vistos: set[str] = set()
        self._reparar_y_cargar()
        self._archivo = self.ruta.open("a", encoding="utf-8")

    def _reparar_y_cargar(self) -> None:
        if not self.ruta.exists():
            return
        datos = self.ruta.read_bytes()
        validos = datos if datos.endswith(b"\n") or not datos else datos[: datos.rfind(b"\n") + 1]
        if validos != datos:
            self.ruta.write_bytes(validos)
        for linea in validos.decode("utf-8").splitlines():
            if linea.strip():
                self.vistos.add(json.loads(linea)["event_id"])

    def guardar(self, evento: dict) -> bool:
        """Guarda el evento si es nuevo. Devuelve False si era un duplicado (no escribe nada)."""
        event_id = evento["event_id"]
        if event_id in self.vistos:
            return False
        self._archivo.write(json.dumps(evento, ensure_ascii=False, separators=(",", ":")) + "\n")
        self._archivo.flush()
        os.fsync(self._archivo.fileno())
        self.vistos.add(event_id)
        return True

    def cerrar(self) -> None:
        self._archivo.close()
