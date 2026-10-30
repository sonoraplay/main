# EG-31 and EG-32 — Acceptance evidence register / Registro de evidencia de aceptación

**As of / Corte:** 2026-10-23 · **Review state / Estado:** EG-31 dimensional contract approved by Julián on 2026-10-23 (ADR-0014 accepted with conditions on 2026-10-22); Spark/Parquet evidence pending; EG-32 awaiting its tests in AWS / contrato dimensional de EG-31 aprobado por Julián el 2026-10-23 (ADR-0014 aceptado con condiciones el 2026-10-22); pruebas de Spark/Parquet pendientes; EG-32 espera sus pruebas en AWS.

This file is a **traceability register**, not a claim of deployed AWS infrastructure or completed Spark processing. / Este archivo es un **registro de trazabilidad**, no una afirmación de despliegue AWS ni de ejecución Spark terminada.

## EG-31 — Dimensional model and Data Lake

| Criterion / Criterio | Deliverable / Entregable | Evidence / Evidencia | Status / Estado | Next verification / Siguiente verificación |
|---|---|---|---|---|
| CA1: `fact_plays` + eight dimensions | [model / modelo](eg31-modelo-dimensional-en-es.md) | grain, keys, Mermaid relationships | Design documented / diseño documentado | review joins and run Silver/Gold materialization |
| CA2: `fact_settlement` holder × country × month × version, original/adjustment | [model / modelo](eg31-modelo-dimensional-en-es.md) | versioning, existing PostgreSQL report contract `db/ddl/003_reportes_regalias.sql` | Design documented / diseño documentado | validate original + adjustment settlement on real data |
| CA3: paid play has settlement ID | [model / modelo](eg31-modelo-dimensional-en-es.md) | nullable `settlement_id`, bridge proposal, SQL verification contract | Pending implementation / pendiente implementar | run integrity query after EG-37 |
| CA4: Bronze/Silver/Gold Parquet partitions + ADR-0014 | [ADR-0014](../adr/0014-data-lake-parquet-partitions.md) | layer paths, partition policy | Design documented; ADR accepted with conditions on 2026-10-22 / diseño, ADR aceptado con condiciones | run Parquet read/write, verify S3 layout and meet the ADR conditions |
| CA5: churn and engagement | [model / modelo](eg31-modelo-dimensional-en-es.md) | F3 churn semantics, F2 session metrics | Design documented / diseño documentado | run EG-42 sample calculations and Power BI queries |

**EG-31 acceptance gates / Puertas de aceptación EG-31:** (1) Julián's technical approval of the v2 dimensional contract — **given on 2026-10-23** (ADR-0014 was accepted with conditions on 2026-10-22; its conditions remain open); (2) Spark/Parquet materialization and partition evidence (EG-35/37); (3) executed integrity and reconciliation checks for paid plays, settlement versions and adjustments; (4) sample churn/engagement query results (EG-42). These are validation outcomes, not four new user-story requirements. **All five criteria are documented as a design, not demonstrated end-to-end.** / (1) aprobación del modelo v2 — **otorgada el 2026-10-23** (el ADR-0014 se aceptó con condiciones el 2026-10-22; sus condiciones siguen abiertas); (2) pruebas de materialización y particiones Spark/Parquet; (3) consultas ejecutadas de integridad, versiones y ajustes; (4) resultados de muestra de churn/engagement. Son evidencias de validación, no requisitos nuevos. **Los cinco criterios están diseñados, pero no demostrados de extremo a extremo.**

## EG-32 — Cost analysis v1 and budget alarm

