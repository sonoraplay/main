"""EG-37 · El lanzador de jobs de Spark en ECS: éxito solo con exitCode 0."""

import pytest

from sonoraplay.orquestacion import ecs_job as e

ARN = "arn:aws:ecs:us-east-1:1:task/c/abc"
ENV = {
    "ECS_CLUSTER": "c",
    "ECS_SPARK_FAMILY": "sonoraplay-dev-spark",
    "ECS_SUBNETS": "s1,s2",
    "ECS_SECURITY_GROUPS": "sg1",
}


class Waiter:
    def __init__(self, error=None):
        self.error, self.llamadas = error, []

    def wait(self, **kw):
        self.llamadas.append(kw)
        if self.error:
            raise self.error


class Cliente:
    def __init__(self, run=None, exit_code=0, waiter_error=None, contenedores=None):
        self.run = run if run is not None else {"tasks": [{"taskArn": ARN}], "failures": []}
        self.exit_code = exit_code
        self.contenedores = contenedores
        self.waiter = Waiter(waiter_error)
        self.parado = []
        self.run_kw = None

    def run_task(self, **kw):
        self.run_kw = kw
        return self.run

    def get_waiter(self, nombre):
        assert nombre == "tasks_stopped"
        return self.waiter

    def describe_tasks(self, **_):
        cont = (
            self.contenedores
            if self.contenedores is not None
            else [{"name": "spark", "exitCode": self.exit_code}]
        )
        return {"tasks": [{"containers": cont, "stoppedReason": "Essential container exited"}]}

    def stop_task(self, **kw):
        self.parado.append(kw)


def _lanzar(cliente, **kw):
    args = dict(
        cluster="c",
        familia="f",
        subredes=["s1"],
        security_groups=["sg1"],
        comando=["python", "-m", "x"],
    )
    return e.ejecutar_job(cliente, **{**args, **kw})


def test_exito_con_exit_code_0_y_comando_sobrescrito():
    c = Cliente()
    assert _lanzar(c) == ARN
    assert c.run_kw["overrides"]["containerOverrides"] == [
        {"name": "spark", "command": ["python", "-m", "x"]}
    ]
    assert c.run_kw["networkConfiguration"]["awsvpcConfiguration"]["assignPublicIp"] == "DISABLED"


@pytest.mark.parametrize("codigo", [1, 137, None])
def test_un_exit_code_distinto_de_0_falla(codigo):
    with pytest.raises(e.EcsJobFallo, match="exitCode"):
        _lanzar(Cliente(exit_code=codigo))


def test_sin_contenedor_spark_en_la_tarea_falla():
    with pytest.raises(e.EcsJobFallo):
        _lanzar(Cliente(contenedores=[{"name": "otro", "exitCode": 0}]))


def test_run_task_con_failures_no_espera_nada():
    c = Cliente(run={"tasks": [], "failures": [{"reason": "RESOURCE:CPU"}]})
    with pytest.raises(e.EcsJobFallo, match="no arrancó"):
        _lanzar(c)
    assert c.waiter.llamadas == []


def test_plazo_vencido_detiene_la_tarea_y_falla():
    c = Cliente(waiter_error=RuntimeError("Max attempts exceeded"))
    with pytest.raises(e.EcsJobFallo, match="a tiempo"):
        _lanzar(c, plazo_s=60, espera_s=20)
    assert c.parado and c.parado[0]["task"] == ARN
    assert c.waiter.llamadas[0]["WaiterConfig"] == {"Delay": 20, "MaxAttempts": 3}


def test_exige_comando_y_red():
    with pytest.raises(ValueError):
        _lanzar(Cliente(), comando=[])
    with pytest.raises(ValueError):
        _lanzar(Cliente(), subredes=[])


def test_cli_codigos_de_salida():
    assert e.main(["--", "python", "-m", "x"], entorno=ENV, cliente=Cliente()) == 0
    assert e.main(["--", "python"], entorno=ENV, cliente=Cliente(exit_code=1)) == 1
    assert e.main(["python"], entorno=ENV, cliente=Cliente()) == 2  # falta --
    assert e.main(["--", "python"], entorno={}, cliente=Cliente()) == 2  # faltan variables
