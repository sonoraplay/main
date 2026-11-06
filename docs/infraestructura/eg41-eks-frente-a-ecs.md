---
title: "EG-41 · Un componente en EKS y comparación con ECS"
---

# EG-41 · `api-contratos` en EKS y comparación con ECS

**Estado: preparado, sin desplegar.** El stack Terraform pasa `fmt` y Checkov; `validate` lo corre el CI (no se pudo ejecutar localmente por falta de acceso al registro de Terraform). **No se ha creado ningún clúster**: el análisis de costos pide aprobación del gasto antes (ver [ADR-0018](../adr/0018-ecs-frente-a-eks.md)).

## Qué se agrega

| Pieza | Para qué |
|---|---|
| `infra/terraform/eks/` | Clúster EKS + 1 nodo ARM64 gestionado + KMS para secretos + regla `eks → rds:5432`. Estado propio (`sonoraplay/eks.tfstate`); el `destroy` no toca el entorno |
| `k8s/api-contratos/api-contratos.yaml` | Deployment y Service (ClusterIP) de la API F4; la imagen es la misma de ECS |
| `infra/scripts/destruir-todo.sh` | Ya destruye `eks/` primero y comprueba que no queden clústeres |

## Prueba (en la ventana del Sprint 5)

```bash
# 0. Con el entorno principal aplicado y la imagen publicada (infra/scripts/publicar-imagen.sh api-contratos).
terraform -chdir=infra/terraform/eks init -backend-config=../backend.hcl
terraform -chdir=infra/terraform/eks apply -var 'acceso_api_cidrs=["TU_IP/32"]'
$(terraform -chdir=infra/terraform/eks output -raw kubeconfig)

# 1. Secreto con la conexión (sale de SSM; no se versiona).
kubectl create secret generic api-contratos --from-literal=DATABASE_URL='postgresql+psycopg://…'

# 2. Desplegar con la imagen de ECR (la misma que usa ECS).
sed "s#__IMAGEN__#<cuenta>.dkr.ecr.us-east-1.amazonaws.com/sonoraplay/api-contratos:<sha>#" \
  k8s/api-contratos/api-contratos.yaml | kubectl apply -f -
kubectl rollout status deploy/api-contratos

# 3. Responder una petición (criterio 1).
kubectl port-forward svc/api-contratos 8000:80 &
curl -fsS http://localhost:8000/health

# 4. Destruir el mismo día (criterio 3).
terraform -chdir=infra/terraform/eks destroy -var 'acceso_api_cidrs=["TU_IP/32"]'
```

Guarda la salida de cada paso y el costo real de Cost Explorer como evidencia.

## Criterios de la EG-41

| # | Criterio | Estado |
|---|---|---|
| 1 | Un componente en EKS con Deployment y Service que responde | Manifiestos listos; **sin probar** |
| 2 | Misma imagen que ECS, desde ECR | Por diseño (mismo repositorio y etiqueta); **sin probar** |
| 3 | Creado y destruido con Terraform, solo en la ventana | Stack y script listos; **sin ejecutar** |
| 4 | Comparación de costo, complejidad y encaje + ADR-0018 | ADR escrito (Propuesto). Precio del plano de control de EKS verificado en la fuente oficial (0,10 USD por clúster-hora); faltan los precios de Fargate y del nodo, y el costo real de la ventana |