| Criterion / Criterio | Deliverable / Entregable | Evidence / Evidencia | Status / Estado | Next verification / Siguiente verificación |
|---|---|---|---|---|
| CA1: priced inventory and calculator | [cost draft / borrador](../costos/eg32-aws-cost-analysis-v1-en-es.md) | priced worksheet with official AWS list prices (v1.1): about USD 126/month always on; **no shareable calculator URL yet** | Partial / parcial | generate the Calculator URL (steps in the cost doc) |
| CA2: 24/7 vs test windows | [cost draft / borrador](../costos/eg32-aws-cost-analysis-v1-en-es.md), [ADR-0020](../adr/0020-ventanas-encendido-aws.md) | same inventory priced for both scenarios (v1.1): about USD 126/month always on vs USD 5.6/month in windows; reconciles with the ADR-0020 six-week figures | Done as worksheet / hecho en hoja | reconcile with Cost Explorer after each window |
| CA3: AWS Budget + SNS email | [cost checklist / lista](../costos/eg32-aws-cost-analysis-v1-en-es.md) | deployed in AWS; confirmed subscription; SNS test email and a real AWS Budgets email (`sonoraplay-mensual`, ACTUAL > USD 25.00, amount USD 25.50) received on 2026-10-23 ([evidence](../infraestructura/eg32-presupuesto-alarma.md)) | Done / cumplido: Budgets → SNS → email proven | none |
| CA4: `Project` and `Owner` tags | EG-26 Terraform branch and [cost draft](../costos/eg32-aws-cost-analysis-v1-en-es.md) | `Project` and `Owner` verified on the SNS topic, the 5 ECR repositories and the state bucket (2026-10-23) | Partial / parcial: tags exist; Billing activation pending | Julián activates `Project` and `Owner` in Billing; check Cost Explorer later |
| CA5: docs in `docs/costos/` and architecture link | [cost draft](../costos/eg32-aws-cost-analysis-v1-en-es.md), [architecture](../arquitectura/arquitectura-v1.md) | both files changed in PR #7, merged into `develop` on 2026-10-23 | Done / hecho (PR #7 merged / fusionado) | confirm the architecture link still resolves during consolidation |

## Sequential dependency gate / Puertas de dependencias

1. **EG-30:** done. PR #3 was merged into `develop` on 2026-10-23, ADR-0021 was accepted (PR #13) and EG-30 is "Finalizada" in Jira. / Cumplido: el PR #3 se fusionó en `develop` el 2026-10-23, el ADR-0021 se aceptó (PR #13) y EG-30 está «Finalizada» en Jira.
2. **EG-31:** the dimensional contract was approved on 2026-10-23 and ADR-0014 is accepted with conditions, so EG-35/37 can lock the Gold schemas under those conditions; EG-31 stays open until the Spark/Parquet evidence exists. / El contrato dimensional se aprobó el 2026-10-23 y el ADR-0014 está aceptado con condiciones, así que EG-35/37 pueden fijar los esquemas Gold bajo esas condiciones; EG-31 sigue abierta hasta tener la evidencia de Spark/Parquet.
3. **EG-26 and EG-29:** infrastructure and reliable messaging unblock EG-33 Bronze. / Infraestructura y mensajería desbloquean Bronze.
4. **EG-33 → EG-35/36 → EG-37 → EG-38/45:** Bronze to Silver to Gold to monthly settlement. / Flujo de ingesta a liquidación.
5. **EG-32:** budget controls must precede any new AWS test window. / Controles de gasto antes de nuevas ventanas AWS.

**Review responsibility / Revisión:** María Clara prepares design and estimate; Julián approves ADRs, infrastructure and budget; Andrea validates API/Gold interface and ECS usage. **No Jira status change or PR merge is implied. / No implica cambio de estado en Jira ni fusión de PR.**

