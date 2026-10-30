---
sidebar_position: 5
title: "EG-32 · Guion de verificaciones AWS"
---

# EG-32 · Guion de verificaciones AWS (14:00–16:00)

**Quiénes:** Andrea y Julián · **Dónde:** CloudShell de la cuenta del proyecto, región `us-east-1` (ADR-0009) · **Tiempo:** 2 h.
Todos los comandos son de **solo lectura**. No se crea, cambia ni borra nada, y no se enciende el stack principal.

**Regla de evidencia:** pegar en el registro (sección 6) solo lo que no identifica la cuenta. El número de cuenta aparece en los ARN y en las capturas: tacharlo antes de guardar nada. No subir capturas con la cuenta ni el correo al repositorio.

## 0. Preparación (5 min)

```bash
export AWS_REGION=us-east-1
CUENTA=$(aws sts get-caller-identity --query Account --output text)
```

## 1. Etiquetas `Project` y `Owner` en recursos desplegados (30 min)

Esperado: `Project=sonoraplay` y `Owner=sonoraplay-equipo` en el tema SNS, los 5 repositorios de ECR y el bucket de estado. El stack principal está destruido, así que no se puede comprobar ahí.

```bash
# Tema SNS
TEMA=$(aws sns list-topics --query "Topics[?contains(TopicArn,'sonoraplay-presupuesto-alertas')].TopicArn" --output text)
aws sns list-tags-for-resource --resource-arn "$TEMA" --query "Tags[?Key=='Project'||Key=='Owner']"
```

```bash
# Repositorios de ECR (debe listar 5, cada uno con Project y Owner)
for ARN in $(aws ecr describe-repositories --query 'repositories[].repositoryArn' --output text); do
  echo "${ARN##*/}"; aws ecr list-tags-for-resource --resource-arn "$ARN" --query "tags[?Key=='Project'||Key=='Owner']" --output text
done
```

```bash
# Bucket de estado
aws s3api get-bucket-tagging --bucket "sonoraplay-$CUENTA-tfstate" --query "TagSet[?Key=='Project'||Key=='Owner']"
```

```bash
# Vista global: todo lo que lleva Owner (los ARN incluyen la cuenta: tachar al copiar)
aws resourcegroupstaggingapi get-resources --tag-filters Key=Owner,Values=sonoraplay-equipo --query 'ResourceTagMappingList[].ResourceARN'
```

Si algún recurso no tiene alguna de las dos etiquetas, anotarlo; no corregir en esta sesión.

## 2. Activación como etiquetas de asignación de costos (10 min)

Esperado: `Project` y `Owner` en estado `Active`. `Owner` se activó el 2026-10-26.

```bash
aws ce list-cost-allocation-tags --tag-keys Project Owner --region us-east-1 --query 'CostAllocationTags[].[TagKey,Status,LastUpdatedDate]' --output table
```

Alternativa en consola: Billing and Cost Management → Cost allocation tags. Si `Owner` aparece `Inactive`, activarla ahí y anotar la hora.

## 3. Atribución en Cost Explorer (30 min)

AWS aplica la activación **hacia adelante**: solo cuenta el gasto posterior al 2026-10-26. Con el stack principal destruido, el gasto tiene solo los recursos persistentes (ECR, bucket, SNS) y puede ser de centavos.
Ajustar las fechas: `Start` desde el 2026-10-27; `End` es exclusivo.

```bash
for CLAVE in Owner Project; do
  aws ce get-cost-and-usage --region us-east-1 \
    --time-period Start=2026-10-27,End=2026-10-31 --granularity DAILY \
    --metrics UnblendedCost --group-by Type=TAG,Key=$CLAVE \
    --query 'ResultsByTime[].Groups[].[Keys[0],Metrics.UnblendedCost.Amount]' --output table
done
```

Cada llamada de `aws ce` cuesta unos 0,01 USD. La consola (Cost Explorer → Group by → Tag) es gratis y sirve para la captura.

