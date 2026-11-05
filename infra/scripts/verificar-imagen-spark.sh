#!/usr/bin/env bash
# Verifica (solo lectura) que la imagen de Spark quedó bien publicada en ECR y que no se tocó nada más.
# Uso en CloudShell:  bash verificar-imagen-spark.sh [TAG] [REGION]
#   TAG    por defecto d4f06f6 (commit de feature/EG-37-imagen-spark-ecs)
#   REGION por defecto la de la sesión (AWS_REGION / AWS_DEFAULT_REGION)
# No crea, modifica ni borra nada: solo describe recursos. Sale con código 1 si algo no cuadra.
set -uo pipefail

TAG="${1:-d4f06f6}"
REGION="${2:-${AWS_REGION:-${AWS_DEFAULT_REGION:-}}}"
PREFIJO="sonoraplay"
FALLOS=0
[ -n "$REGION" ] || { echo "Indica la región: bash $0 $TAG <region>"; exit 2; }
AWSR=(aws --region "$REGION")

ok()   { echo "  [OK]    $*"; }
mal()  { echo "  [FALLA] $*"; FALLOS=$((FALLOS + 1)); }
aviso(){ echo "  [AVISO] $*"; }

echo "== Cuenta y región"
CUENTA=$("${AWSR[@]}" sts get-caller-identity --query Account --output text 2>/dev/null) || { echo "Sin credenciales de AWS"; exit 2; }
echo "  cuenta=$CUENTA región=$REGION tag=$TAG"

echo "== 1. Imagen $PREFIJO/spark:$TAG"
IMG=$("${AWSR[@]}" ecr describe-images --repository-name "$PREFIJO/spark" \
      --image-ids imageTag="$TAG" --output json 2>/dev/null) || IMG=""
if [ -z "$IMG" ]; then
  mal "no existe la etiqueta $TAG en $PREFIJO/spark"
else
  python3 - "$IMG" <<'PY'
import json, sys
d = json.loads(sys.argv[1])["imageDetails"][0]
print("  digest :", d["imageDigest"])
print("  tamaño :", round(d.get("imageSizeInBytes", 0) / 1e6, 1), "MB")
print("  subida :", d.get("imagePushedAt"))
print("  etiquetas:", d.get("imageTags"))
PY
  ok "la etiqueta existe"
fi

echo "== 2. Arquitectura (debe ser arm64)"
MAN=$("${AWSR[@]}" ecr batch-get-image --repository-name "$PREFIJO/spark" \
      --image-ids imageTag="$TAG" --query 'images[0].imageManifest' --output text 2>/dev/null) || MAN=""
if [ -z "$MAN" ] || [ "$MAN" = "None" ]; then
  mal "no pude leer el manifiesto"
else
  CFG=$(python3 -c 'import json,sys; m=json.loads(sys.argv[1]); print(m["config"]["digest"] if "config" in m else "INDICE")' "$MAN" 2>/dev/null)
  if [ "$CFG" = "INDICE" ] || [ -z "$CFG" ]; then
    aviso "el manifiesto es un índice multi-arquitectura; revisa con: docker buildx imagetools inspect"
  else
    URL=$("${AWSR[@]}" ecr get-download-url-for-layer --repository-name "$PREFIJO/spark" \
          --layer-digest "$CFG" --query downloadUrl --output text 2>/dev/null)
    ARQ=$(curl -fsS "$URL" 2>/dev/null | python3 -c 'import json,sys; c=json.load(sys.stdin); print(c.get("architecture","?"), c.get("os","?"))' 2>/dev/null)
    if [ "$ARQ" = "arm64 linux" ]; then ok "arquitectura $ARQ"; else mal "arquitectura inesperada: ${ARQ:-no se pudo leer}"; fi
  fi
fi

echo "== 3. Los demás repositorios no cambiaron"
declare -A ESPERADO=( [api-contratos]=9ae8d2c [simulador]=9ae8d2c [consumidor]=9ae8d2c [api-titulares]=d44fd1d )
for r in "${!ESPERADO[@]}"; do
  TAGS=$("${AWSR[@]}" ecr describe-images --repository-name "$PREFIJO/$r" \
         --query 'imageDetails[].imageTags[]' --output text 2>/dev/null)
  if [ "$TAGS" = "${ESPERADO[$r]}" ]; then ok "$r → $TAGS"; else mal "$r tiene [$TAGS], se esperaba [${ESPERADO[$r]}]"; fi
done
N=$("${AWSR[@]}" ecr describe-images --repository-name "$PREFIJO/spark" --query 'length(imageDetails)' --output text 2>/dev/null)
[ "$N" = "1" ] && ok "spark tiene exactamente 1 imagen" || aviso "spark tiene $N imágenes"

echo "== 4. Limpieza de CodeBuild"
if "${AWSR[@]}" codebuild batch-get-projects --names sonoraplay-imagenes --query 'projects[0].name' --output text 2>/dev/null | grep -q sonoraplay-imagenes; then
  mal "el proyecto de CodeBuild sonoraplay-imagenes todavía existe"
else ok "el proyecto sonoraplay-imagenes ya no existe"; fi
ROL=$(aws iam list-roles --query "Roles[?contains(RoleName, 'imagenes')].RoleName" --output text 2>/dev/null)
[ -z "$ROL" ] && ok "no quedan roles *imagenes*" || mal "quedan roles: $ROL"
LG=$("${AWSR[@]}" logs describe-log-groups --log-group-name-prefix /aws/codebuild/sonoraplay-imagenes \
     --query 'logGroups[].logGroupName' --output text 2>/dev/null)
[ -z "$LG" ] && ok "no queda el grupo de logs" || aviso "queda el grupo de logs $LG (decide si borrarlo)"

echo
if [ "$FALLOS" -eq 0 ]; then echo "RESULTADO: todo cuadra."; else echo "RESULTADO: $FALLOS comprobación(es) fallaron."; exit 1; fi
