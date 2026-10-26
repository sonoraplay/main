---
sidebar_position: 3
title: "EG-32 · Presupuesto y alarma / Budget and alarm"
---

# EG-32 · Presupuesto y alarma de AWS / AWS budget and alarm

## Español

**Estado: desplegado en AWS; prueba de transporte SNS y alerta real de Budgets recibidas el 2026-10-23.** Esta página explica cómo desplegar y probar el presupuesto con aviso por correo (criterio 3 de EG-32) y las etiquetas `Project` y `Owner` (criterio 4). Alerta real de AWS Budgets recibida el 2026-10-23; falta la activación de etiquetas en Billing (ver «Evidencia de la prueba»). 

### Qué se agrega

| Pieza | Qué hace |
|---|---|
| Stack `infra/terraform/presupuesto/` | **Persistente**: sigue vigilando entre ventanas porque no se destruye con el `destroy` del stack principal (ADR-0020). Estado propio en S3: `sonoraplay/presupuesto.tfstate` |
| Presupuesto `sonoraplay-mensual` | 50 USD al mes, sobre el gasto bruto (no descuenta créditos). Avisa al 50 % y al 80 % del gasto real, y cuando la proyección supera el 100 % |
| Tema SNS y suscripción de correo | La suscripción requiere un correo válido; Budgets publica en el tema y el tema envía el correo. El correo **no está en el repositorio**: se pasa al aplicar |
| Etiqueta `Owner` | Valor `sonoraplay-equipo` en todos los recursos del stack principal, en el presupuesto y en el bootstrap |

