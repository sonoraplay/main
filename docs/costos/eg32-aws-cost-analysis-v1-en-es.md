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

**Pricing verification required:** Build and save the exact AWS Pricing Calculator estimate: https://calculator.aws/#/ . Paste the **generated shareable estimate URL** here once available: **PENDING**. Never fabricate a calculator estimate or unit prices. Validate account plan restrictions, Free Tier applicability and actual billing in AWS Cost Explorer. Use 730 h/month only as a planning assumption for continuous services, not as a measured runtime. **A priced worksheet built from official AWS list prices is in "Priced estimate v1.1" at the end of this file**; the calculator URL stays **PENDING** because it can only be generated in the web interface.

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

1. Per-service assumptions: **priced worksheet with official list prices (v1.1); shareable calculator link pending**.
2. Two scenarios: **priced for the same inventory (v1.1): about USD 126/month always on vs about USD 5.6/month in windows**; Cost Explorer reconciliation pending.
3. AWS Budget + SNS email: **not configured/tested by this document**.
4. `Project` and `Owner` tags: **Owner change and verification pending**.
5. Documentation in `docs/costos/`: **this draft satisfies location; architecture backlink pending**.

---

## Español

**Alcance:** región `us-east-1`; arquitectura v1 y ADR-0020. Las cifras de **165–170 USD** (proyecto de seis semanas encendido) y **30–40 USD** (ventanas de prueba), sin EKS, proceden de estimaciones previas del ADR-0020. **No son costos mensuales ni facturas verificadas.** Falta la cotización detallada del AWS Pricing Calculator.

**Servicios por cotizar:** EC2 NAT, EBS, IPv4 pública, ALB, ECS Fargate, EC2 de RabbitMQ y Airflow, jobs Spark, RDS, S3, ECR, CloudWatch, CloudTrail, SSM, Budgets, SNS y EKS por separado. La tabla anterior indica las unidades que deben presupuestarse. Para funcionamiento continuo se asumen unas **730 horas por mes**; para ventanas, solo las horas reales de cada prueba. Almacenamiento, tráfico y solicitudes se calculan aparte.

**Escenario A (24/7):** recursos encendidos durante todo el mes; es el escenario más costoso. **Escenario B (ventanas):** Terraform crea recursos, se prueban y destruyen el mismo día; es la opción aprobada en ADR-0020. EKS requiere autorización de gasto independiente.