GitHub: [PR #3](https://github.com/sonoraplay/main/pull/3), [PR #7](https://github.com/sonoraplay/main/pull/7). Jira: [EG-30](https://claram04.atlassian.net/browse/EG-30), [EG-31](https://claram04.atlassian.net/browse/EG-31), [EG-32](https://claram04.atlassian.net/browse/EG-32).


## Corrective review 2026-10-21 / Revisión correctiva

- **EG-31 CA1:** design v2 explicitly separates F2 message `event_id` from reconstructed `play_id`; Gold `fact_plays` is one row per play, not per message. **Design correction documented; EG-35 test pending.** / Se separan eventos y reproducciones; falta probar EG-35.
- **EG-31 CA2:** `fact_settlement` reporting grain is holder × billing country × month × version, with `fact_settlement_detail` for component/contract percentage and `fact_country_pool` to avoid double-counting. **Review and EG-37 reconciliation pending.** / Grano corregido, conciliación pendiente.
- **EG-31 CA3:** canonical `settlement_id` plus append-only play/settlement bridge, with explicit adjustment history. **The canonical-settlement policy is exercised by the EG-37 reconciliation tests (Spark).** / La política de liquidación principal se prueba en la conciliación de EG-37.
- **EG-31 CA4/5:** ADR-0014 is accepted with conditions (2026-10-22) and the analytics contracts remain proposed; no real Parquet or churn/engagement test is claimed. / No hay prueba real de Parquet ni de analítica.
- **EG-32 CA1/2:** priced worksheet v1.1 added with official AWS list prices for the same inventory in both scenarios; the AWS Calculator link remains `PENDING`, as do Cloud Map/DNS, CloudTrail, KMS, Budgets and EKS. / Hoja cotizada con tarifas oficiales; falta el enlace de la calculadora.
- **EG-32 CA3:** **passed.** The SNS-only delivery test passed on 2026-10-23, and a real AWS Budgets email for `sonoraplay-mensual` (ACTUAL > USD 25.00, amount USD 25.50) arrived the same day, proving Budgets → SNS → email. See `docs/infraestructura/eg32-presupuesto-alarma.md`. / **Cumplido.** La prueba SNS pasó el 2026-10-23 y ese mismo día llegó un correo real de AWS Budgets de `sonoraplay-mensual` (ACTUAL > 25,00 USD, monto 25,50 USD): recorrido Budgets → SNS → correo demostrado.
- **EG-32 CA4:** `Project=sonoraplay` and `Owner` are verified on deployed persistent resources (2026-10-23); Billing cost allocation activation and Cost Explorer attribution are pending. / Etiquetas verificadas en recursos desplegados; falta la activación en Billing.
- **EG-32 CA5:** documentation remains in draft PR #7. / Pendiente revisión/fusión.
- **EG-30:** PR #3 and ADR-0021 remain separate review gates. Changing REST Countries to `mledoze/countries` requires formal source-contract approval, and month-end holiday/weekend behavior must be decided and tested. / EG-30 no está cerrada.

**Dependencies / Dependencias:** EG-26 and EG-29 → EG-33 → EG-35/36 → EG-37 → EG-38/45; EG-30/23 feed EG-37; EG-31 contract review precedes Gold schema freeze; EG-32 budget authorization precedes any new AWS test. Jira issue links are not yet configured. / No hay vínculos de bloqueo en Jira verificados.

**Acceptance rule / Regla:** a proposed schema, template, SQL snippet or procedure is not a passing integration test. / Un diseño o procedimiento no sustituye evidencia de ejecución.


## Integration status update (2026-10-22) / Actualización de integración

**English:** PR #22 now includes Terraform `Owner` default tagging and a persistent AWS Budget/SNS implementation. Its CI and Docusaurus checks passed at commit `12a11cd4`; **this is code-validation evidence only**. Therefore the earlier CA4 wording “Owner absent / Julián adds tag” is **superseded**: the tag exists in the proposed code, but actual resource tagging, Billing cost-allocation activation and Cost Explorer attribution remain unverified. CA3 is also **implemented in code, not demonstrated in AWS**. CA1 still requires **two shareable calculator estimate URLs**; the calculator homepage does not satisfy it. See the calculator handoff in the cost analysis document. PR #23 targets PR #7's branch; PR #7 and PR #22 remain separate reviews for Julián. Do not mark any acceptance criterion complete solely because GitHub CI is green.

**Español:** El PR #22 ya incluye la etiqueta predeterminada `Owner` y la implementación persistente de AWS Budget/SNS. CI y Docusaurus pasaron en el commit `12a11cd4`, pero **eso solo valida el código**. Por lo tanto, la afirmación anterior “falta Owner / Julián debe agregarla” queda **reemplazada**: la etiqueta está en el código propuesto, pero faltan la comprobación de recursos reales, la activación de etiquetas en Billing y la atribución de costos en Cost Explorer. CA3 está **implementado en código, no probado en AWS**. CA1 necesita **dos enlaces compartibles de estimaciones**; la página principal de la calculadora no sirve como evidencia. Consulta las instrucciones en el análisis de costos. El PR #23 apunta a la rama del PR #7; PR #7 y PR #22 requieren revisiones separadas de Julián. No cerrar criterios solo por tener CI en verde.
