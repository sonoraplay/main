"""EG-38 · Liquidación mensual: periodo, espera de ingesta, versiones nuevas y aviso de fallo."""

import os
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path
from subprocess import CalledProcessError

import psycopg
import pytest

from sonoraplay.orquestacion import liquidacion_mensual as liq

DDL = sorted(Path(__file__).resolve().parents[2].glob("db/ddl/00[1-5]_*.sql"))
OCT = date(2026, 10, 1)


@pytest.fixture
def conexion():
    """Esquema propio por prueba: aplica el DDL real y no toca lo que haya en la base."""
    url = os.environ.get("EG30_DATABASE_URL")
    if not url:
        pytest.skip("requiere EG30_DATABASE_URL (PostgreSQL)")
    esquema = f"t_{uuid.uuid4().hex[:8]}"
    with psycopg.connect(url.replace("postgresql+psycopg://", "postgresql://", 1)) as c:
        c.execute(f"CREATE SCHEMA {esquema}")
        c.execute(f"SET search_path TO {esquema}")
        for f in DDL:
            c.execute(f.read_text(encoding="utf-8"))
        c.commit()
        yield c
        c.rollback()
        c.execute(f"DROP SCHEMA {esquema} CASCADE")
        c.commit()


def publicar_version(conexion, periodo: date = OCT) -> uuid.UUID:
    i = uuid.uuid4()
    conexion.execute(
        "INSERT INTO liquidaciones (liquidacion_id, periodo, publicada_en) VALUES (%s,%s,now())",
        (i, periodo),
    )
    conexion.commit()
    return i


def test_el_dia_3_liquida_el_mes_anterior():
    assert liq.periodo_a_liquidar(datetime(2026, 11, 3, 6, tzinfo=UTC)) == OCT
    assert liq.periodo_a_liquidar(datetime(2027, 1, 3, 6, tzinfo=UTC)) == date(2026, 12, 1)
    assert liq.periodo_a_liquidar(date(2026, 3, 3)) == date(2026, 2, 1)


def test_requiere_el_mes_completo_mas_dos_dias_de_gracia():
    dias = liq.fechas_requeridas(OCT)
    assert dias[0] == date(2026, 10, 1) and dias[-1] == date(2026, 11, 2)
    assert len(dias) == 31 + 2


def test_espera_hasta_que_toda_la_ingesta_este_completa(conexion):
    dias = liq.fechas_requeridas(OCT)
    for d in dias[:-1]:
        liq.marcar_ingesta(conexion, d, "run")
    assert liq.ingesta_pendiente(conexion, OCT) == [dias[-1]]
    assert liq.ingesta_completa(conexion, OCT) is False
    liq.marcar_ingesta(conexion, dias[-1], "run")
    assert liq.ingesta_completa(conexion, OCT) is True


def test_marcar_ingesta_es_idempotente(conexion):
    liq.marcar_ingesta(conexion, OCT, "a")
    liq.marcar_ingesta(conexion, OCT, "b")
    filas = conexion.execute("SELECT count(*), max(run_id) FROM ingesta_diaria_estado").fetchone()
    assert filas == (1, "b")


def entorno_con(conexion, codigo: str) -> dict:
    """Comando que ejecuta ``codigo`` con el python actual (simula el job de liquidación)."""
    return {liq.VARIABLE_COMANDO: f'"{sys.executable}" -c "{codigo}" {{periodo}}'}


def test_sin_job_no_finge_liquidar(conexion):
    with pytest.raises(liq.LiquidacionNoConfigurada, match="EG-37"):
        liq.liquidar(OCT, conexion, "r1", entorno={})
    assert conexion.execute("SELECT count(*) FROM corridas_liquidacion").fetchone()[0] == 0


