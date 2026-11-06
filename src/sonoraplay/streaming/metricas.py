"""Métricas del consumidor para CloudWatch (EG-33, criterio 5).

Publica en el espacio ``SonoraPlay/Mensajeria``: profundidad de la cola y de la DLQ, y contadores
del consumidor (guardados, duplicados, enviados a la DLQ y fallos de escritura en S3). Nunca debe
romper el consumo: si CloudWatch falla, se registra y se sigue.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any

log = logging.getLogger(__name__)

NAMESPACE = "SonoraPlay/Mensajeria"


class PublicadorMetricas:
    def __init__(self, cliente: Any, cola: str, namespace: str = NAMESPACE) -> None:
        self.cliente = cliente
        self.cola = cola
        self.namespace = namespace

    def publicar(self, valores: dict[str, float], unidad: str = "Count") -> bool:
        """Envía las métricas. Devuelve False (y no lanza) si CloudWatch no responde."""
        ahora = datetime.now(UTC)
        datos = [
            {
                "MetricName": nombre,
                "Dimensions": [{"Name": "Cola", "Value": self.cola}],
                "Timestamp": ahora,
                "Value": float(valor),
                "Unit": unidad,
            }
            for nombre, valor in valores.items()
        ]
        try:
            for i in range(0, len(datos), 1000):  # límite de la API por llamada
                self.cliente.put_metric_data(
                    Namespace=self.namespace, MetricData=datos[i : i + 1000]
                )
        except Exception as exc:  # noqa: BLE001 - las métricas no pueden tumbar el consumidor
            log.warning("No se pudieron publicar las métricas: %s", exc)
            return False
        return True


def profundidades(canal: Any, cola: str, cola_dlq: str) -> dict[str, float]:
    """Mensajes en la cola y en la DLQ, sin consumir (declaración pasiva)."""
    return {
        "ProfundidadCola": canal.queue_declare(queue=cola, passive=True).method.message_count,
        "ProfundidadDLQ": canal.queue_declare(queue=cola_dlq, passive=True).method.message_count,
    }
