---
sidebar_position: 3
title: "EG-32 · Presupuesto y alarma / Budget and alarm"
---

# EG-32 · Presupuesto y alarma de AWS / AWS budget and alarm

## Español

**Estado: código listo, NO aplicado en AWS.** Esta página explica cómo desplegar y probar el presupuesto con aviso por correo (criterio 3 de EG-32) y las etiquetas `Project` y `Owner` (criterio 4). Todavía no hay evidencia de AWS.

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

### Lo que no está probado

- Nada de esto se aplicó en AWS: pasó `terraform fmt`, `validate` en los tres stacks y Checkov (299 aprobados, 0 fallidos).
- No se sabe aún si `include_credit = false` produce exactamente el gasto bruto esperado en esta cuenta: confirmarlo en la consola de Budgets tras el primer día.
- El correo de alertas, el valor de `Owner` y el límite son decisiones del equipo; los valores del código son una propuesta.

## English

**Status: code ready, NOT applied in AWS.** This page explains how to deploy and test the budget with email alerts (EG-32 criterion 3) and the `Project` and `Owner` tags (criterion 4). There is no AWS evidence yet.

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

### Not tested

- None of this was applied in AWS: it passed `terraform fmt`, `validate` on the three stacks and Checkov (299 passed, 0 failed).
- It is not yet known whether `include_credit = false` produces exactly the expected gross spend in this account: confirm it in the Budgets console after the first day.
- The alert email, the `Owner` value and the limit are team decisions; the values in the code are a proposal.