def test_cada_corrida_crea_una_version_nueva_y_conserva_las_anteriores(conexion, tmp_path):
    previa = publicar_version(conexion)
    url = os.environ["EG30_DATABASE_URL"]
    esquema = conexion.execute("SHOW search_path").fetchone()[0]
    job = (
        "import psycopg,uuid,sys;"
        f"c=psycopg.connect('{url}', options='-c search_path={esquema}');"
        'c.execute(\\"INSERT INTO liquidaciones(liquidacion_id,periodo,publicada_en) '
        "VALUES(%s,'2026-10-01',now())\\\",(uuid.uuid4(),));c.commit()"
    )
    env = entorno_con(conexion, job)
    r1 = liq.liquidar(OCT, conexion, "r1", entorno=env)
    r2 = liq.liquidar(OCT, conexion, "r2", entorno=env)
    versiones = {f[0] for f in conexion.execute("SELECT liquidacion_id FROM liquidaciones")}
    assert len(versiones) == 3 and previa in versiones
    assert r1["liquidacion_id"] != r2["liquidacion_id"]
    filas = conexion.execute(
        "SELECT estado, duracion_s IS NOT NULL, liquidacion_id IS NOT NULL "
        "FROM corridas_liquidacion ORDER BY corrida_id"
    ).fetchall()
    assert filas == [("ok", True, True)] * 2


def test_un_job_que_no_crea_version_falla_y_queda_registrado(conexion):
    publicar_version(conexion)
    with pytest.raises(liq.VersionNoCreada):
        liq.liquidar(OCT, conexion, "r1", entorno=entorno_con(conexion, "pass"))
    estado, detalle = conexion.execute(
        "SELECT estado, detalle FROM corridas_liquidacion"
    ).fetchone()
    assert estado == "error" and "VersionNoCreada" in detalle


def test_un_job_que_falla_se_registra_y_propaga(conexion):
    with pytest.raises(CalledProcessError):
        liq.liquidar(OCT, conexion, "r1", entorno=entorno_con(conexion, "raise SystemExit(3)"))
    assert conexion.execute("SELECT estado FROM corridas_liquidacion").fetchone() == ("error",)


def test_la_duracion_se_mide_contra_la_meta_de_una_hora(conexion):
    relojes = iter([0.0, 3601.0])
    publicar_version(conexion)
    job = entorno_con(conexion, "pass")
    with pytest.raises(liq.VersionNoCreada):
        liq.liquidar(OCT, conexion, "r1", entorno=job, reloj=lambda: next(relojes))
    assert (
        float(conexion.execute("SELECT duracion_s FROM corridas_liquidacion").fetchone()[0])
        == 3601.0
    )


class FakeSNS:
    def __init__(self):
        self.enviados = []

    def publish(self, **kw):
        self.enviados.append(kw)


def test_el_fallo_final_se_registra_y_se_notifica(caplog):
    sns = FakeSNS()
    ctx = {"dag_id": "d", "task_id": "liquidar_mes", "run_id": "r9", "exception": "boom"}
    with caplog.at_level("ERROR"):
        texto = liq.notificar_fallo(ctx, entorno={liq.VARIABLE_SNS: "arn:aws:sns:x"}, cliente=sns)
    assert "liquidar_mes" in texto and "boom" in caplog.text
    assert sns.enviados[0]["TopicArn"] == "arn:aws:sns:x"
    assert "r9" in sns.enviados[0]["Message"]


def test_sin_tema_sns_solo_registra(caplog):
    sns = FakeSNS()
    with caplog.at_level("ERROR"):
        liq.notificar_fallo({"exception": "x"}, entorno={}, cliente=sns)
    assert sns.enviados == [] and "Falló" in caplog.text


def test_marcar_guarda_el_run_de_silver_y_la_mensual_lo_lee(conexion):
    ultimo = liq.fechas_requeridas(OCT)[-1]
    liq.marcar_ingesta(conexion, ultimo, "airflow-1", "airflow-1.1")
    assert liq.silver_run_id_del_periodo(conexion, OCT) == "airflow-1.1"
    liq.marcar_ingesta(conexion, ultimo, "airflow-2", "airflow-2.2")  # re-proceso: actualiza
    assert liq.silver_run_id_del_periodo(conexion, OCT) == "airflow-2.2"


def test_liquidar_exige_silver_run_id_si_el_comando_lo_pide(conexion):
    env = {liq.VARIABLE_COMANDO: "echo {periodo} {silver_run_id}"}
    with pytest.raises(liq.SilverRunIdFaltante):
        liq.liquidar(OCT, conexion, "r", entorno=env)
