"""EG-33 criterio 5 · Las métricas llegan a CloudWatch y nunca tumban el consumo."""

from types import SimpleNamespace

from sonoraplay.streaming.metricas import NAMESPACE, PublicadorMetricas, profundidades


class CloudWatchFalso:
    def __init__(self, falla=False):
        self.llamadas = []
        self.falla = falla

    def put_metric_data(self, Namespace, MetricData):  # noqa: N803
        if self.falla:
            raise OSError("sin red")
        self.llamadas.append((Namespace, MetricData))


def test_publica_en_el_espacio_de_nombres_con_la_cola_como_dimension():
    cw = CloudWatchFalso()
    p = PublicadorMetricas(cw, "eventos.f2")
    assert p.publicar({"ProfundidadCola": 120, "EventosADLQ": 3}) is True
    ns, datos = cw.llamadas[0]
    assert ns == NAMESPACE == "SonoraPlay/Mensajeria"
    assert {d["MetricName"]: d["Value"] for d in datos} == {
        "ProfundidadCola": 120.0,
        "EventosADLQ": 3.0,
    }
    assert all(d["Dimensions"] == [{"Name": "Cola", "Value": "eventos.f2"}] for d in datos)


def test_si_cloudwatch_falla_no_lanza():
    assert PublicadorMetricas(CloudWatchFalso(falla=True), "q").publicar({"X": 1}) is False


def test_profundidades_leen_cola_y_dlq_sin_consumir():
    class Canal:
        def queue_declare(self, queue, passive):
            assert passive is True  # solo mira, no crea ni cambia nada
            n = {"eventos.f2": 42, "eventos.f2.dlq": 5}[queue]
            return SimpleNamespace(method=SimpleNamespace(message_count=n))

    assert profundidades(Canal(), "eventos.f2", "eventos.f2.dlq") == {
        "ProfundidadCola": 42,
        "ProfundidadDLQ": 5,
    }
