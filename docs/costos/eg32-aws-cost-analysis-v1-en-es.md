# EG-32 — AWS cost analysis v1 / Análisis de costos AWS v1

**Status / Estado:** Draft, not an AWS billing report / Borrador, no es una factura AWS. 2026-10-21.

## English

### Scope and assumptions

Region `us-east-1`. Architecture: [v1](../arquitectura/arquitectura-v1.md); operating policy: [ADR-0020](../adr/0020-ventanas-encendido-aws.md). The figures **USD 165–170** (six-week always-on project scenario) and **USD 30–40** (test-window project scenario), both **excluding EKS**, are previously documented planning estimates in ADR-0020, **not current monthly prices, not AWS invoices and not verified calculator results**. Do not compare them as monthly bills. Final amounts depend on actual instance types, duration, storage, requests, data transfer and EKS usage. The 1-day RDS backup exception was accepted by Julián on October 20; architecture text still describes the original 7-day criterion and must be reconciled.

| Service | Unit and price input needed | 24/7 scenario | Test-window scenario | Evidence / owner |
|---|---|---|---|---|
| VPC, subnets, S3 gateway endpoint | Usually no hourly base charge; check data transfer | All month | Windows | EG-26 / Julián |
| EC2 NAT instance + EBS + public IPv4 | instance USD/hour, EBS GB-month, IPv4 USD/hour, egress GB | ~730 hours/month | actual window hours | EG-26 / Julián |
| ALB | ALB-hour + LCU-hour | ~730 hours/month | window hours | EG-27 / Andrea |
| ECS Fargate APIs and consumers | vCPU-hour + GB-hour × number of tasks | ~730 hours/month per task | window hours | EG-27/33 / Andrea |
| RabbitMQ and Airflow EC2 | instance USD/hour + EBS GB-month | ~730 hours/month | window hours | EG-34 / Julián |
| Spark jobs on ECS Spot | vCPU-hour + GB-hour × job duration | job-dependent | job-dependent | EG-35/37 |
| RDS PostgreSQL | instance USD/hour + storage GB-month + backups | ~730 hours/month | window hours | EG-26/28 / Julián |
| S3 Bronze/Silver/Gold/state | storage GB-month + PUT/GET + transfer | persistent volume | persistent volume | EG-26/31 |
| ECR | image storage GB-month + transfer | stored images | stored images | EG-40 |
| CloudWatch, CloudTrail | logs ingestion/storage, alarms, events | volume-dependent | volume-dependent | EG-26 |
| SSM, IAM, Budgets, SNS | check free allowances, budget/action pricing, SNS email usage | usage-dependent | usage-dependent | Julián |
| EKS | cluster USD/hour + nodes/pods + network | **separate scenario** | short authorized test only | EG-41 / Julián |

**Pricing verification required:** Build and save the exact AWS Pricing Calculator estimate: https://calculator.aws/#/ . Paste the **generated shareable estimate URL** here once available: **PENDING**. Never fabricate a calculator estimate or unit prices. Validate account plan restrictions, Free Tier applicability and actual billing in AWS Cost Explorer. Use 730 h/month only as a planning assumption for continuous services, not as a measured runtime.

### Scenario comparison

- **A — always on:** compute, database, broker and ALB run continuously; model a calendar month at ~730 h, plus storage and variable usage. The historical ADR-0020 six-week total is ~USD 165–170 **without EKS**, not a monthly quote.
- **B — controlled windows (selected in ADR-0020):** provision with Terraform for approved test windows, destroy on the same day, keep only explicitly authorized persistent low-cost resources. The historical six-week estimate is ~USD 30–40 **without EKS**; actual cost must be verified after each window.
- **EKS:** price separately; do not assume its control plane or nodes are free. Do not provision EKS until the team approves the cost.

### Budget and tagging: action required

1. **Julián / AWS account owner:** confirm the maximum approved USD budget and notification email (never commit the email or account identifiers to public documentation).
2. Create an AWS Budget with actual/forecast thresholds appropriate to the approved limit; configure SNS notification destination and confirm subscription.
3. Perform **one controlled notification test** and retain a redacted screenshot/email with timestamp. **NOT TESTED/NOT VERIFIED HERE.** AWS Budgets may have notification timing constraints; document the test mechanism and avoid intentionally incurring costs to force a threshold.
4. Ensure Terraform `default_tags` or `local.etiquetas` includes `Project=SonoraPlay` and `Owner=<approved team value>` on supported resources; verify Cost Allocation Tags activation and tagging coverage. Jira comment (October 14) reports that `Owner` is **missing** from EG-26 Terraform. **NOT YET FIXED.**
5. Capture AWS Cost Explorer by service for the October 19 test window and after each later test; reconcile with the calculator and explain variance.
6. Link this document from the architecture once reviewed; this draft already provides a link target.

### Acceptance status

1. Per-service assumptions: **draft inventory; exact unit prices and shareable calculator link pending**.
2. Two scenarios: **described; actual priced comparison pending**.
3. AWS Budget + SNS email: **not configured/tested by this document**.
4. `Project` and `Owner` tags: **Owner change and verification pending**.
5. Documentation in `docs/costos/`: **this draft satisfies location; architecture backlink pending**.

