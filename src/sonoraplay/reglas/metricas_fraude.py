"""CA-10: deterministic, auditable fraud-detection metrics from EG-51 account labels.

This evaluator never changes RN-03 thresholds or Gold settlement outcomes.
"""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class MetricasFraude:
    tp: int
    fp: int
    tn: int
    fn: int

    @property
    def recall(self) -> float:
        return self.tp / (self.tp + self.fn) if self.tp + self.fn else 0.0

    @property
    def tasa_falsos_positivos(self) -> float:
        return self.fp / (self.fp + self.tn) if self.fp + self.tn else 0.0

    @property
    def cumple_ca10(self) -> bool:
        return self.tp + self.fn > 0 and self.fp + self.tn > 0 and (
            self.recall >= 0.95 and self.tasa_falsos_positivos < 0.02
        )


def medir_ca10(
    etiquetas: Mapping[str, str],
    sospechosas: Mapping[str, bool],
) -> MetricasFraude:
    """Compare one UTC-month prediction per account against independent EG-51 truth.

    Strictly require identical account populations: missing predictions would
    otherwise inflate recall or hide false positives.
    """
    if not etiquetas or set(etiquetas) != set(sospechosas):
        raise ValueError("CA-10: etiquetas y predicciones deben cubrir las mismas cuentas")
    if set(etiquetas.values()) - {"granja", "legitima"}:
        raise ValueError("CA-10: etiqueta desconocida")
    if any(type(v) is not bool for v in sospechosas.values()):
        raise ValueError("CA-10: prediccion no booleana")
    tp = fp = tn = fn = 0
    for cuenta, etiqueta in etiquetas.items():
        pred = sospechosas[cuenta]
        if etiqueta == "granja":
            tp += int(pred)
            fn += int(not pred)
        else:
            fp += int(pred)
            tn += int(not pred)
    return MetricasFraude(tp=tp, fp=fp, tn=tn, fn=fn)
