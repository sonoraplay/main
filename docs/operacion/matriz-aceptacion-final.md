---
title: "Final acceptance matrix / Matriz final de aceptación"
---

# Final acceptance matrix / Matriz final de aceptación

> Evidence snapshot: 2026-11-08. This matrix is a delivery control, not an assertion that all acceptance criteria are complete. The owner column identifies the **responsible role to confirm**, not a Jira assignment.
>
> Corte de evidencia: 2026-11-08. Esta matriz es un control de entrega, no una afirmación de que todos los criterios estén completos. La columna de responsable identifica el **rol por confirmar**, no una asignación de Jira.

## English — submission version

**Statuses:** Verified in CI = automated evidence exists; Technical work pending = implementation or tests incomplete; External verification / approval = requires AWS, a reviewer or instructor.

| Workstream | Status | Evidence / next action | Owner (role, to confirm) |
|---|---|---|---|
| EG-15 production timestamp validation | Verified in CI; merge pending | [PR #67](https://github.com/sonoraplay/main/pull/67), [CI run](https://github.com/sonoraplay/main/actions/runs/42515543301); real project F2 validator rejects an impossible date without dev dependencies | Development |
| Documentation canonical URLs | Verified in CI; merge pending | PR #67: README, Docusaurus and four bilingual portal/publication pages | Documentation |
| EG-36 fraud exclusion before Gold | Technical work pending | [PR #66](https://github.com/sonoraplay/main/pull/66): fail-closed default and held-play royalty regression; full Spark/Python 10,000-account parity and performance evidence still required | Data engineering |
| EG-51 CA-10 pure Python | Verified in CI for pure rules only | [CI run](https://github.com/sonoraplay/main/actions/runs/42510450696): TP=500, FP=1, TN=9499, FN=0, recall=100%, FPR≈0.0105%; **not yet Spark acceptance** | Data engineering |
| EG-27 ECS Fargate | External verification / approval | Recover ECR digest, task definition revision and CloudTrail events; update bilingual evidence without claiming expired CloudWatch logs | Infrastructure |
| EG-31 dimensional model | External verification / approval | Recheck approval and technical evidence against current Jira; historical [pending list](../infraestructura/cierre-sprint-3-pendientes.md) is dated Oct 30 | Architecture |
| EG-32 AWS budget and cost attribution | External verification / approval | Confirm official pricing calculator URLs and Cost Explorer attribution, current AWS state and reviewer approval | Infrastructure / finance |
| EG-42 churn and cohorts | Technical work pending | Audit code, datasets, reproducible queries and acceptance criteria | Analytics |
| EG-43 fraud report | Technical work pending | Base report on verified Spark fraud signals, held plays and confusion matrix | Analytics |
| EG-44 Power BI / ADR-0019 | Technical work pending | Confirm secure SSM tunnel design, report artifacts and reviewer acceptance | BI |
| EG-48/49 final cost and architecture | Technical work pending | Prepare final comparison, architecture and assumptions with source-linked AWS cost evidence | Architecture / finance |
| EKS / ADR-0018 | External verification / approval | Obtain written instructor acceptance of comparison-only scope, or deploy required component in approved AWS window | Instructor / infrastructure |
| RabbitMQ and Airflow deployment | Technical work pending | Define reproducible Terraform deployment and destruction path; avoid asserting existing Compose is cloud-managed | Infrastructure |
| Real AWS destruction and demo | External verification / approval | Run only in authorized window; preserve outputs, verify orphan resources, review Cost Explorer after window | Infrastructure / team |
| develop → main and release | External verification / approval | Review and squash approved PRs, pass final CI, rehearse demo, tag release after authorization | Team lead |

## Español — versión equivalente para revisión

**Estados:** Verificado en CI = existe evidencia automatizada; Trabajo técnico pendiente = faltan implementación o pruebas; Verificación / aprobación externa = requiere AWS, un revisor o el docente.

| Frente | Estado | Evidencia / siguiente acción | Responsable (rol por confirmar) |
|---|---|---|---|
| EG-15 validación de fechas en producción | Verificado en CI; fusión pendiente | [PR #67](https://github.com/sonoraplay/main/pull/67), [ejecución CI](https://github.com/sonoraplay/main/actions/runs/42515543301); el validador F2 real rechaza una fecha imposible sin dependencias de desarrollo | Desarrollo |
| URL oficiales de documentación | Verificado en CI; fusión pendiente | PR #67: README, Docusaurus y cuatro páginas bilingües de portal/publicación | Documentación |
| EG-36 exclusión de fraude antes de Gold | Trabajo técnico pendiente | [PR #66](https://github.com/sonoraplay/main/pull/66): fallo seguro por defecto y regresión de regalías retenidas; faltan paridad completa Spark/Python de 10.000 cuentas y rendimiento | Ingeniería de datos |
| EG-51 CA-10 en Python puro | Verificado en CI solo para reglas puras | [Ejecución CI](https://github.com/sonoraplay/main/actions/runs/42510450696): VP=500, FP=1, VN=9499, FN=0, recall=100 %, FPR≈0,0105 %; **aún no es aceptación de Spark** | Ingeniería de datos |
| EG-27 ECS Fargate | Verificación / aprobación externa | Recuperar digest ECR, revisión de tarea y eventos CloudTrail; actualizar evidencia bilingüe sin afirmar que existen logs de CloudWatch expirados | Infraestructura |
| EG-31 modelo dimensional | Verificación / aprobación externa | Revisar aprobación y evidencia técnica en Jira actual; la [lista histórica](../infraestructura/cierre-sprint-3-pendientes.md) es del 30 de octubre | Arquitectura |
| EG-32 presupuesto AWS y atribución de costos | Verificación / aprobación externa | Confirmar URL oficiales de la calculadora, atribución en Cost Explorer, estado AWS y aprobación del revisor | Infraestructura / finanzas |
| EG-42 churn y cohortes | Trabajo técnico pendiente | Auditar código, datos, consultas reproducibles y criterios de aceptación | Analítica |
| EG-43 informe de fraude | Trabajo técnico pendiente | Basar informe en señales Spark verificadas, reproducciones retenidas y matriz de confusión | Analítica |
| EG-44 Power BI / ADR-0019 | Trabajo técnico pendiente | Confirmar diseño seguro de túnel SSM, entregables del informe y aceptación del revisor | BI |
| EG-48/49 costos y arquitectura finales | Trabajo técnico pendiente | Preparar comparación, arquitectura y supuestos finales con evidencia de costos AWS enlazada | Arquitectura / finanzas |
| EKS / ADR-0018 | Verificación / aprobación externa | Obtener aceptación escrita del docente para alcance solo comparativo o desplegar componente requerido en ventana AWS aprobada | Docente / infraestructura |
| Despliegue RabbitMQ y Airflow | Trabajo técnico pendiente | Definir despliegue y destrucción reproducibles con Terraform; no afirmar que Compose actual está gestionado en nube | Infraestructura |
| Destrucción real AWS y demo | Verificación / aprobación externa | Ejecutar solo en ventana autorizada; guardar salidas, verificar recursos huérfanos y revisar Cost Explorer después | Infraestructura / equipo |
| develop → main y versión final | Verificación / aprobación externa | Revisar y fusionar con squash los PR aprobados, pasar CI final, ensayar demo y etiquetar versión tras autorización | Líder del equipo |
