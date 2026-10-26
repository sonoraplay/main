#!/usr/bin/env bash
# EG-27 · verificación de los criterios 2 a 5 después del apply. Solo lee, salvo el paso 4,
# que detiene UNA tarea para comprobar que ECS la reemplaza.
#
# Uso: infra/scripts/verificar-eg27.sh   (desde la raíz del repo, con sesión de AWS)
set -euo pipefail

REGION="${AWS_REGION:-us-east-1}"
TF="infra/terraform"
CLUSTER="$(terraform -chdir=$TF output -raw ecs_cluster)"
URL="$(terraform -chdir=$TF output -raw api_titulares_url)"
SERVICIO="api-titulares"
[[ -n "$URL" ]] || { echo "La API no está desplegada (falta api_titulares_imagen_tag)."; exit 1; }

echo "== Criterio 2 · definición de tarea versionada y red privada"
terraform -chdir=$TF output -raw api_titulares_task_definition; echo
aws ecs describe-services --region "$REGION" --cluster "$CLUSTER" --services "$SERVICIO" \
  --query 'services[0].{taskDefinition:taskDefinition,deseadas:desiredCount,corriendo:runningCount,ipPublica:networkConfiguration.awsvpcConfiguration.assignPublicIp,subredes:networkConfiguration.awsvpcConfiguration.subnets}' \
  --output json
aws ec2 describe-subnets --region "$REGION" --subnet-ids $(aws ecs describe-services --region "$REGION" \
  --cluster "$CLUSTER" --services "$SERVICIO" \
  --query 'services[0].networkConfiguration.awsvpcConfiguration.subnets' --output text) \
  --query 'Subnets[].[SubnetId,Tags[?Key==`Tier`]|[0].Value]' --output text

echo "== Criterio 3 · /health por la URL del ALB y estado del target group"
curl -sS -o /dev/null -w "GET $URL/health -> HTTP %{http_code}\n" "$URL/health"
TG="$(aws elbv2 describe-target-groups --region "$REGION" --names sonoraplay-dev-api-titulares \
  --query 'TargetGroups[0].TargetGroupArn' --output text)"
aws elbv2 describe-target-groups --region "$REGION" --target-group-arns "$TG" \
  --query 'TargetGroups[0].{ruta:HealthCheckPath,codigo:Matcher.HttpCode}' --output json
aws elbv2 describe-target-health --region "$REGION" --target-group-arn "$TG" \
  --query 'TargetHealthDescriptions[].[Target.Id,TargetHealth.State]' --output text

echo "== Criterio 4 · se detiene una tarea y ECS la reemplaza"
VIEJA="$(aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --service-name "$SERVICIO" \
  --query 'taskArns[0]' --output text)"
aws ecs stop-task --region "$REGION" --cluster "$CLUSTER" --task "$VIEJA" \
  --reason "EG-27 criterio 4: prueba de reemplazo" --query 'task.lastStatus' --output text
aws ecs wait services-stable --region "$REGION" --cluster "$CLUSTER" --services "$SERVICIO"
aws ecs list-tasks --region "$REGION" --cluster "$CLUSTER" --service-name "$SERVICIO" \
  --query 'taskArns' --output text | tr '\t' '\n' | sed "s#^#  corriendo: #"
echo "  detenida:  $VIEJA"
curl -sS -o /dev/null -w "GET $URL/health -> HTTP %{http_code}\n" "$URL/health"

echo "== Criterio 5 · logs en CloudWatch con retención de 7 días"
aws logs describe-log-groups --region "$REGION" --log-group-name-prefix "/ecs/sonoraplay/$SERVICIO" \
  --query 'logGroups[].[logGroupName,retentionInDays]' --output text
aws logs tail "/ecs/sonoraplay/$SERVICIO" --region "$REGION" --since 15m | tail -5
