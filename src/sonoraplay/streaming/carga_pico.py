"""Carga pico hacia RabbitMQ a un ritmo fijo (EG-51, criterio 1 · CT-06).

Publica con las mismas garantías que el productor de la EG-29 (mensajes persistentes, publisher
confirms y ``mandatory``) y mide cuántos eventos por segundo confirmó el broker de verdad.
"""

import math
import time
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field

from sonoraplay.streaming.config import StreamingConfig
from sonoraplay.streaming.productor import publicar_linea
from sonoraplay.streaming.topologia import declarar

TASA_MINIMA = 100.0  # CT-06: al menos 100 eventos/s de media
DURACION_MINIMA = 60.0  # durante al menos 60 s


@dataclass(frozen=True)
class ResultadoPico:
    publicados: int
    segundos: float
    tasa_objetivo: float
    por_segundo: dict[int, int] = field(default_factory=dict)

    @property
    def tasa_media(self) -> float:
        return self.publicados / self.segundos if self.segundos else 0.0

    def cumple(self, tasa: float = TASA_MINIMA, duracion: float = DURACION_MINIMA) -> bool:
        return self.segundos >= duracion and self.tasa_media >= tasa

    def como_dict(self) -> dict:
        completos = [n for s, n in self.por_segundo.items() if s < int(self.segundos)]
        return {
            "resultado": "OK" if self.cumple() else "FALLA",
            "publicados_confirmados": self.publicados,
            "segundos": round(self.segundos, 3),
            "tasa_objetivo": self.tasa_objetivo,
            "tasa_media": round(self.tasa_media, 2),
            "min_por_segundo": min(completos, default=0),
            "max_por_segundo": max(completos, default=0),
        }


def publicar_a_ritmo(
    publicar: Callable[[str], object],
    lineas: Sequence[str],
    tasa: float,
    duracion: float,
    reloj: Callable[[], float] = time.monotonic,
    dormir: Callable[[float], None] = time.sleep,
) -> ResultadoPico:
    """Publica a `tasa` eventos/s durante `duracion` segundos y cuenta lo publicado por segundo.

    En cada instante `t` se lleva publicado ``floor(t · tasa) + 1``: si el broker se atrasa, se
    recupera en ráfaga sin pasarse del total. `publicar` debe bloquear hasta la confirmación, así
    que lo contado es lo que el broker ya guardó. `reloj` y `dormir` se inyectan en las pruebas.
    """
    if tasa <= 0 or duracion <= 0:
        raise ValueError("tasa y duracion deben ser positivas")
    necesarias = math.ceil(tasa * duracion)
    if len(lineas) < necesarias:
        raise ValueError(f"hacen falta {necesarias} eventos para {duracion} s a {tasa}/s")
    por_segundo: Counter[int] = Counter()
    enviados = 0
    inicio = reloj()
    while (t := reloj() - inicio) < duracion:
        objetivo = min(len(lineas), math.floor(t * tasa) + 1)
        while enviados < objetivo:
            publicar(lineas[enviados])
            enviados += 1
            por_segundo[int(reloj() - inicio)] += 1
        dormir(min(0.005, max(0.0, (enviados / tasa) - (reloj() - inicio))))
    return ResultadoPico(enviados, reloj() - inicio, tasa, dict(sorted(por_segundo.items())))


def publicar_pico(
    cfg: StreamingConfig, lineas: Sequence[str], tasa: float, duracion: float
) -> ResultadoPico:
    """Abre un canal con confirmaciones y publica `lineas` a ritmo fijo en la cola F2."""
    import pika

    conexion = pika.BlockingConnection(pika.URLParameters(cfg.url))
    try:
        canal = conexion.channel()
        declarar(canal, cfg)
        canal.confirm_delivery()

        def publicar(linea: str) -> bool:
            return publicar_linea(canal, cfg, linea)

        return publicar_a_ritmo(publicar, lineas, tasa, duracion)
    finally:
        conexion.close()
