#!/usr/bin/env bash
# EG-47 · Destruye TODO el entorno facturable y comprueba que no queda nada (evita la
# penalización del −10 % por infraestructura viva).
#
# Uso:
#   infra/scripts/destruir-todo.sh --dry-run          # muestra lo que haría, no toca AWS
#   infra/scripts/destruir-todo.sh                    # pide confirmación
#   infra/scripts/destruir-todo.sh --yes              # sin preguntar
#   infra/scripts/destruir-todo.sh --yes --persistentes   # además: ECR, presupuesto y estado
#
# Por defecto NO borra lo persistente por diseño (ADR-0020): repositorios de ECR, el
# presupuesto/SNS y el bucket del estado. El día de la entrega usa --persistentes.
# Requisitos: AWS CLI v2 y Terraform con sesión en la cuenta, backend.hcl en infra/terraform.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
DRY=0; SI=0; PERSISTENTES=0
for a in "$@"; do
  case "$a" in
    --dry-run) DRY=1 ;;
    --yes) SI=1 ;;
    --persistentes) PERSISTENTES=1 ;;
    *) echo "Opción desconocida: $a" >&2; exit 2 ;;
  esac
done

cd "$(git rev-parse --show-toplevel)"
TF=infra/terraform

paso() { echo; echo "== $*"; }
run() {
  if [[ $DRY -eq 1 ]]; then echo "[dry-run] $*"; else "$@"; fi
}

if [[ $DRY -eq 0 && $SI -eq 0 ]]; then
  echo "Esto DESTRUYE el entorno de AWS (región $REGION)$([[ $PERSISTENTES -eq 1 ]] && echo ' y lo persistente')."
  read -r -p "Escribe 'destruir' para continuar: " r
  [[ "$r" == "destruir" ]] || { echo "Cancelado."; exit 1; }
fi

paso "0 · Sesión de AWS"
if [[ $DRY -eq 0 ]]; then
  aws sts get-caller-identity --query Account --output text >/dev/null \
    || { echo "Sin sesión de AWS (aws sso login)." >&2; exit 1; }
fi

paso "1 · EKS (si existe; EG-41)"
if [[ -d $TF/eks ]]; then
  run terraform -chdir=$TF/eks init -backend-config=../backend.hcl -input=false
  run terraform -chdir=$TF/eks destroy -auto-approve -input=false
else
  echo "No hay stack de EKS en el repositorio: nada que destruir."
fi

paso "2 · Entorno principal (VPC, NAT, RDS, S3, ECS, ALB, EC2)"
run terraform -chdir=$TF init -backend-config=backend.hcl -input=false
run terraform -chdir=$TF destroy -auto-approve -input=false

if [[ $PERSISTENTES -eq 1 ]]; then
  paso "3 · Persistentes: ECR y presupuesto"
  for d in ecr presupuesto; do
    run terraform -chdir=$TF/$d init -backend-config=../backend.hcl -input=false
    run terraform -chdir=$TF/$d destroy -auto-approve -input=false
  done
  echo "El bucket del estado (bootstrap) se destruye a mano al final: ver docs/operacion/runbook.md §9."
fi

paso "4 · Comprobación: no quedan recursos con Project=sonoraplay"
run "$TF/verificar-huerfanos.sh" "$REGION"

paso "5 · Recursos que la API de etiquetas no ve (cuestan dinero si quedan)"
if [[ $DRY -eq 0 ]]; then
  fallos=0
  n=$(aws ec2 describe-instances --region "$REGION" \
        --filters Name=instance-state-name,Values=pending,running,stopping,stopped \
        --query 'length(Reservations[].Instances[])' --output text)
  [[ "$n" == "0" ]] || { echo "EC2 vivas: $n"; fallos=1; }
  n=$(aws ec2 describe-addresses --region "$REGION" --query 'length(Addresses)' --output text)
  [[ "$n" == "0" ]] || { echo "Elastic IP sin liberar: $n"; fallos=1; }
  n=$(aws ec2 describe-nat-gateways --region "$REGION" \
        --filter Name=state,Values=pending,available \
        --query 'length(NatGateways)' --output text)
  [[ "$n" == "0" ]] || { echo "NAT Gateways vivas: $n"; fallos=1; }
  n=$(aws ec2 describe-volumes --region "$REGION" --filters Name=status,Values=available \
        --query 'length(Volumes)' --output text)
  [[ "$n" == "0" ]] || { echo "Volúmenes EBS sueltos: $n"; fallos=1; }
  n=$(aws rds describe-db-instances --region "$REGION" --query 'length(DBInstances)' --output text)
  [[ "$n" == "0" ]] || { echo "RDS vivas: $n"; fallos=1; }
  n=$(aws elbv2 describe-load-balancers --region "$REGION" --query 'length(LoadBalancers)' --output text)
  [[ "$n" == "0" ]] || { echo "Balanceadores vivos: $n"; fallos=1; }
  n=$(aws eks list-clusters --region "$REGION" --query 'length(clusters)' --output text)
  [[ "$n" == "0" ]] || { echo "Clústeres EKS vivos: $n"; fallos=1; }
  [[ $fallos -eq 0 ]] || { echo "FALLA: quedan recursos facturables (arriba)." >&2; exit 1; }
fi

echo
[[ $DRY -eq 0 ]] || { echo "Simulacro terminado: no se tocó AWS."; exit 0; }
echo "OK: entorno destruido. Guarda esta salida como evidencia y revisa Cost Explorer (Daily, por servicio) mañana."