**Cómo interpretar el resultado**
- **Aparece `Owner$sonoraplay-equipo` con un monto:** atribución comprobada para los recursos persistentes. Anotar el monto y el rango.
- **Solo aparece `Owner$` (vacío):** el gasto existe pero sin etiqueta. Puede ser que el costo sea de un servicio sin etiqueta (por ejemplo Cost Explorer, que no la hereda) o que los datos aún no estén. Anotar qué servicios lo causan en la consola (Group by → Service).
- **No hay datos:** documentar la limitación (sección 5) y dejar la verificación completa para la ventana de despliegue.

## 4. Presupuesto y correo SNS (25 min)

```bash
# El presupuesto existe, con 50 USD y sin descontar créditos (IncludeCredit = false)
aws budgets describe-budget --account-id "$CUENTA" --budget-name sonoraplay-mensual \
  --query 'Budget.{Nombre:BudgetName,Limite:BudgetLimit,Periodo:TimeUnit,CostTypes:CostTypes}'
# Tres notificaciones: 50 % y 80 % del gasto real, 100 % de la proyección
aws budgets describe-notifications-for-budget --account-id "$CUENTA" --budget-name sonoraplay-mensual \
  --query 'Notifications[].[NotificationType,ComparisonOperator,Threshold]' --output table
# La suscripción de correo está confirmada (esperado: 1)
aws sns list-subscriptions-by-topic --topic-arn "$TEMA" --query "length(Subscriptions[?SubscriptionArn!='PendingConfirmation'])"
```

**Evidencia del correo real.** El 2026-10-23 llegó un correo de AWS Budgets de `sonoraplay-mensual` (ACTUAL > 25,00 USD, monto 25,50 USD). Ya está documentado y **no hay que repetirlo**. En la reunión, solo confirmar que el correo sigue en la bandeja principal y guardar una captura **con la cuenta tachada** fuera del repositorio.
No publicar otra prueba en SNS ni bajar el límite: no hace falta para este cierre.

## 5. Si Cost Explorer aún no muestra datos

Registrar este texto en el documento y en Jira:

> Atribución por `Project` y `Owner` no verificable el DD-MM-AAAA: las etiquetas están activas en Billing desde el 2026-10-26, pero Cost Explorer no muestra gasto atribuido (stack principal destruido; solo hay recursos persistentes de costo mínimo). Verificación pendiente para la próxima ventana de despliegue: Cost Explorer → Group by → Tag → `Owner` y `Project`.

## 6. Registro de resultados

| Comprobación | Resultado | Hora | Quién | Captura o salida guardada en |
|---|---|---|---|---|
| Tema SNS con `Project` y `Owner` | Correcto: `Project=sonoraplay`, `Owner=sonoraplay-equipo` | 2026-10-30 | Julián y Andrea | Salida de CloudShell (sin cuenta) |
| 5 repositorios ECR con `Project` y `Owner` | No consultado hoy (verificado el 2026-10-23) | | | |
| Bucket de estado con `Project` y `Owner` | No consultado hoy (verificado el 2026-10-23) | | | |
| `Project` y `Owner` activas en Billing | Correcto: ambas `Active` (`Owner` 2026-10-26, `Project` 2026-10-23) | 2026-10-30 | Julián y Andrea | Salida de CloudShell |
| Atribución en Cost Explorer (monto, rango) | Correcto con recursos persistentes: 3 días entre 0,00053 y 0,00058 USD por día, rango 2026-10-27 a 2026-10-30; grupo sin etiqueta negativo casi igual (probables créditos, sin confirmar) | 2026-10-30 | Julián y Andrea | Salida de CloudShell |
| Presupuesto de 50 USD, `IncludeCredit = false` | Correcto | 2026-10-30 | Julián y Andrea | Salida de CloudShell |
| 3 notificaciones del presupuesto | Correcto: ACTUAL > 50, ACTUAL > 80, FORECASTED > 100 (el tipo de umbral no se mostró) | 2026-10-30 | Julián y Andrea | Salida de CloudShell |
| Suscripción de correo confirmada | Correcto: 1 suscripción confirmada | 2026-10-30 | Julián y Andrea | Salida de CloudShell |
| Correo real de Budgets (23-oct) visible | No reportado | | | |

**Cierre de la sesión:** pasar este registro a `eg32-presupuesto-alarma.md` y comentar el resultado en EG-32.
