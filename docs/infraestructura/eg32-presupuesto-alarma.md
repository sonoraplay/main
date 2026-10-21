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
| Tema SNS y suscripción de correo | Budgets publica en el tema y el tema envía el correo. El correo **no está en el repositorio**: se pasa al aplicar |
| Etiqueta `Owner` | Valor `sonoraplay-equipo` en todos los recursos del stack principal, en el presupuesto y en el bootstrap |

El límite de 50 USD sale de la estimación de EG-32: unos 35 USD en las seis semanas del proyecto (ventanas más la última semana encendida), con margen para imprevistos. Se cambia con `-var limite_usd=...`.

### Aplicarlo (una sola vez, en CloudShell)

El bucket del estado ya existe y `infra/terraform/backend.hcl` se arma como en las ventanas. Reemplaza `TU_CORREO` por el correo que recibirá las alertas:

```bash
cd /tmp/sonoraplay
terraform -chdir=infra/terraform/presupuesto init -backend-config=../backend.hcl
terraform -chdir=infra/terraform/presupuesto plan -var correo_alertas=TU_CORREO -out=presupuesto.tfplan
terraform -chdir=infra/terraform/presupuesto apply presupuesto.tfplan
```

El plan debe crear 4 recursos: el tema, su política, la suscripción y el presupuesto. El archivo `*.tfplan` está en `.gitignore`.

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
- El **bucket del estado ya existe** y no tiene `Owner`. Se agrega a mano, conservando las etiquetas actuales (este comando reemplaza todas):
  ```bash
  aws s3api put-bucket-tagging --bucket "sonoraplay-$CUENTA-tfstate" --tagging \
    'TagSet=[{Key=Project,Value=sonoraplay},{Key=ManagedBy,Value=terraform},{Key=Stack,Value=bootstrap},{Key=Owner,Value=sonoraplay-equipo}]'
  ```
- Para que Cost Explorer separe los costos hay que **activar las etiquetas** en la consola: Billing and Cost Management → Cost allocation tags → activar `Project` y `Owner`. Aparecen después de que haya recursos con esas etiquetas y pueden tardar hasta cerca de un día.
- El stack de ECR del PR #10 también necesitará `Owner` en sus etiquetas cuando se fusione.

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
| SNS topic and email subscription | Budgets publishes to the topic and the topic sends the email. The email is **not in the repository**: it is passed at apply time |
| `Owner` tag | Value `sonoraplay-equipo` on every main-stack resource, on the budget stack and on the bootstrap |

The USD 50 limit comes from the EG-32 estimate: about USD 35 over the six project weeks (windows plus the always-on final week), with room for surprises. Change it with `-var limite_usd=...`.

### Apply it (once, in CloudShell)

The state bucket already exists and `infra/terraform/backend.hcl` is built as in the windows. Replace `TU_CORREO` with the address that will receive alerts. Run `init` with `-backend-config=../backend.hcl`, then `plan -var correo_alertas=TU_CORREO -out=presupuesto.tfplan` and `apply presupuesto.tfplan`, all with `-chdir=infra/terraform/presupuesto` (exact commands in the Spanish section above). The plan must create 4 resources: the topic, its policy, the subscription and the budget. `*.tfplan` is in `.gitignore`.

### Confirm and test

1. **Confirm the subscription.** AWS sends an "AWS Notification - Subscription Confirmation" email; click **Confirm subscription**. Until then, nobody receives the alarm. Check with `aws sns list-subscriptions-by-topic`: it must show an ARN, not `PendingConfirmation`.
2. **Transport test** (it only proves SNS delivers the email, not that Budgets fires the alert): `aws sns publish` to the topic.
3. **The budget exists:** `aws budgets describe-budget` and `describe-notifications-for-budget` for `sonoraplay-mensual`.
4. **Real Budgets → SNS → email path.** It is only proven when a threshold is crossed, and AWS Budgets refreshes its data a few times a day (confirm the exact timing in the AWS documentation). Without spending on purpose: after a window, if the month's gross spend already exceeds USD 0.50, lower the limit to USD 1 with `-var limite_usd=1`, wait for the 50% email and set it back to 50. Keep a redacted screenshot of the email.

### `Project` and `Owner` tags (criterion 4)

- The main stack puts them on every resource through `default_tags` (`Owner` comes from `var.owner`). They show after the next `apply`.
- The **state bucket already exists** and has no `Owner`. Add it by hand, keeping the current tags (the command replaces all of them): `aws s3api put-bucket-tagging` with `Project`, `ManagedBy`, `Stack` and `Owner` (full command in the Spanish section above).
- For Cost Explorer to split costs, **activate the tags** in the console: Billing and Cost Management → Cost allocation tags → activate `Project` and `Owner`. They appear once resources carry them and can take up to about a day.
- The ECR stack in PR #10 will also need `Owner` in its tags once merged.

### Cost

- SNS email: the first 1,000 emails per month are free (AWS price list).
- AWS Budgets: its price could not be checked with the price list used in the EG-32 worksheet. Confirm in the AWS documentation whether the first two budgets are free.

### Not tested

- None of this was applied in AWS: it passed `terraform fmt`, `validate` on the three stacks and Checkov (299 passed, 0 failed).
- It is not yet known whether `include_credit = false` produces exactly the expected gross spend in this account: confirm it in the Budgets console after the first day.
- The alert email, the `Owner` value and the limit are team decisions; the values in the code are a proposal.
