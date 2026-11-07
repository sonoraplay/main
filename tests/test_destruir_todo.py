"""EG-47 · `destruir-todo.sh` con `aws` y `terraform` simulados: orden y códigos de salida.

No toca AWS. Los ejecutables falsos dejan un registro de lo que se les pidió y devuelven lo que
cada prueba configura por variables de entorno.
"""

import os
import stat
import subprocess
from pathlib import Path

import pytest

RAIZ = Path(__file__).resolve().parents[1]
SCRIPT = RAIZ / "infra" / "scripts" / "destruir-todo.sh"

AWS_FALSO = """#!/usr/bin/env bash
echo "aws $*" >> "$REGISTRO"
case "$*" in
  *resourcegroupstaggingapi*) printf '%s' "${FAKE_ETIQUETADOS:-}" ;;
  *"iam list-roles"*) printf '%s' "${FAKE_ROLES:-}" ;;
  *"iam list-instance-profiles"*) printf '%s' "${FAKE_PERFILES:-}" ;;
  *"sts get-caller-identity"*) echo 123456789012 ;;
  *"describe-instances"*) echo "${FAKE_EC2:-0}" ;;
  *"describe-addresses"*) echo "${FAKE_EIP:-0}" ;;
  *"describe-nat-gateways"*) echo "${FAKE_NAT:-0}" ;;
  *"describe-volumes"*) echo "${FAKE_EBS:-0}" ;;
  *"describe-db-instances"*) echo "${FAKE_RDS:-0}" ;;
  *"describe-load-balancers"*) echo "${FAKE_ELB:-0}" ;;
  *"eks list-clusters"*) echo "${FAKE_EKS:-0}" ;;
esac
"""

TERRAFORM_FALSO = """#!/usr/bin/env bash
echo "terraform $*" >> "$REGISTRO"
if [[ "$*" == *destroy* && -n "${FAKE_TF_FALLA:-}" ]]; then exit 1; fi
"""


@pytest.fixture
def entorno(tmp_path):
    bin_ = tmp_path / "bin"
    bin_.mkdir()
    for nombre, cuerpo in (("aws", AWS_FALSO), ("terraform", TERRAFORM_FALSO)):
        f = bin_ / nombre
        f.write_text(cuerpo)
        f.chmod(f.stat().st_mode | stat.S_IEXEC)
    registro = tmp_path / "registro.txt"
    registro.write_text("")
    env = {**os.environ, "PATH": f"{bin_}:{os.environ['PATH']}", "REGISTRO": str(registro)}
    for k in [k for k in env if k.startswith("FAKE_")]:
        del env[k]
    return env, registro


def correr(entorno, *args, entrada=None, **extra):
    env, registro = entorno
    p = subprocess.run(
        ["bash", str(SCRIPT), *args],
        cwd=RAIZ,
        env={**env, **extra},
        input=entrada,
        capture_output=True,
        text=True,
        timeout=60,
    )
    return p, registro.read_text()


def destroys(registro: str) -> list[str]:
    return [linea for linea in registro.splitlines() if "terraform" in linea and "destroy" in linea]


def test_entorno_limpio_sale_con_0_y_destruye_eks_antes_que_el_entorno(entorno):
    p, reg = correr(entorno, "--yes")
    assert p.returncode == 0, p.stderr
    assert "OK: entorno destruido" in p.stdout
    d = destroys(reg)
    assert len(d) == 2 and "terraform/eks" in d[0] and "-chdir=infra/terraform " in d[1] + " "


def test_por_defecto_no_destruye_los_persistentes(entorno):
    _, reg = correr(entorno, "--yes")
    assert "terraform/ecr" not in reg and "terraform/presupuesto" not in reg


def test_con_persistentes_tambien_destruye_ecr_y_presupuesto(entorno):
    p, reg = correr(entorno, "--yes", "--persistentes")
    assert p.returncode == 0, p.stderr
    assert "terraform/ecr" in reg and "terraform/presupuesto" in reg and len(destroys(reg)) == 4


def test_dry_run_no_llama_a_terraform_ni_a_aws(entorno):
    p, reg = correr(entorno, "--dry-run")
    assert p.returncode == 0
    assert "no se tocó AWS" in p.stdout
    assert reg.strip() == ""


def test_sin_confirmar_cancela_y_no_destruye(entorno):
    p, reg = correr(entorno, entrada="no\n")
    assert p.returncode == 1 and "Cancelado" in p.stdout
    assert destroys(reg) == []


def test_confirmando_con_la_palabra_destruir_continua(entorno):
    p, reg = correr(entorno, entrada="destruir\n")
    assert p.returncode == 0 and len(destroys(reg)) == 2


def test_opcion_desconocida_sale_con_2(entorno):
    p, reg = correr(entorno, "--nada")
    assert p.returncode == 2 and reg.strip() == ""


@pytest.mark.parametrize(
    ("variable", "mensaje"),
    [
        ("FAKE_EC2", "EC2 vivas"),
        ("FAKE_EIP", "Elastic IP sin liberar"),
        ("FAKE_NAT", "NAT Gateways vivas"),
        ("FAKE_EBS", "Volúmenes EBS sueltos"),
        ("FAKE_RDS", "RDS vivas"),
        ("FAKE_ELB", "Balanceadores vivos"),
        ("FAKE_EKS", "Clústeres EKS vivos"),
    ],
)
def test_falla_si_queda_un_recurso_facturable(entorno, variable, mensaje):
    p, _ = correr(entorno, "--yes", **{variable: "1"})
    assert p.returncode == 1
    assert mensaje in p.stdout and "quedan recursos facturables" in p.stderr


def test_falla_si_la_api_de_etiquetas_ve_un_recurso_que_no_es_persistente(entorno):
    arn = "arn:aws:ec2:us-east-1:123456789012:instance/i-0abc"
    p, _ = correr(entorno, "--yes", FAKE_ETIQUETADOS=arn)
    assert p.returncode == 1 and arn in p.stdout


def test_el_bucket_del_estado_y_los_repositorios_de_ecr_no_cuentan_como_huerfanos(entorno):
    persistentes = (
        "arn:aws:s3:::sonoraplay-123-tfstate\tarn:aws:ecr:us-east-1:1:repository/sonoraplay/spark"
    )
    p, _ = correr(entorno, "--yes", FAKE_ETIQUETADOS=persistentes)
    assert p.returncode == 0, p.stdout


def test_falla_si_queda_un_rol_de_iam_del_proyecto(entorno):
    p, _ = correr(entorno, "--yes", FAKE_ROLES="sonoraplay-dev-spark")
    assert p.returncode == 1 and "sonoraplay-dev-spark" in p.stdout


def test_si_terraform_destroy_falla_el_script_aborta_sin_dar_ok(entorno):
    p, reg = correr(entorno, "--yes", FAKE_TF_FALLA="1")
    assert p.returncode != 0 and "OK: entorno destruido" not in p.stdout
    assert len(destroys(reg)) == 1  # se detiene en el primero que falla
