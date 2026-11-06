#!/usr/bin/env bash
# EG-27 / EG-52 · construye la imagen arm64 de uno o varios componentes y la sube a ECR con el
# SHA del commit como etiqueta. Mientras no exista el CD de la EG-40 (OIDC), se corre a mano.
#
# Uso:
#   infra/scripts/publicar-imagen.sh api-titulares
#   infra/scripts/publicar-imagen.sh api-contratos simulador consumidor     # varios, sin pasos manuales
#   infra/scripts/publicar-imagen.sh --todos                                 # todo lo que tiene Dockerfile
# Requisitos: Docker con buildx, AWS CLI v2 con sesión en la cuenta del proyecto, el stack
# infra/terraform/ecr aplicado y un árbol de trabajo sin cambios (la imagen debe ser el commit).
#
# `--todos` publica los componentes de ECS con Dockerfile propio. `spark` queda fuera hasta que
# exista su Dockerfile (EG-35); `seed` y `esqueleto` no son servicios de ECS.
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
PREFIJO="${ECR_PREFIJO:-sonoraplay}"
COMPONENTES_ECS=(api-titulares api-contratos simulador consumidor spark)

[[ $# -ge 1 ]] || { echo "Uso: $0 <servicio>... | --todos   (${COMPONENTES_ECS[*]})"; exit 2; }

cd "$(git rev-parse --show-toplevel)"

if [[ "$1" == "--todos" ]]; then
  SERVICIOS=()
  for c in "${COMPONENTES_ECS[@]}"; do
    if [[ -f "docker/${c}.Dockerfile" ]]; then SERVICIOS+=("$c"); else echo "Se omite $c: no tiene docker/${c}.Dockerfile todavía."; fi
  done
else
  SERVICIOS=("$@")
fi

# Falla antes de construir nada si algún Dockerfile no existe.
for s in "${SERVICIOS[@]}"; do
  [[ -f "docker/${s}.Dockerfile" ]] || { echo "No existe docker/${s}.Dockerfile"; exit 1; }
done

# `terraform init` reescribe los .terraform.lock.hcl (por ejemplo, para agregar hashes de la
# plataforma del CI). No entran en la imagen (el Dockerfile solo copia el código), así que no
# cuentan como "cambios sin commit".
if [[ -n "$(git status --porcelain --untracked-files=no -- . ':(exclude,glob)**/.terraform.lock.hcl')" ]]; then
  echo "ALTO: hay cambios sin commit; la etiqueta no correspondería al contenido de la imagen."
  exit 1
fi

SHA="$(git rev-parse --short=7 HEAD)"
CUENTA="$(aws sts get-caller-identity --query Account --output text)"
REGISTRO="${CUENTA}.dkr.ecr.${REGION}.amazonaws.com"
aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRO"

PUBLICADAS=()
for SERVICIO in "${SERVICIOS[@]}"; do
  IMAGEN="${REGISTRO}/${PREFIJO}/${SERVICIO}:${SHA}"
  if aws ecr describe-images --region "$REGION" --repository-name "${PREFIJO}/${SERVICIO}" \
       --image-ids imageTag="$SHA" >/dev/null 2>&1; then
    echo "Ya existe ${PREFIJO}/${SERVICIO}:${SHA} (las etiquetas son inmutables). Nada que hacer."
  else
    docker buildx build --platform linux/arm64 -f "docker/${SERVICIO}.Dockerfile" \
      -t "$IMAGEN" --provenance=false --push .
  fi
  PUBLICADAS+=("${PREFIJO}/${SERVICIO}:${SHA}")
done

echo
echo "Imágenes (arm64, etiqueta = SHA del commit):"
printf '  %s\n' "${PUBLICADAS[@]}"
echo "Despliegue de la API de sellos: terraform -chdir=infra/terraform apply -var api_titulares_imagen_tag=${SHA}"