El límite de **50 USD por mes calendario es una propuesta pendiente de aprobación del equipo**, no una cifra derivada directamente de los ~35 USD estimados **para seis semanas**. La hoja de EG-32 (PR #7) estima aproximadamente **5,6 USD por mes** en ventanas de prueba (8 × 3 h) y **126 USD por mes** en operación continua, con supuestos y exclusiones documentados. El escenario de seis semanas incluye una última semana encendida y no se debe comparar directamente con un límite mensual sin distribuir los costos por mes calendario. Antes del despliegue, registrar la proyección máxima de cada mes y confirmar el umbral elegido. **AWS Budgets avisa; no bloquea el gasto ni apaga recursos.** Se cambia con `-var limite_usd=...`.

### Aplicarlo (una sola vez, en CloudShell)

El bucket del estado ya existe y `infra/terraform/backend.hcl` se arma como en las ventanas. **Antes de ejecutar `apply`, confirmar con el equipo el umbral mensual, el correo receptor y el valor de `Owner`.** Reemplaza `TU_CORREO` por el correo que recibirá las alertas:

```bash
cd /tmp/sonoraplay
terraform -chdir=infra/terraform/presupuesto init -backend-config=../backend.hcl
terraform -chdir=infra/terraform/presupuesto plan -var correo_alertas=TU_CORREO -out=presupuesto.tfplan
terraform -chdir=infra/terraform/presupuesto apply presupuesto.tfplan
```

En un despliegue inicial, el plan debe crear 4 recursos: el tema, su política, la suscripción y el presupuesto. **No ejecutar `apply` sin un correo válido**, ni considerar el aviso operativo antes de confirmar la suscripción. El archivo `*.tfplan` está en `.gitignore`.

### Confirmar y probar

1. **Confirmar la suscripción.** AWS envía un correo «AWS Notification - Subscription Confirmation». Hay que pulsar **Confirm subscription**. Mientras no se confirme, la alarma no llega a nadie. Comprobación:
   ```bash
   aws sns list-subscriptions-by-topic --topic-arn "$(terraform -chdir=infra/terraform/presupuesto output -raw tema_sns_arn)" \
     --query 'Subscriptions[].SubscriptionArn'
   ```
   Debe mostrar un ARN y no `PendingConfirmation`.
2. **Prueba de transporte** (solo demuestra que SNS entrega el correo, no que Budgets dispare la alerta):
   ```bash
   aws sns publish --topic-arn "$(terraform -chdir=infra/terraform/presupuesto output -raw tema_sns_arn)" \
     --subject "Prueba EG-32" --message "Prueba de transporte SNS"
   ```
3. **El presupuesto existe:**
   ```bash
   CUENTA=$(aws sts get-caller-identity --query Account --output text)
   aws budgets describe-budget --account-id "$CUENTA" --budget-name sonoraplay-mensual
   aws budgets describe-notifications-for-budget --account-id "$CUENTA" --budget-name sonoraplay-mensual
   ```
4. **Recorrido real Budgets → SNS → correo.** Solo se prueba cuando se cruza un umbral, y AWS Budgets actualiza sus datos unas pocas veces al día (confirmar el tiempo exacto en la documentación de AWS). Sin gastar a propósito: después de una ventana, si el gasto bruto del mes ya pasa de 0,50 USD, baja el límite a 1 USD con `-var limite_usd=1`, espera el correo del umbral del 50 % y vuelve a 50. Guarda una captura del correo sin datos sensibles.

### Etiquetas `Project` y `Owner` (criterio 4)

- El stack principal las pone en todos los recursos con `default_tags` (`Owner` sale de `var.owner`). Se ven tras el próximo `apply`.
- El **bucket del estado ya existe** y no tiene `Owner`. **Primero consultar y guardar sus etiquetas actuales** con `aws s3api get-bucket-tagging --bucket "sonoraplay-$CUENTA-tfstate"`. El siguiente comando **reemplaza todas las etiquetas**, por lo que solo debe ejecutarse si las cuatro etiquetas listadas coinciden con las existentes más la nueva `Owner`; de lo contrario, preparar un `TagSet` que preserve todas las etiquetas actuales:
  ```bash
  aws s3api put-bucket-tagging --bucket "sonoraplay-$CUENTA-tfstate" --tagging \
    'TagSet=[{Key=Project,Value=sonoraplay},{Key=ManagedBy,Value=terraform},{Key=Stack,Value=bootstrap},{Key=Owner,Value=sonoraplay-equipo}]'
  ```
- Para que Cost Explorer separe los costos hay que **activar las etiquetas** en la consola: Billing and Cost Management → Cost allocation tags → activar `Project` y `Owner`. Aparecen después de que haya recursos con esas etiquetas y pueden tardar hasta cerca de un día.
- El stack de ECR ya lleva `Owner` en sus etiquetas desde el PR #24 (fusionado).

### Costo

- SNS por correo: los primeros 1.000 correos al mes son gratis (lista de precios de AWS).
- AWS Budgets: no se pudo comprobar su precio con la lista de precios usada en la hoja de EG-32. Confirmar en la documentación de AWS si los dos primeros presupuestos son gratuitos.

### Evidencia de la prueba (2026-10-23)

**Estado desplegado**, comprobado con llamadas de solo lectura: presupuesto `sonoraplay-mensual` de 50 USD mensuales con `IncludeCredit = false`; tres notificaciones (50 % y 80 % del gasto real, 100 % de la proyección); tema SNS `sonoraplay-presupuesto-alertas` sin cifrar; suscripción de correo **confirmada**; etiquetas `Project`, `Owner=sonoraplay-equipo`, `Environment`, `ManagedBy` y `Stack` en el tema. `Project` y `Owner` también están en los 5 repositorios de ECR y en el bucket de estado.

**Prueba de transporte.** Desde un CloudShell, Julián ejecutó `aws sns publish` con el asunto «Prueba EG-32»; SNS devolvió el `MessageId` `828ee581-a2c4-511d-8f19-86d42339f2a4`, y el correo **llegó a la bandeja principal** (no a spam) en el momento. Los comandos de comprobación previa devolvieron lo esperado. Esta prueba demuestra que SNS entrega el correo; **no** demuestra que AWS Budgets dispare la alerta.

**Alerta real de AWS Budgets (recibida el 2026-10-23, 19:29, hora local del buzón).** Llegó un correo del remitente `AWS Notifications` (`no-reply@sns.amazonaws.com`) con el asunto «AWS Budgets: sonoraplay-mensual has exceeded your alert threshold». Su cuerpo dice: presupuesto `sonoraplay-mensual`, tipo Cost, monto presupuestado 50,00 USD, tipo de alerta ACTUAL, umbral > 25,00 USD, **monto ACTUAL 25,50 USD**. Es decir, AWS Budgets cruzó el umbral del 50 % del gasto real y publicó en el tema SNS, que entregó el correo a la suscripción confirmada: **recorrido Budgets → SNS → correo demostrado**. Captura revisada por Julián el 2026-10-26; no se guarda en el repositorio porque muestra el número de cuenta.

**Efecto de `include_credit = false`.** El mismo día, Cost Explorer con créditos incluidos daba un costo neto cercano a 0, y sin créditos ni reembolsos 28,18 USD acumulados del 1 al 26 de octubre. Budgets avisó con 25,50 USD: es coherente con que el presupuesto mide el gasto bruto y no descuenta créditos (el comportamiento esperado de la configuración). No se compararon las dos cifras al centavo porque corresponden a fechas distintas.

**Activación de etiquetas (2026-10-26).** Julián activó `Owner` como etiqueta de asignación de costos en Billing (según su informe; no se guardó captura). La atribución en Cost Explorer solo cubre el gasto posterior a la activación y puede tardar hasta unas 24 horas.

**Sigue sin evidencia:** la atribución por `Project` y `Owner` en Cost Explorer. **Decisión (2026-10-26): se verifica en la próxima ventana de despliegue**, con el stack principal encendido y recursos con costo. Cómo: Cost Explorer → Group by → Tag → `Owner` (y `Project`), rango que cubra la ventana, y guardar el resultado sin datos de cuenta. Hasta entonces EG-32 sigue «En curso».

### Lo que no está probado

- El código pasó `terraform fmt`, `validate` en los tres stacks y Checkov (299 aprobados, 0 fallidos), y el stack está desplegado (ver arriba); lo que sigue sin probarse es lo listado como «Sigue sin evidencia».
- `include_credit = false`: la alerta de 25,50 USD es coherente con gasto bruto, pero no se comparó al centavo contra Cost Explorer.
- El correo de alertas, el valor de `Owner` y el límite son decisiones del equipo; los valores del código son una propuesta.

## English

**Status: deployed in AWS; SNS transport test and real Budgets alert received on 2026-10-23.** This page explains how to deploy and test the budget with email alerts (EG-32 criterion 3) and the `Project` and `Owner` tags (criterion 4). The real Budgets alert was received on 2026-10-23; only the Billing tag activation is still missing (see "Evidence of the test").

### What is added

| Piece | What it does |
|---|---|
| Stack `infra/terraform/presupuesto/` | **Persistent**: it keeps watching between windows because the main stack's `destroy` does not remove it (ADR-0020). Own S3 state: `sonoraplay/presupuesto.tfstate` |
| Budget `sonoraplay-mensual` | USD 50 per month on gross spend (credits are not deducted). It alerts at 50% and 80% of actual spend, and when the forecast exceeds 100% |
| SNS topic and email subscription | A valid recipient email is required; Budgets publishes to the topic and the topic sends the email. The email is **not in the repository**: it is passed at apply time |
| `Owner` tag | Value `sonoraplay-equipo` on every main-stack resource, on the budget stack and on the bootstrap |

The **USD 50 per calendar month threshold is a proposal awaiting team approval**, not a direct conversion of the approximately **USD 35 six-week** project estimate. The EG-32 worksheet (PR #7) estimates approximately **USD 5.6/month** for test windows (8 × 3 h) and **USD 126/month** for always-on operations, subject to documented assumptions and exclusions. The six-week scenario includes a final always-on week and must be allocated to calendar months before comparing it to a monthly threshold. Before deployment, record the peak projected spend in each calendar month and approve the threshold. **AWS Budgets sends alerts; it does not cap spending or stop resources.** Change the threshold with `-var limite_usd=...`.

### Apply it (once, in CloudShell)

The state bucket already exists and `infra/terraform/backend.hcl` is built as in the windows. **Before `apply`, obtain team confirmation of the monthly threshold, recipient email and `Owner` value.** Replace `TU_CORREO` with the address that will receive alerts. Run `init` with `-backend-config=../backend.hcl`, then `plan -var correo_alertas=TU_CORREO -out=presupuesto.tfplan` and `apply presupuesto.tfplan`, all with `-chdir=infra/terraform/presupuesto` (exact commands in the Spanish section above). On initial deployment, the plan must create 4 resources: the topic, its policy, the subscription and the budget. **Do not run `apply` without a valid email** or consider alerts operational until the subscription is confirmed. `*.tfplan` is in `.gitignore`.

### Confirm and test

1. **Confirm the subscription.** AWS sends an "AWS Notification - Subscription Confirmation" email; click **Confirm subscription**. Until then, nobody receives the alarm. Check with `aws sns list-subscriptions-by-topic`: it must show an ARN, not `PendingConfirmation`.
2. **Transport test** (it only proves SNS delivers the email, not that Budgets fires the alert): `aws sns publish` to the topic.
3. **The budget exists:** `aws budgets describe-budget` and `describe-notifications-for-budget` for `sonoraplay-mensual`.
4. **Real Budgets → SNS → email path.** It is only proven when a threshold is crossed, and AWS Budgets refreshes its data a few times a day (confirm the exact timing in the AWS documentation). Without spending on purpose: after a window, if the month's gross spend already exceeds USD 0.50, lower the limit to USD 1 with `-var limite_usd=1`, wait for the 50% email and set it back to 50. Keep a redacted screenshot of the email.

### `Project` and `Owner` tags (criterion 4)

- The main stack puts them on every resource through `default_tags` (`Owner` comes from `var.owner`). They show after the next `apply`.
- The **state bucket already exists** and has no `Owner`. First inspect and save existing tags using `aws s3api get-bucket-tagging --bucket "sonoraplay-$CUENTA-tfstate"`. The following command **replaces every tag**: only use it if the four listed tags match all existing tags plus `Owner`; otherwise build a `TagSet` that preserves every existing tag: `aws s3api put-bucket-tagging` with `Project`, `ManagedBy`, `Stack` and `Owner` (full command in the Spanish section above).
- For Cost Explorer to split costs, **activate the tags** in the console: Billing and Cost Management → Cost allocation tags → activate `Project` and `Owner`. They appear once resources carry them and can take up to about a day.
- The ECR stack already carries `Owner` in its tags since PR #24 (merged).

### Cost

- SNS email: the first 1,000 emails per month are free (AWS price list).
- AWS Budgets: its price could not be checked with the price list used in the EG-32 worksheet. Confirm in the AWS documentation whether the first two budgets are free.

### Evidence of the test (2026-10-23)

**Deployed state**, checked with read-only calls: budget `sonoraplay-mensual` of USD 50 per month with `IncludeCredit = false`; three notifications (50 % and 80 % of actual spend, 100 % of the forecast); unencrypted SNS topic `sonoraplay-presupuesto-alertas`; **confirmed** email subscription; tags `Project`, `Owner=sonoraplay-equipo`, `Environment`, `ManagedBy` and `Stack` on the topic. `Project` and `Owner` are also on the 5 ECR repositories and the state bucket.

**Transport test.** From a CloudShell, Julián ran `aws sns publish` with the subject "Prueba EG-32"; SNS returned `MessageId` `828ee581-a2c4-511d-8f19-86d42339f2a4`, and the email **arrived in the primary inbox** (not spam) right away. The pre-checks returned what was expected. This test shows that SNS delivers the email; it does **not** show that AWS Budgets fires the alert.

**Real AWS Budgets alert (received 2026-10-23, 19:29 mailbox local time).** An email from `AWS Notifications` (`no-reply@sns.amazonaws.com`) arrived with the subject "AWS Budgets: sonoraplay-mensual has exceeded your alert threshold". Its body states: budget `sonoraplay-mensual`, type Cost, budgeted amount USD 50.00, alert type ACTUAL, threshold > USD 25.00, **ACTUAL amount USD 25.50**. So AWS Budgets crossed the 50% actual-spend threshold and published to the SNS topic, which delivered the email to the confirmed subscription: **Budgets → SNS → email path demonstrated**. Julián reviewed the screenshot on 2026-10-26; it is not stored in the repository because it shows the account number.

**Effect of `include_credit = false`.** On the same day, Cost Explorer with credits included showed a net cost near zero, and excluding credits and refunds it showed USD 28.18 accumulated from 1 to 26 October. Budgets alerted at USD 25.50: this is consistent with the budget measuring gross spend and not deducting credits (the expected behavior of the setting). The two figures were not compared to the cent because they refer to different dates.

**Tag activation (2026-10-26).** Julián activated `Owner` as a cost allocation tag in Billing (as reported by him; no screenshot kept). Cost Explorer attribution only covers spend after activation and can take up to about 24 hours.

**Still without evidence:** attribution by `Project` and `Owner` in Cost Explorer. **Decision (2026-10-26): verify it in the next deployment window**, with the main stack running and billable resources. How: Cost Explorer → Group by → Tag → `Owner` (and `Project`), date range covering the window, and keep the result without account data. Until then EG-32 stays "In progress".

### Not tested

- The code passed `terraform fmt`, `validate` on the three stacks and Checkov (299 passed, 0 failed), and the stack is deployed (see above); what is still untested is what is listed under "Still without evidence".
- `include_credit = false`: the USD 25.50 alert is consistent with gross spend, but it was not compared to the cent against Cost Explorer.
- The alert email, the `Owner` value and the limit are team decisions; the values in the code are a proposal.
