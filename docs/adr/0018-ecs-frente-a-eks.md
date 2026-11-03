# ADR-0018 · ECS Fargate como cómputo de la plataforma; EKS solo para una prueba comparativa

| Campo | Valor |
|---|---|
| Estado | **Propuesto** (la comparación de costo y la prueba en EKS están pendientes; ver §6) |
| Fecha | 2026-11-03 |
| Historia que lo origina | HU 32 · EG-41 |
| Responsable | Julián |
| Revisó | Pendiente |
| Referencias | Tema 19, [ADR-0001](0001-arquitectura-base-aws.md), [ADR-0012](0012-fargate-on-demand-spot-arm64.md), [ADR-0020](0020-ventanas-encendido-aws.md), EG-32 |

## 1. Contexto

Todo el cómputo de la plataforma corre en ECS Fargate ARM64 (ADR-0012). El tema 19 pide desplegar **un** componente en EKS y comparar. El análisis de costos (EG-32) dice expresamente que EKS se cotiza aparte y **no se aprovisiona sin que el equipo apruebe el gasto**.

## 2. Qué debe cumplir la decisión

- **Costo:** el menor justificable; el plano de control de EKS se cobra por hora aunque no corra nada.
- **Operación:** pocas personas y ventanas cortas (ADR-0020); `destroy` debe dejar cero recursos.
- **Requisito (EG-41):** un componente en EKS con Deployment y Service, la **misma imagen** de ECR que ECS, creado y destruido con Terraform solo en el Sprint 5 y la demo.
- **Equipo:** el flujo de despliegue ya existe para ECS (Terraform + `publicar-imagen.sh`).

## 3. Opciones consideradas

| Opción | A favor | En contra |
|---|---|---|
| **A · ECS Fargate para todo; EKS solo como prueba de una ventana (elegida)** | Sin plano de control que pagar; sin nodos que parchear; ya funciona; encaja con jobs que "corren y se apagan" (Spark) | Menos portable que Kubernetes; menos ecosistema (Helm, operadores) |
| B · Todo en EKS | Estándar de la industria, portable, ecosistema | Plano de control 24/7 mientras el entorno esté prendido, nodos que dimensionar y parchear, red de pods y RBAC que operar; no aporta un requisito del proyecto |
| C · Sin prueba de EKS | Cero costo | No cumple el tema 19 / EG-41 |

## 4. Decisión

ECS Fargate sigue siendo el cómputo del proyecto. EKS se levanta **una sola vez**, con un solo componente (`api-contratos`), mediante el stack efímero `infra/terraform/eks/` (estado propio, 1 nodo ARM64 `t4g.small`, secretos cifrados con KMS, API restringida a la IP del equipo) y los manifiestos de `k8s/api-contratos/`. Se destruye en cuanto termina la prueba (`infra/scripts/destruir-todo.sh` ya lo incluye).

## 5. Comparación

| Criterio | ECS Fargate | EKS (nodos gestionados) |
|---|---|---|
| Costo fijo | Ninguno | Plano de control por hora (precio de lista a confirmar en el Pricing Calculator) |
| Costo de cómputo | vCPU-hora + GB-hora por tarea, exacto por lo que corre | Instancias por hora, estén llenas o vacías |
| Tareas de operación | Definición de tarea + servicio | Versión de Kubernetes, AMI de nodos, CNI, RBAC / access entries, manifiestos, probes |
| Jobs batch (Spark) | `RunTask` desde Airflow, se apaga solo | Hay que añadir Jobs/operador y capacidad de nodos |
| Portabilidad | Específico de AWS | Alta |
| Encaje con el proyecto | Alto | Bajo: ningún requisito lo exige más allá del tema 19 |

Los números concretos de costo por hora de ambas opciones **no se afirman aquí**: se rellenan con la cotización del Pricing Calculator y con el costo real de la ventana (EG-48).

## 6. Pendiente de comprobar

Este ADR no afirma que nada de lo siguiente haya ocurrido:

1. Aprobación del gasto de EKS por el equipo.
2. `terraform apply` del stack `eks/` y `kubectl get pods` con el pod `Ready`.
3. Una petición `GET /health` respondida por el Service (port-forward).
4. Costo real de la ventana, medido en Cost Explorer.
5. `destroy` y verificación de que no queda nada.