---

## Español

**Alcance:** región `us-east-1`; arquitectura v1 y ADR-0020. Las cifras de **165–170 USD** (proyecto de seis semanas encendido) y **30–40 USD** (ventanas de prueba), sin EKS, proceden de estimaciones previas del ADR-0020. **No son costos mensuales ni facturas verificadas.** Falta la cotización detallada del AWS Pricing Calculator.

**Servicios por cotizar:** EC2 NAT, EBS, IPv4 pública, ALB, ECS Fargate, EC2 de RabbitMQ y Airflow, jobs Spark, RDS, S3, ECR, CloudWatch, CloudTrail, SSM, Budgets, SNS y EKS por separado. La tabla anterior indica las unidades que deben presupuestarse. Para funcionamiento continuo se asumen unas **730 horas por mes**; para ventanas, solo las horas reales de cada prueba. Almacenamiento, tráfico y solicitudes se calculan aparte.

**Escenario A (24/7):** recursos encendidos durante todo el mes; es el escenario más costoso. **Escenario B (ventanas):** Terraform crea recursos, se prueban y destruyen el mismo día; es la opción aprobada en ADR-0020. EKS requiere autorización de gasto independiente.

**Pendientes con Julián:** (1) acordar límite en USD y correo de alertas; (2) generar y compartir cotización del [AWS Pricing Calculator](https://calculator.aws/#/); (3) crear AWS Budget y notificación SNS, confirmar suscripción y guardar prueba de correo; (4) agregar `Owner` a las etiquetas de Terraform, además de `Project`, y comprobar Cost Explorer; (5) obtener costos reales por servicio de la ventana AWS y reconciliar la estimación. **No se ha realizado ninguna configuración AWS desde este documento.**

**Criterios de Jira:** inventario y escenarios en borrador; precios reales, enlace de cotización, alarma probada, etiquetas y enlace desde arquitectura siguen pendientes de validación. No cerrar EG-32 todavía.


## Reproducible estimation worksheet / Hoja de cálculo reproducible

Use the following formula for **each** metered service and each scenario. This is a calculation method, **not** a validated AWS quote.

`estimated_monthly_usd = hourly_rate_usd × active_hours + storage_rate_usd_per_gb_month × stored_gb + request_rate_usd_per_1000 × requests/1000 + data_transfer_rate_usd_per_gb × transfer_gb + other_service_specific_charges`

| Input / Entrada | Always on / Siempre activo | Windows / Ventanas | Source / Fuente |
|---|---|---|---|
| Calendar basis / Mes de referencia | 730 h/month planning assumption | actual approved test hours | ADR-0020 and EG-26 logs |
| Compute instance count / Instancias | inventory from Terraform | same inventory when on | EG-26 branch |
| RDS storage / Almacenamiento RDS | allocated GB × monthly rate | GB-month prorated per billing terms | AWS calculator |
| S3 / S3 | stored GB and PUT/GET | stored GB and PUT/GET | S3 usage and calculator |
| EKS / EKS | separate, not included in historical totals | separate short authorized window | EG-41, approval required |
| AWS prices / Precios AWS | **PENDING: quote by SKU and region** | **PENDING: quote by SKU and region** | https://calculator.aws/#/ |
| Actual AWS costs / Costos reales | **PENDING** | **PENDING** | Cost Explorer by service and tag |

**Do not mark CA1 complete** until the unit rates, monthly totals by service, timestamped calculator estimate and shareable estimate URL have been recorded. **Do not mark CA3 complete** until the AWS Budget/SNS email notification is actually demonstrated. AWS Budget notifications may not fire instantly; do not spend money deliberately just to trigger one.

### Acceptance trace / Trazabilidad de aceptación

| CA | Deliverable / Entregable | Evidence required / Evidencia exigida | Status / Estado |
|---|---|---|---|
| 1 | per-service estimate + calculator URL / cotización por servicio | price, units, hours/GB/requests, shareable link | **Blocked: no verified quote** |
| 2 | 24/7 vs windows / escenarios | two calculated scenario totals with the same service inventory | **Partial: qualitative comparison** |
| 3 | AWS Budget → SNS → email | redacted proof of one received notification | **Blocked: AWS access** |
| 4 | `Project` and `Owner` tags | Terraform code + deployed tag inspection + cost allocation activation | **Blocked: Owner tag missing** |
| 5 | `docs/costos/` and architecture backlink | this file and architecture cross-link | **Implemented in PR #7; pending review/merge** |

**Responsibility / Responsables:** María Clara owns the estimate and its bilingual documentation. Julián owns account-level approvals, AWS Budget/SNS configuration and Terraform tag fixes. Andrea supplies ECS/ALB utilization assumptions. No cloud resource should be created to fill a documentation gap without cost approval.

**Consistency note / Nota de coherencia:** ADR-0020 contains *six-week total project estimates*; do not silently convert them to monthly costs. The current architecture still describes a 7-day RDS backup requirement; Julián's 1-day exception must be documented in the authoritative EG-26 decision before updating the baseline.
