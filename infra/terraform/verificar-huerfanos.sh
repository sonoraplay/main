#!/usr/bin/env bash
# Criterio 1 de la EG-26: después de `terraform destroy` no queda ningún recurso con
# Project=sonoraplay, salvo el bucket del estado (bootstrap, persistente por ADR-0020).
#
# Uso: ./verificar-huerfanos.sh [region]
# La API de etiquetas puede mostrar durante unos minutos recursos recién borrados: si aparece
# alguno, vuelve a correrlo antes de investigar.
set -euo pipefail

region="${1:-us-east-1}"

restantes=$(
  aws resourcegroupstaggingapi get-resources \
    --region "$region" \
    --tag-filters Key=Project,Values=sonoraplay \
    --query 'ResourceTagMappingList[].ResourceARN' \
    --output text | tr '\t' '\n' | grep -v -- '-tfstate$' | grep -v '^$' || true
)

# IAM es global y la API de etiquetas no siempre lista roles ni perfiles: se revisan por nombre.
roles=$(
  aws iam list-roles \
    --query "Roles[?starts_with(RoleName, 'sonoraplay-')].RoleName" --output text
)
perfiles=$(
  aws iam list-instance-profiles \
    --query "InstanceProfiles[?starts_with(InstanceProfileName, 'sonoraplay-')].InstanceProfileName" \
    --output text
)
restantes=$(printf '%s\n%s\n%s\n' "$restantes" "$roles" "$perfiles" | tr '\t' '\n' | grep -v '^$' || true)

if [[ -n "$restantes" ]]; then
  echo "Recursos con Project=sonoraplay que siguen en $region:"
  echo "$restantes"
  exit 1
fi

echo "OK: no quedan recursos con Project=sonoraplay en $region (salvo el bucket del estado)."
