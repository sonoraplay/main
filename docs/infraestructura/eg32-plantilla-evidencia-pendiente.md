---
sidebar_position: 4
title: "EG-32 · Plantilla de evidencia pendiente / Pending evidence template"
---

# EG-32 · Plantilla de evidencia pendiente / Pending evidence template

## Español

**Estado: plantilla vacía.** Los campos `PENDIENTE` se llenan solo con resultados reales. No inventar cifras ni URL, y no publicar el número de cuenta, el correo ni capturas que los muestren. Al terminar, trasladar el resumen a `eg32-presupuesto-alarma.md` y comentar en Jira (EG-32).

### 1. Atribución por `Project` y `Owner` en Cost Explorer (criterio 4)

Requisitos: stack principal encendido con recursos que cuesten, y `Owner` activada en Billing (2026-10-26) desde hace al menos ~24 h.

| Dato | Valor |
|---|---|
| Fecha de la ventana de despliegue | PENDIENTE |
| Rango de fechas en Cost Explorer | PENDIENTE |
| Agrupación usada | Group by → Tag → `Owner` y luego `Project` |
| Costo atribuido a `Owner=sonoraplay-equipo` (USD) | PENDIENTE |
| Costo atribuido a `Project=sonoraplay` (USD) | PENDIENTE |
| Costo «sin etiqueta» (USD) y servicios que lo causan | PENDIENTE |
| Captura sin datos de cuenta guardada en | PENDIENTE (no subir al repositorio si muestra la cuenta) |

Criterio de aceptación: el gasto de la ventana aparece separado por `Project` y `Owner`; si hay gasto «sin etiqueta», se explica qué servicio no hereda las etiquetas.

### 2. URL del AWS Pricing Calculator (criterio 1)

Generar a mano en la web (calculator.aws) con el inventario de Terraform y copiar con «Share». No hay cifras de tarifa aquí: se toman de la estimación.

| Escenario | URL compartible | Total mensual de la estimación (USD) | Fecha |
|---|---|---|---|
| A · 24/7 | PENDIENTE | PENDIENTE | PENDIENTE |
| B · ventanas de prueba (8 × 3 h) | PENDIENTE | PENDIENTE | PENDIENTE |

Al llenar la tabla, reemplazar también los `PENDING` de la sección «URL de la calculadora» en `docs/costos/eg32-aws-cost-analysis-v1-en-es.md` y comparar con la hoja v1.1 (≈126 USD/mes y ≈5,6 USD/mes) explicando cualquier diferencia.

### 3. Cierre

- [ ] Tabla 1 completa
- [ ] Tabla 2 completa
- [ ] Resumen trasladado a `eg32-presupuesto-alarma.md`
- [ ] Comentario en Jira EG-32 con el resultado
- [ ] Decisión de Julián sobre mover EG-32 a «Finalizada»

## English

**Status: empty template.** `PENDIENTE` fields are filled only with real results. Do not invent figures or URLs, and do not publish the account number, the email address or screenshots showing them. When done, move the summary to `eg32-presupuesto-alarma.md` and comment on Jira (EG-32).

### 1. Attribution by `Project` and `Owner` in Cost Explorer (criterion 4)

Prerequisites: main stack running with billable resources, and `Owner` activated in Billing (2026-10-26) at least ~24 h earlier.

| Item | Value |
|---|---|
| Deployment window date | PENDIENTE |
| Cost Explorer date range | PENDIENTE |
| Grouping used | Group by → Tag → `Owner`, then `Project` |
| Cost attributed to `Owner=sonoraplay-equipo` (USD) | PENDIENTE |
| Cost attributed to `Project=sonoraplay` (USD) | PENDIENTE |
| «No tag» cost (USD) and the services causing it | PENDIENTE |
| Screenshot without account data stored at | PENDIENTE (do not commit if it shows the account) |

Acceptance: the window's spend is split by `Project` and `Owner`; any untagged spend is explained by naming the service that does not inherit the tags.

### 2. AWS Pricing Calculator URLs (criterion 1)

Generate by hand on the web (calculator.aws) from the Terraform inventory and copy with "Share". No rates are given here: they come from the estimate.

| Scenario | Shareable URL | Estimate monthly total (USD) | Date |
|---|---|---|---|
| A · 24/7 | PENDIENTE | PENDIENTE | PENDIENTE |
| B · test windows (8 × 3 h) | PENDIENTE | PENDIENTE | PENDIENTE |

When filling the table, also replace the `PENDING` values in the calculator-URL section of `docs/costos/eg32-aws-cost-analysis-v1-en-es.md` and compare with the v1.1 worksheet (≈USD 126/month and ≈USD 5.6/month), explaining any difference.

### 3. Closing

- [ ] Table 1 complete
- [ ] Table 2 complete
- [ ] Summary moved to `eg32-presupuesto-alarma.md`
- [ ] Jira EG-32 comment with the result
- [ ] Julián's decision on moving EG-32 to "Finalizada"
