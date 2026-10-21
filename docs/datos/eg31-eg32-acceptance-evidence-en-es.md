# EG-31 and EG-32 — Acceptance evidence register / Registro de evidencia de aceptación

**As of / Corte:** 2026-10-21 · **Review state / Estado:** awaiting technical review / pendiente revisión técnica.

This file is a **traceability register**, not a claim of deployed AWS infrastructure or completed Spark processing. / Este archivo es un **registro de trazabilidad**, no una afirmación de despliegue AWS ni de ejecución Spark terminada.

## EG-31 — Dimensional model and Data Lake

| Criterion / Criterio | Deliverable / Entregable | Evidence / Evidencia | Status / Estado | Next verification / Siguiente verificación |
|---|---|---|---|---|
| CA1: `fact_plays` + eight dimensions | [model / modelo](eg31-modelo-dimensional-en-es.md) | grain, keys, Mermaid relationships | Design documented / diseño documentado | review joins and run Silver/Gold materialization |
| CA2: `fact_settlement` holder × country × month × version, original/adjustment | [model / modelo](eg31-modelo-dimensional-en-es.md) | versioning, existing PostgreSQL report contract `db/ddl/003_reportes_regalias.sql` | Design documented / diseño documentado | validate original + adjustment settlement on real data |
| CA3: paid play has settlement ID | [model / modelo](eg31-modelo-dimensional-en-es.md) | nullable `settlement_id`, bridge proposal, SQL verification contract | Pending implementation / pendiente implementar | run integrity query after EG-37 |
| CA4: Bronze/Silver/Gold Parquet partitions + ADR-0014 | [ADR-0014](../adr/0014-data-lake-parquet-partitions.md) | proposed layer paths, partition policy | Design documented; ADR proposed / diseño, ADR propuesto | run Parquet read/write, verify S3 layout and accept ADR |
| CA5: churn and engagement | [model / modelo](eg31-modelo-dimensional-en-es.md) | F3 churn semantics, F2 session metrics | Design documented / diseño documentado | run EG-42 sample calculations and Power BI queries |

**EG-31 pending — only these two / Pendiente de EG-31, únicamente:** (1) technical approval of ADR-0014 by Julián; (2) Spark/Parquet execution tests (EG-35/37). The five criteria are documented as design in the aligned v2 model. / (1) aprobación técnica del ADR-0014 por Julián; (2) pruebas de Spark/Parquet.

## EG-32 — Cost analysis v1 and budget alarm

| Criterion / Criterio | Deliverable / Entregable | Evidence / Evidencia | Status / Estado | Next verification / Siguiente verificación |
|---|---|---|---|---|
| CA1: priced inventory and calculator | [cost draft / borrador](../costos/eg32-aws-cost-analysis-v1-en-es.md) | priced worksheet with official AWS list prices (v1.1): about USD 126/month always on; **no shareable calculator URL yet** | Partial / parcial | generate the Calculator URL (steps in the cost doc) |
| CA2: 24/7 vs test windows | [cost draft / borrador](../costos/eg32-aws-cost-analysis-v1-en-es.md), [ADR-0020](../adr/0020-ventanas-encendido-aws.md) | same inventory priced for both scenarios (v1.1): about USD 126/month always on vs USD 5.6/month in windows; reconciles with the ADR-0020 six-week figures | Done as worksheet / hecho en hoja | reconcile with Cost Explorer after each window |
| CA3: AWS Budget + SNS email | [cost checklist / lista](../costos/eg32-aws-cost-analysis-v1-en-es.md) | procedure only; no AWS evidence | Blocked / bloqueado | Julián configures and proves notification |
| CA4: `Project` and `Owner` tags | EG-26 Terraform branch and [cost draft](../costos/eg32-aws-cost-analysis-v1-en-es.md) | Jira EG-32 reports `Owner` absent | Blocked / bloqueado | Julián adds tag and verifies in AWS |
| CA5: docs in `docs/costos/` and architecture link | [cost draft](../costos/eg32-aws-cost-analysis-v1-en-es.md), [architecture](../arquitectura/arquitectura-v1.md) | both files changed in PR #7 | Implemented in draft / implementado en borrador | review and merge PR |