**Pendientes con Julián:** (1) acordar límite en USD y correo de alertas; (2) generar y compartir cotización del [AWS Pricing Calculator](https://calculator.aws/#/); (3) crear AWS Budget y notificación SNS, confirmar suscripción y guardar prueba de correo; (4) agregar `Owner` a las etiquetas de Terraform, además de `Project`, y comprobar Cost Explorer; (5) obtener costos reales por servicio de la ventana AWS y reconciliar la estimación. **No se ha realizado ninguna configuración AWS desde este documento.**

**Criterios de Jira:** inventario y escenarios **ya cotizados con tarifas oficiales de lista** (v1.1, al final del archivo); siguen pendientes el enlace compartible de la calculadora, la alarma probada, las etiquetas y la conciliación con Cost Explorer. No cerrar EG-32 todavía.


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
| 1 | per-service estimate + calculator URL / cotización por servicio | price, units, hours/GB/requests, shareable link | **Partial: priced worksheet from official list prices (v1.1); calculator URL pending** |
| 2 | 24/7 vs windows / escenarios | two calculated scenario totals with the same service inventory | **Done as worksheet (v1.1); reconcile with Cost Explorer after each window** |
| 3 | AWS Budget → SNS → email | redacted proof of one received notification | **Blocked: AWS access** |
| 4 | `Project` and `Owner` tags | Terraform code + deployed tag inspection + cost allocation activation | **Blocked: Owner tag missing** |
| 5 | `docs/costos/` and architecture backlink | this file and architecture cross-link | **Implemented in PR #7; pending review/merge** |

**Responsibility / Responsables:** María Clara owns the estimate and its bilingual documentation. Julián owns account-level approvals, AWS Budget/SNS configuration and Terraform tag fixes. Andrea supplies ECS/ALB utilization assumptions. No cloud resource should be created to fill a documentation gap without cost approval.

**Consistency note / Nota de coherencia:** ADR-0020 contains *six-week total project estimates*; do not silently convert them to monthly costs. The architecture baseline still describes 7-day RDS backups and a `t4g.nano` NAT; the accepted exception is recorded in ADR-0022 (1-day backups and `t4g.micro` NAT while the account is on the AWS free plan), and this worksheet prices the exception configuration.


## Corrective implementation checklist v2 (English) — EG-32

**Acceptance remains OPEN.** This section is an executable handoff, not an AWS price quote or evidence of a sent notification.

### Pricing evidence contract — CA1 and CA2

Record one **identical Terraform-derived inventory** for both scenarios. For each row record: service, SKU/instance type, region, quantity, hourly rate and pricing date/source, active hours, storage GB-month and rate, requests and rate, data transfer GB and rate, other fees, calculated monthly USD, and estimate URL. Keep the following **monthly worksheet template** in the PR and replace `PENDING` with verified calculator values:

| Service group | Quantity / SKU | Rate source | 24/7 monthly USD | Window monthly USD | Verification |
|---|---|---|---|---|---|
| NAT EC2 + EBS + public IPv4 | PENDING | PENDING | PENDING | PENDING | EG-26 |
| ALB + LCU | PENDING | PENDING | PENDING | PENDING | EG-27 |
| ECS Fargate API + consumers | PENDING | PENDING | PENDING | PENDING | EG-27/33 |
| RabbitMQ + Airflow EC2/EBS | PENDING | PENDING | PENDING | PENDING | EG-34 |
| Spark jobs / Spot | PENDING | PENDING | PENDING | PENDING | EG-35/37 |
| RDS + storage + backups | PENDING | PENDING | PENDING | PENDING | EG-26/28 |
| S3 + ECR + requests | PENDING | PENDING | PENDING | PENDING | EG-26/40 |
| CloudWatch + CloudTrail + transfer | PENDING | PENDING | PENDING | PENDING | EG-26 |
| Budgets + SNS + other billed services | PENDING | PENDING | PENDING | PENDING | Julián |
| **Monthly total, excluding EKS** | same inventory | calculator | **PENDING** | **PENDING** | María Clara |
| **EKS separate incremental total** | PENDING | calculator | **PENDING** | **PENDING** | EG-41 |

Formula per SKU: `monthly = quantity × rate_per_hour × active_hours + storage_GB_month × rate_per_GB_month + request_count/1000 × rate_per_1000 + transfer_GB × rate_per_GB + fixed_and_other_charges`. Model **persisted storage, public IPv4, backups and retained logs even when compute is off**; do not multiply those costs by the compute duty cycle without billing evidence. For 24/7 use a disclosed ~730-hour planning month; for windows use the approved schedule and actual teardown logs. Record **monthly** totals separately from the historical **six-week** ADR-0020 estimates. No prices, savings percentages, or shareable calculator URL have yet been verified.

**Required proof:** dated shareable AWS Pricing Calculator estimate in `us-east-1`, two fully priced totals, Terraform SKU inventory snapshot, assumptions and currency. Cost Explorer actuals are a separate post-execution reconciliation, not a substitute for the estimate.

### Budget/SNS test — CA3

**Owner Julián, prior authorization required.** (1) Agree a maximum USD budget and notification recipient privately. (2) Create a monthly cost budget with actual and forecast thresholds and SNS topic/email subscription as supported by the account. (3) Confirm the email subscription; inspect the topic policy so AWS Budgets can publish. (4) Conduct an authorized **SNS test publish** and retain a redacted received email plus timestamp; **this proves SNS delivery only**. (5) Independently retain evidence that AWS Budgets is configured to notify this topic and, when an actual/forecast threshold event genuinely occurs, retain the Budgets-originated email. **CA3 requires the end-to-end Budgets → SNS → email event**; an SNS-only test must not be marked CA3 passed. Do not force costs to trigger a budget alert.

### Tag verification — CA4

Terraform must consistently use the Jira-mandated value `Project=sonoraplay` (lowercase), not `Project=SonoraPlay`, and a team-approved `Owner` value. Configure provider `default_tags` for supported resources and explicit tags for resources not covered; inventory any untaggable AWS resources separately. After an approved deployment, verify actual resource tags with AWS resource tagging APIs/console and activate both user-defined cost allocation tags in Billing where supported. **Tags on a resource are not proof that Cost Explorer can yet allocate its costs**; activation and billing-data lag must be documented. Do not commit personal email addresses or account IDs.

### Approval and audit fields

| Gate | Evidence to attach | Approver | State |
|---|---|---|---|
| Budget maximum and test window | written approval and scope | Julián | PENDING |
| CA1/CA2 priced comparison | calculator URL, rates, inventory, dated monthly totals | Julián / María Clara | PENDING |
| CA3 end-to-end alarm | Budget settings, SNS topic/subscription, redacted Budgets-originated email | Julián | PENDING |
| CA4 tags | Terraform diff, resource inspection, activated cost allocation tags | Julián | PENDING |
| CA5 docs | PR #7 review + merged architecture backlink | reviewer | IN DRAFT |

## Lista correctiva v2 (Español) — EG-32

**La historia continúa abierta.** Se agrega una plantilla verificable, no una cotización ni una alarma ejecutada.

**CA1/CA2:** cotizar el **mismo inventario Terraform** en dos escenarios mensuales, indicando por servicio región, SKU, cantidad, precio unitario con fecha y fuente, horas, almacenamiento, solicitudes, transferencia, otros cargos y total. La tabla anterior tiene valores **PENDING** hasta obtener una cotización compartible de AWS Pricing Calculator. Los costos persistentes (almacenamiento, IPv4, copias y logs) pueden seguir existiendo cuando las instancias están apagadas. No convertir los presupuestos históricos de seis semanas en facturas mensuales. EKS se cotiza por separado.

**CA3:** Julián aprueba el límite y configura AWS Budget, SNS y la suscripción de correo. Una publicación de prueba en SNS **solo verifica el transporte de correo**, no demuestra que AWS Budgets dispare la alerta. Para aceptar CA3 se necesita evidencia real del recorrido **Budgets → SNS → correo** cuando ocurra el umbral, sin gastar deliberadamente para forzarlo.

**CA4:** usar `Project=sonoraplay` exactamente como exige EG-26 y `Owner` con valor aprobado; verificar etiquetas en recursos desplegados y su activación en Billing/Cost Explorer. Etiquetar Terraform por sí solo no demuestra atribución de costos.

**CA5:** la documentación y el enlace arquitectónico están en el PR #7, pero siguen sujetos a revisión/fusión. No declarar EG-32 completada hasta contar con las pruebas y aprobaciones registradas.

## Priced estimate v1.1 — official AWS list prices (English)

**Date:** 2026-10-21 · **Region:** `us-east-1` · **Status:** worksheet from published AWS list prices. It is **not** an AWS Pricing Calculator export, **not** an invoice, and **not** Cost Explorer data.

**Method.** Rates come from the public AWS Price List bulk files (`https://pricing.us-east-1.amazonaws.com/offers/v1.0/aws/<service>/current/us-east-1/index.json`), downloaded on 2026-10-21. The Calculator may round or apply Free Tier differently. Each rate below is the on-demand list price with no discounts or credits.

| Rate / Tarifa | USD | Unit / Unidad | Price file published / Archivo publicado |
|---|---:|---|---|
| EC2 `t4g.nano` / `t4g.micro` / `t4g.small` / `t4g.medium`, Linux | 0.0042 / 0.0084 / 0.0168 / 0.0336 | hour / hora | EC2, 2026-10-15 |
| EBS gp3 | 0.08 | GB-month | EC2, 2026-10-15 |
| Public IPv4 address in use | 0.005 | hour | VPC, 2026-10-16 |
| RDS `db.t4g.micro` PostgreSQL Single-AZ | 0.016 | hour | RDS, 2026-10-20 |
| RDS gp3 storage / extra backup storage | 0.115 / 0.095 | GB-month | RDS, 2026-10-20 |
| ALB / LCU | 0.0225 / 0.008 | hour / LCU-hour | ELB, 2026-09-11 |
| Fargate ARM vCPU / memory (On-Demand) | 0.03238 / 0.00356 | vCPU-hour / GB-hour | ECS, 2026-10-19 |
| S3 Standard (first 50 TB) / PUT / GET | 0.023 / 0.005 per 1,000 / 0.0004 per 1,000 | GB-month / requests | S3, 2026-10-15 |
| CloudWatch standard alarm / log ingestion / log storage | 0.10 / 0.50 / 0.03 | alarm-month / GB / GB-month | CloudWatch, 2026-10-07 |
| ECR storage | 0.10 | GB-month | ECR, 2026-09-11 |
| SNS email notifications | first 1,000 per month free, then 2.00 per 100,000 | notifications | SNS, 2026-09-15 |

**Assumptions (edit them in one place if the team changes them).** 730 h/month for always on; **8 windows of 3 h = 24 h/month** for the window scenario; 1 NAT with `t4g.micro` and 8 GB (ADR-0022); RabbitMQ `t4g.small` with 20 GB (ADR-0013); Airflow `t4g.medium` with 30 GB (architecture v1); RDS `db.t4g.micro` with 20 GB and 1-day backups inside the free backup allowance; 1 ALB with 2 public IPv4 addresses and 1 LCU as a conservative ceiling; 2 API tasks On-Demand and 2 Spot-class tasks priced **at the On-Demand ceiling** (the price list does not publish Spot rates); Spark 2 vCPU / 8 GB for 6 h/month at the On-Demand ceiling; S3 5 GB with 100,000 PUT and 200,000 GET; ECR 2 GB; 2 GB of logs ingested per month in the always-on case (scaled by hours in windows). Storage and IPs that disappear with `terraform destroy` are billed by the hour; S3, ECR, log storage and Spark are the only items counted as persistent.

| Service / Servicio | Assumption / Supuesto | 24/7 USD/mo | Windows USD/mo | Note / Nota |
|---|---|---:|---:|---|
| NAT: EC2 t4g.micro | 1 instancia (ADR-0022) | 6.13 | 0.20 |  |
| NAT: disco gp3 | 8 GB | 0.64 | 0.02 | GB-mes prorrateado por hora |
| NAT: IPv4 pública | 1 | 3.65 | 0.12 |  |
| RabbitMQ: EC2 t4g.small | 1 instancia (ADR-0013) | 12.26 | 0.40 |  |
| RabbitMQ: disco gp3 | 20 GB | 1.60 | 0.05 |  |
| Airflow: EC2 t4g.medium | 1 instancia (arquitectura v1) | 24.53 | 0.81 |  |
| Airflow: disco gp3 | 30 GB | 2.40 | 0.08 |  |
| RDS db.t4g.micro | Single-AZ | 11.68 | 0.38 |  |
| RDS almacenamiento gp3 | 20 GB | 2.30 | 0.08 | backups: 1 día, dentro de la asignación gratuita (hasta 20 GB) |
| ALB: hora | 1 ALB | 16.43 | 0.54 |  |
| ALB: LCU | 1 LCU (techo) | 5.84 | 0.19 | supuesto conservador; el consumo real suele ser menor |
| ALB: IPv4 públicas | 2 (una por AZ) | 7.30 | 0.24 |  |
| Fargate On-Demand: 2 APIs | 2 tareas x 0,25 vCPU / 0,5 GB ARM | 14.42 | 0.47 |  |
| Fargate Spot: simulador + consumidor | 2 tareas x 0,25 vCPU / 0,5 GB (techo = On-Demand) | 14.42 | 0.47 | la lista de precios no publica Spot; esto es un techo |
| Spark en Fargate | 2 vCPU / 8 GB, 6 h/mes (techo On-Demand) | 0.56 | 0.56 | solo corre en jobs; no depende del modo 24/7 |
| S3 Bronze/Silver/Gold | 5 GB estándar + 100 000 PUT + 200 000 GET | 0.69 | 0.69 | persiste entre ventanas |
| ECR | 2 GB de imágenes | 0.20 | 0.20 | persiste entre ventanas |
| CloudWatch: alarma NAT | 1 alarma estándar | 0.10 | 0.00 |  |
| CloudWatch Logs: ingesta | 2 GB/mes en 24/7 | 1.00 | 0.03 | escala con las horas encendidas |
| CloudWatch Logs: almacenamiento | ~2 GB con retención de 7 dias | 0.06 | 0.06 |  |
| SNS email + SSM estándar | hasta 1 000 correos/mes | 0.00 | 0.00 | SNS: primeros 1 000 correos/mes gratis; SSM estándar sin costo |
| **Total (excl. EKS and unquoted items) / Total (sin EKS ni rubros no cotizados)** | | **126.21** | **5.61** | |

**Results.**
- **Always on:** about **USD 126 per month**. If the Spot discount of up to 70% stated in architecture v1 holds (not verified), about **USD 116**.
- **Test windows:** about **USD 5.6 per month** (8 windows × 3 h): about **USD 0.51 per 3-hour window** plus about **USD 1.5 per month** of persistent items.
- **Reconciliation with the six-week figures in ADR-0020:** always on for six weeks gives about USD 160–174 (ADR-0020: 165–170); five weeks of windows plus one continuous final week gives about **USD 35** (ADR-0020: 30–40). The final continuous week alone is about USD 29. The figures agree, so the ADR-0020 range is not contradicted.
- **Not quoted here (marked PENDING):** Cloud Map and the private DNS zone, CloudTrail storage, KMS, AWS Budgets (the Budgets price file was not available at the path used), NAT data transfer (no volume assumed), RDS backup storage above the free allowance, actual Fargate Spot rates, and EKS (priced separately, see EG-41). Architecture v1 estimates the first group at about USD 1 per month.

**To obtain the shareable Calculator URL (about 15 minutes).** Open https://calculator.aws/#/ → *Create estimate* → region US East (N. Virginia) → add EC2 (`t4g.micro`, `t4g.small`, `t4g.medium`, Linux, On-Demand), EBS gp3 (8, 20 and 30 GB), Public IPv4 (3 addresses plus 2 for the ALB), RDS PostgreSQL (`db.t4g.micro`, Single-AZ, 20 GB gp3), Application Load Balancer (1 ALB, 1 LCU), Fargate (ARM, 0.25 vCPU / 0.5 GB × 4 tasks, and 2 vCPU / 8 GB × 6 h), S3 (5 GB), ECR (2 GB), CloudWatch (1 alarm, 2 GB logs) and SNS → set 730 h for always on and 24 h for windows (two estimates) → *Save and share* → paste both URLs in this section.

### What is missing to test the budget and the SNS notification (CA3 and CA4)

1. **Decisions (Julián):** the maximum USD budget and the alert email. Do not commit the email or account identifiers.
2. **Terraform:** `aws_budgets_budget` (monthly cost, actual and forecast thresholds), `aws_sns_topic` with a topic policy that lets `budgets.amazonaws.com` publish, and `aws_sns_topic_subscription` for email. **The email subscription must be confirmed manually** by clicking the link AWS sends.
3. **`Owner` tag:** add it to `local.etiquetas`; today Terraform only sets `Project`, `Environment` and `ManagedBy`. The approved `Owner` value is **PENDING**.
4. **Billing prerequisites:** activate the cost allocation tags `Project` and `Owner` in Billing and enable Cost Explorer. AWS needs time (up to about a day) before tagged costs appear. Confirm the exact timing in the AWS documentation.
5. **Two separate tests:** (a) an SNS test publish proves only the email transport; (b) the Budgets → SNS → email path is proven only when a threshold is actually crossed. Do not spend money on purpose to force it. A deliberately low test budget is an option to evaluate once the actual cost of a window is visible in Cost Explorer.
6. **Evidence to store:** redacted screenshot of the budget, the SNS subscription confirmed, and the received email with timestamp.
7. **Sequence:** this must be in place **before the next AWS window** (see the sequential gate in the acceptance register).

## Estimación con tarifas oficiales v1.1 — precios de lista de AWS (Español)

**Fecha:** 2026-10-21 · **Región:** `us-east-1` · **Estado:** hoja de cálculo con precios de lista publicados por AWS. **No** es una exportación del AWS Pricing Calculator, **no** es una factura y **no** son datos de Cost Explorer.

**Método.** Las tarifas salen de los archivos públicos de la AWS Price List, descargados el 2026-10-21 (la tabla de tarifas de arriba, con su fecha de publicación). La calculadora puede redondear o aplicar la capa gratuita de otra forma. Son precios de lista bajo demanda, sin descuentos ni créditos.

**Supuestos (se cambian en un solo lugar).** 730 h/mes siempre encendido; **8 ventanas de 3 h = 24 h/mes** en el escenario por ventanas; NAT `t4g.micro` de 8 GB (ADR-0022); RabbitMQ `t4g.small` de 20 GB (ADR-0013); Airflow `t4g.medium` de 30 GB (arquitectura v1); RDS `db.t4g.micro` de 20 GB con 1 día de backups dentro de la asignación gratuita; 1 ALB con 2 IPv4 públicas y 1 LCU como techo; 2 APIs On-Demand y 2 tareas de tipo Spot cotizadas **al techo On-Demand** (la lista de precios no publica Spot); Spark de 2 vCPU / 8 GB durante 6 h/mes; S3 de 5 GB; ECR de 2 GB; 2 GB de logs al mes. Lo que desaparece con `terraform destroy` se cobra por hora; solo S3, ECR, almacenamiento de logs y Spark se cuentan como persistentes.

**Resultados.** Siempre encendido: unos **126 USD al mes** (unos **116** si se cumple el descuento Spot de hasta 70 % que cita la arquitectura, sin verificar). Ventanas de prueba: unos **5,6 USD al mes**, es decir, unos **0,51 USD por ventana de 3 horas** más unos **1,5 USD al mes** persistentes. **Conciliación con el ADR-0020 (seis semanas):** siempre encendido da unos 160–174 USD (ADR-0020: 165–170), y cinco semanas de ventanas más una semana final continua dan unos **35 USD** (ADR-0020: 30–40). Las cifras coinciden. **Sin cotizar (PENDIENTE):** Cloud Map y zona DNS privada, CloudTrail, KMS, AWS Budgets, transferencia de datos de la NAT, backups de RDS por encima de lo gratuito, tarifas reales de Spot y EKS (por separado, EG-41).

**Para obtener el enlace de la calculadora (unos 15 minutos):** https://calculator.aws/#/ → *Create estimate* → US East (N. Virginia) → agregar EC2, EBS gp3, IPv4 pública, RDS PostgreSQL, ALB, Fargate ARM, S3, ECR, CloudWatch y SNS con las cantidades de la tabla → 730 h (siempre encendido) y 24 h (ventanas), dos estimaciones → *Save and share* → pegar los dos enlaces aquí.

**Qué falta para probar el presupuesto y la notificación SNS (CA3 y CA4).** (1) Julián define el límite en USD y el correo de alertas, sin subirlos al repositorio. (2) Terraform: `aws_budgets_budget` con umbrales real y proyectado, `aws_sns_topic` con política que permita publicar a `budgets.amazonaws.com` y suscripción por correo, que **se confirma a mano** con el enlace que envía AWS. (3) Agregar la etiqueta `Owner` a `local.etiquetas` (hoy solo hay `Project`, `Environment` y `ManagedBy`); el valor aprobado está **PENDIENTE**. (4) Activar las etiquetas de asignación de costos y Cost Explorer en Billing; los costos con etiquetas tardan en aparecer (hasta cerca de un día, a confirmar en la documentación de AWS). (5) Dos pruebas distintas: la publicación de prueba en SNS solo prueba el correo, y el recorrido Budgets → SNS → correo se prueba únicamente cuando se cruza un umbral real, sin gastar a propósito. (6) Guardar capturas sin datos sensibles. (7) Todo esto debe estar listo **antes de la próxima ventana de AWS**.
