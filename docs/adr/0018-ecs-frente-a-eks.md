# ADR-0018 · ECS Fargate como cómputo de la plataforma; EKS preparado y comparado, sin desplegar

| Campo | Valor |
|---|---|
| Estado | **Aceptado** por Julián el 2026-11-07, con una salvedad: **no se desplegó EKS**; el requisito se cierra como comparación documentada (ver §7) |
| Fecha | 2026-11-03 |
| Historia que lo origina | HU 32 · EG-41 |
| Responsable | Julián |
| Revisó | Pendiente de revisión por otra persona del equipo |
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
| Costo fijo | Ninguno | Plano de control: **0,10 USD por clúster-hora** con versión de Kubernetes en soporte estándar (0,60 USD en soporte extendido). Fuente: [Amazon EKS Pricing](https://aws.amazon.com/eks/pricing/), consultada el 2026-11-03 |
| Costo de cómputo | vCPU-hora + GB-hora por tarea, exacto por lo que corre | Instancias por hora, estén llenas o vacías |
| Tareas de operación | Definición de tarea + servicio | Versión de Kubernetes, AMI de nodos, CNI, RBAC / access entries, manifiestos, probes |
| Jobs batch (Spark) | `RunTask` desde Airflow, se apaga solo | Hay que añadir Jobs/operador y capacidad de nodos |
| Portabilidad | Específico de AWS | Alta |
| Encaje con el proyecto | Alto | Bajo: ningún requisito lo exige más allá del tema 19 |

Solo el precio del plano de control de EKS está verificado en la fuente oficial. Con él, una ventana de *H* horas cuesta *H* × 0,10 USD de plano de control **más** las horas del nodo `t4g.small` y su disco; por ejemplo, 4 h son 0,40 USD de plano de control (el nodo y el disco se suman aparte). Los precios de Fargate (Spot y On-Demand) y del nodo **no se afirman aquí**: se rellenan con el Pricing Calculator y con el costo real de la ventana (EG-48). Elegir una versión de Kubernetes que ya esté en soporte extendido multiplicaría por seis el plano de control; por eso la versión del stack se verifica antes de aplicar.

## 6. Lo que NO se comprobó (queda así por la decisión de §7)

Este ADR no afirma que nada de lo siguiente haya ocurrido:

1. Aprobación del gasto de EKS por el equipo.
2. `terraform apply` del stack `eks/` y `kubectl get pods` con el pod `Ready`.
3. Una petición `GET /health` respondida por el Service (port-forward).
4. Costo real de la ventana, medido en Cost Explorer.
5. `destroy` y verificación de que no queda nada.

## 7. Decisión de cierre (2026-11-07): comparación documentada, sin desplegar EKS

**Decisión de Julián:** EG-41 se cierra como **comparación documentada**. El stack `infra/terraform/eks/`, los manifiestos de `k8s/api-contratos/` y la guía de prueba quedan listos y validados por el CI (`terraform validate` y Checkov), pero **no se aprovisiona ningún clúster**.

**Por qué:**
- Ningún requisito del proyecto, aparte del tema 19, exige Kubernetes; ECS Fargate ya cubre todo el cómputo (ADR-0012).
- El costo fijo del plano de control no se justifica para una demostración (cifras de abajo).
- Cada ventana de AWS tiene un riesgo de costo y de recursos huérfanos; el presupuesto es de 50 USD.

**Costo, de la lista oficial de precios de AWS (us-east-1, bajo demanda; EG-32):**

| Concepto | 730 h/mes | 24 h/mes |
|---|---:|---:|
| Plano de control EKS (0,10 USD por clúster-hora) | 73,00 | 2,40 |
| Nodo `t4g.small` (0,0168 USD/h) | 12,26 | 0,40 |
| Disco gp3 de 20 GB | 1,60 | 0,05 |
| **Total EKS** | **86,86** | **2,86** |
| Referencia: 4 tareas Fargate ARM de 0,25 vCPU y 0,5 GB (ECS) | 28,84 | 0,95 |

La estimación de la calculadora (enlace en la [cotización](../costos/eg32-cotizacion-lista-de-precios.md)) coincide a 730 h (86,86); a 24 h la calculadora cobra el clúster el mes completo y no sirve para esta cifra.

**Qué no se demostró (consecuencia de no desplegar):**
- Que `api-contratos` corra como Deployment y Service y responda (criterio 1).
- Que la misma imagen de ECR funcione en EKS (criterio 2; solo por diseño).
- Que el stack se cree y se destruya con Terraform (criterio 3; hoy solo `fmt`, `validate` y Checkov en el CI).
- El costo real de una ventana en Cost Explorer.

**Riesgo asumido:** el tema 19 pide desplegar un componente en EKS. Si quien califica exige la prueba real, este cierre no la cumple; **reabrir** con el procedimiento de la guía (`terraform -chdir=infra/terraform/eks apply`, un `GET /health`, `destroy` el mismo día, unos 3 USD).

