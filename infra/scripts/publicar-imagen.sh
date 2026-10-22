#!/usr/bin/env bash
# EG-27 · criterio 1: construye la imagen arm64 de un componente y la sube a ECR con el SHA
# del commit como etiqueta. Mientras no exista el CD de la EG-40 (OIDC), se corre a mano.
#
# Uso: infra/scripts/publicar-imagen.sh api-titulares
# Requisitos: Docker con buildx, AWS CLI v2 con sesión en la cuenta del proyecto, el stack
# infra/terraform/ecr aplicado y un árbol de trabajo sin cambios (la imagen debe ser el commit).
set -euo pipefail

SERVICIO="${1:?Uso: $0 <servicio>   (api-titulares, api-contratos, ...)}"
REGION="${AWS_REGION:-us-east-1}"
PREFIJO="${ECR_PREFIJO:-sonoraplay}"
DOCKERFILE="docker/${SERVICIO}.Dockerfile"

cd "$(git rev-parse --show-toplevel)"
[[ -f "$DOCKERFILE" ]] || { echo "No existe $DOCKERFILE"; exit 1; }
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
IMAGEN="${REGISTRO}/${PREFIJO}/${SERVICIO}:${SHA}"

if aws ecr describe-images --region "$REGION" --repository-name "${PREFIJO}/${SERVICIO}" \
     --image-ids imageTag="$SHA" >/dev/null 2>&1; then
  echo "Ya existe ${PREFIJO}/${SERVICIO}:${SHA} (las etiquetas son inmutables). Nada que hacer."
else
  aws ecr get-login-password --region "$REGION" | docker login --username AWS --password-stdin "$REGISTRO"
  docker buildx build --platform linux/arm64 -f "$DOCKERFILE" -t "$IMAGEN" --provenance=false --push .
fi

echo
echo "Imagen: ${PREFIJO}/${SERVICIO}:${SHA}"
echo "Despliegue: terraform -chdir=infra/terraform apply -var api_titulares_imagen_tag=${SHA}"
