---
sidebar_position: 3
title: "EG-50 · Guion de la demo de 40 minutos"
---

# EG-50 · Guion de la demo de 40 minutos, con plan de respaldo

> **Estado:** guion escrito el 2026-11-08 a partir de lo que existe en `develop`. **No se ha ensayado** (el ensayo es el criterio pendiente de EG-50). Lo que dice "en vivo" depende de una ventana de AWS que **todavía no se ha hecho**; cada parte tiene su plan de respaldo.

## Idea central
Mostrar que un evento de reproducción se vuelve regalía pagada a un sello, con trazabilidad, y que cuesta unos pocos dólares: **simulador → RabbitMQ → Bronze (S3) → Silver → Gold → liquidación en RDS → API de sellos**, orquestado por Airflow, y **destruido el mismo día**.

## Antes de empezar (30 min antes)
- [ ] Ventana de AWS aplicada (`docs/infraestructura/README` y `infra/terraform/README.md`), RDS sembrado y datos de prueba F5/F6/F7 cargados (`infra/ventana/`).
- [ ] Imagen `sonoraplay/spark:<sha>` en ECR (`infra/scripts/verificar-imagen-spark.sh`).
- [ ] Pestañas abiertas: diagrama de arquitectura, consola de ECS, Airflow, la API de sellos, Cost Explorer y el PR/CI en GitHub.
- [ ] Un token de sello emitido para una consulta (`docs/esqueleto.md`).
- [ ] **Plan de respaldo listo:** capturas y la salida de la última corrida guardadas en una carpeta local.

## Tiempos (40 min)
| Min | Parte | Qué se muestra | En vivo | Respaldo |
|---|---|---|---|---|
| 0–3 | Problema y reglas | Qué se paga: RN-01 (30 s), RN-02 (tope de 10), RN-04 (offline), Q6/Q8 (bolsa por país y componente) | No | — |
| 3–8 | Arquitectura | `arquitectura-v1.md`: capas Bronze/Silver/Gold, ECS Fargate ARM, ADR-0012/0014/0018 | No | Diagrama impreso |
| 8–13 | Datos entran | Simulador publica eventos; el consumidor escribe lotes `f2/fecha=…` en S3 (EG-33), sin pérdidas | Parcial | Salida guardada del consumidor |
| 13–20 | Silver | Job de Spark en Fargate: sesiones, reglas, cuarentena; marcador de commit `commits/<run_id>.json` | Sí, si la ventana está lista | Log guardado de la tarea de ECS |
| 20–27 | Gold y liquidación | Gold liquida el mes: `liquidacion_id`, conciliación por `play_id`, carga idempotente a RDS | Sí | `esqueleto` en local (`docker compose --profile esqueleto up --build`) |
| 27–31 | Airflow | DAG diario y mensual, reintentos, la tarea que verifica el marcador antes de marcar el día | Parcial | Capturas de la corrida con Airflow real (`docs/orquestacion/airflow-dags.md`) |
| 31–35 | Resultado para el sello | `GET /me/reportes` con su token: regalía, `liquidacion_id`, reproducciones que la respaldan (RNF-03) | Sí | Respuesta guardada |
| 35–38 | Costo y rendimiento | 0,75 USD/mes de cómputo de Spark (cota), 42 min para 400 000 reproducciones, 5,61 USD/mes en ventanas frente a 126,21 USD/mes 24/7 | No | `eg39-informe-spark.md`, `eg32-cotizacion-lista-de-precios.md` |
| 38–40 | Cierre y destrucción | `infra/scripts/destruir-todo.sh` y la comprobación de que no queda nada facturable | Sí | Salida guardada de la prueba |

## Plan de respaldo (si algo falla)
1. **Falla AWS o la red:** correr todo en local con el esqueleto y la cadena Bronze → Silver → Gold (`docs/esqueleto.md`, `tests/spark/test_integracion_bronze_silver_gold.py`) y mostrar el CI en verde de `develop`.
2. **Falla una tarea de Fargate:** mostrar el log de la corrida anterior y el CI; decir qué falló, no taparlo.
3. **Falla Airflow:** mostrar las capturas y la evidencia de `airflow-dags.md`.

## Qué NO afirmar
- Que corre en producción: es una ventana de pruebas con datos sintéticos.
- Que Airflow corre en EC2: hoy no está en Terraform (se probó con Airflow local y con Docker).
- Que EKS fue desplegado: se cerró como comparación documentada (ADR-0018).
- Cifras de Spark en Fargate: se midieron en `local[2]`, no en Fargate.
- Que EG-35 está aceptada: su revisión de aceptación sigue pendiente.

## Después
Destruir **ese mismo día** (`destruir-todo.sh --yes`), guardar la salida y revisar Cost Explorer al día siguiente.
