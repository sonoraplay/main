"""CA-10: strict labelled detection acceptance tests."""
import pytest

from sonoraplay.reglas.metricas_fraude import medir_ca10


def test_ca10_exact_thresholds_and_confusion_matrix():
    truth = {f"g{i}": "granja" for i in range(100)}
    truth.update({f"l{i}": "legitima" for i in range(100)})
    predicted = {key: True for key in truth if key.startswith("g")}
    predicted.update({key: False for key in truth if key.startswith("l")})
    for i in range(5):
        predicted[f"g{i}"] = False
    predicted["l0"] = True
    metrics = medir_ca10(truth, predicted)
    assert (metrics.tp, metrics.fn, metrics.fp, metrics.tn) == (95, 5, 1, 99)
    assert metrics.recall == 0.95
    assert metrics.tasa_falsos_positivos == 0.01
    assert metrics.cumple_ca10


def test_ca10_rejects_two_percent_false_positives():
    truth = {f"g{i}": "granja" for i in range(100)}
    truth.update({f"l{i}": "legitima" for i in range(100)})
    predicted = {key: key.startswith("g") for key in truth}
    predicted["l0"] = True
    predicted["l1"] = True
    metrics = medir_ca10(truth, predicted)
    assert metrics.tasa_falsos_positivos == 0.02
    assert not metrics.cumple_ca10


def test_ca10_never_accepts_missing_predictions_or_one_class_only():
    with pytest.raises(ValueError, match="mismas cuentas"):
        medir_ca10({"g": "granja", "l": "legitima"}, {"g": True})
    assert not medir_ca10({"g": "granja"}, {"g": True}).cumple_ca10