## Sequential dependency gate / Puertas de dependencias

1. **EG-30:** PR #3 needs ADR-0021 decision, source approval, and month-end behavior confirmation. / Requiere decisión ADR-0021 y cierre de mes.
2. **EG-31:** approve dimensional contract and ADR-0014 before EG-35/37 implementation locks Gold schemas. / Aprobar contrato dimensional antes de fijar esquemas Gold.
3. **EG-26 and EG-29:** infrastructure and reliable messaging unblock EG-33 Bronze. / Infraestructura y mensajería desbloquean Bronze.
4. **EG-33 → EG-35/36 → EG-37 → EG-38/45:** Bronze to Silver to Gold to monthly settlement. / Flujo de ingesta a liquidación.
5. **EG-32:** budget controls must precede any new AWS test window. / Controles de gasto antes de nuevas ventanas AWS.

**Review responsibility / Revisión:** María Clara prepares design and estimate; Julián approves ADRs, infrastructure and budget; Andrea validates API/Gold interface and ECS usage. **No Jira status change or PR merge is implied. / No implica cambio de estado en Jira ni fusión de PR.**

GitHub: [PR #3](https://github.com/sonoraplay/main/pull/3), [PR #7](https://github.com/sonoraplay/main/pull/7). Jira: [EG-30](https://claram04.atlassian.net/browse/EG-30), [EG-31](https://claram04.atlassian.net/browse/EG-31), [EG-32](https://claram04.atlassian.net/browse/EG-32).


## Corrective review 2026-10-21 / Revisión correctiva

- **EG-31 CA1:** design v2 explicitly separates F2 message `event_id` from reconstructed `play_id`; Gold `fact_plays` is one row per play, not per message. **Design correction documented; EG-35 test pending.** / Se separan eventos y reproducciones; falta probar EG-35.
- **EG-31 CA2:** `fact_settlement` reporting grain is holder × billing country × month × version, with `fact_settlement_detail` for component/contract percentage and `fact_country_pool` to avoid double-counting. **Review and EG-37 reconciliation pending.** / Grano corregido, conciliación pendiente.
- **EG-31 CA3:** canonical `settlement_id` plus append-only play/settlement bridge, with explicit adjustment history. **The canonical-settlement policy is exercised by the EG-37 reconciliation tests (Spark).** / La política de liquidación principal se prueba en la conciliación de EG-37.
- **EG-31 CA4/5:** ADR-0014 and analytics contracts remain proposed; no real Parquet or churn/engagement test is claimed. / No hay prueba real de Parquet ni de analítica.
- **EG-32 CA1/2:** priced worksheet v1.1 added with official AWS list prices for the same inventory in both scenarios; the AWS Calculator link remains `PENDING`, as do Cloud Map/DNS, CloudTrail, KMS, Budgets and EKS. / Hoja cotizada con tarifas oficiales; falta el enlace de la calculadora.
- **EG-32 CA3:** distinguish SNS-only delivery test from required AWS Budgets-originated threshold email. **Neither is claimed passed.** / No confundir pruebas.
- **EG-32 CA4:** correct required tag to `Project=sonoraplay` and verify `Owner`, actual resource tags, and Billing cost allocation activation. / Falta evidencia desplegada.
- **EG-32 CA5:** documentation remains in draft PR #7. / Pendiente revisión/fusión.
- **EG-30:** PR #3 and ADR-0021 remain separate review gates. Changing REST Countries to `mledoze/countries` requires formal source-contract approval, and month-end holiday/weekend behavior must be decided and tested. / EG-30 no está cerrada.

**Dependencies / Dependencias:** EG-26 and EG-29 → EG-33 → EG-35/36 → EG-37 → EG-38/45; EG-30/23 feed EG-37; EG-31 contract review precedes Gold schema freeze; EG-32 budget authorization precedes any new AWS test. Jira issue links are not yet configured. / No hay vínculos de bloqueo en Jira verificados.

**Acceptance rule / Regla:** a proposed schema, template, SQL snippet or procedure is not a passing integration test. / Un diseño o procedimiento no sustituye evidencia de ejecución.
