---
sidebar_position: 6
title: "Cierre del Sprint 3 · Pendientes y responsables"
---

# Cierre del Sprint 3 · Lista única de pendientes y responsables

**Corte:** 2026-10-30 (revisado contra Jira y GitHub). Sprint 3 "S3 · AWS Foundations": 7 de 9 elementos están Finalizados; faltan EG-31 y EG-32.

**Cómo leer la columna «Responsable confirmado por»:**
- **Plan del día:** el responsable sale del plan de trabajo que pasó Julián.
- **Jira:** es la persona asignada en la tarea.
- **Por confirmar:** nadie lo ha confirmado todavía; es una propuesta.

## A. Para cerrar lo que queda del Sprint 3

| # | Pendiente | Tarea | Responsable | Confirmado por | Estado |
|---|---|---|---|---|---|
| 1 | Generar las dos URL compartibles del AWS Pricing Calculator (24/7 y ventanas) y entregarlas para pegarlas en `docs/costos/` | EG-32, criterio 1 | María Clara | Plan del día | Pendiente |
| 2 | Aprobar la matriz de EG-31 y decidir sus 3 puntos (criterios 1, 3 y 4) | EG-31 | Julián, con María Clara | Plan del día | Pendiente de firma |
| 3 | Decidir si el criterio 4 de EG-32 se cierra con la evidencia del 2026-10-30 o espera a la ventana con el stack principal | EG-32, criterio 4 | Julián | Plan del día (aprobaciones de Julián) | Pendiente de decisión |
| 4 | Etiquetas de los 5 repositorios de ECR y del bucket de estado, y correo real de Budgets del 23-oct en la bandeja | EG-32, criterios 3 y 4 | Julián y Andrea | Plan del día | **Hecho el 2026-10-30** |
| 5 | Definir quién accede a AWS y reservar la ventana de pruebas | EG-32 y verificaciones | Julián | **Por confirmar** (la actividad no tiene nombre en el plan) | Pendiente |
| 6 | Completar el Sprint 3 en el tablero y mover EG-31 y EG-32 al Sprint 4 | Tablero Jira | Julián | **Por confirmar** | Pendiente. En Jira el Sprint 3 sigue «activo» y EG-31 y EG-32 siguen asignadas solo a él; el Sprint 4 figura «futuro» (con fechas del 21 al 27 de octubre, ya pasadas) |

## B. Para cerrar EG-31 y EG-32 después (Sprint 4 o próxima ventana)

| # | Pendiente | Tarea | Responsable | Confirmado por | Estado |
|---|---|---|---|---|---|
| 7 | Verificar en Cost Explorer la atribución por `Project` y `Owner` de los recursos del stack principal | EG-32, criterio 4 | Julián | Decisión del 2026-10-26 | Depende de #5 |
| 8 | Lectura y escritura reales de Parquet en Silver; país, retención, datos tardíos y compactación | EG-35 (condiciones del ADR-0014) | María Clara (implementa) y Julián (revisor, en lugar de Joshua) | Jira (María Clara) y la descripción del PR #38 (revisor) | Sprint 4. El PR #38 («Spark Silver initial implementation and acceptance tests», de María Clara) es un borrador sin fusionar: `lint` falla por formato y las pruebas de Spark no se han ejecutado. EG-35 sigue en «Tareas por hacer» |
| 9 | Parquet real en Gold; conciliación por `play_id`; reserva sobre `settlement_id` | EG-37 (condiciones del ADR-0014) | Andrea | Jira | Sprint 4 |
| 10 | Cifrado e IAM de `silver/` y `gold/` | EG-26 / ADR-0014 | Julián | **Por confirmar** (la matriz de EG-31 lo propone) | Sprint 4 |

## C. Fuera del cierre del Sprint 3

| # | Pendiente | Tarea | Responsable | Confirmado por | Estado |
|---|---|---|---|---|---|
| 11 | Ensayo de la demo de 40 minutos: guion con tiempos, plan de respaldo y ventana de AWS | EG-50 | Julián | Plan del día | Ensayo propuesto para el 2026-10-31 a las 9:00; ventana y plan de respaldo sin definir. En Jira, EG-50 está en el Sprint 6 (3 al 6 de noviembre) y sin persona asignada |

## Cuándo se cierra cada tarea

- **EG-32** pasa a Finalizada cuando estén listos #1 y #3 (o #7 si se decide esperar la ventana).
- **EG-31** pasa a Finalizada cuando estén listos #2, #8, #9 y #10; hasta entonces sigue En curso.
- **Sprint 3** se completa con #6. Los pendientes de EG-31 y EG-32 pasan al Sprint 4 sin cerrarse.
