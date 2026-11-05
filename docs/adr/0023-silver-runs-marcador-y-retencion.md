# ADR-0023 · Silver: corridas inmutables, marcador de commit y retención de `runs/`

| Campo | Valor |
|---|---|
| Estado | **Aceptado por Julián** el 2026-11-05 (revisor de EG-35 y responsable de EG-34); **pendiente de revisión de María Clara**, autora del diseño de Silver |
| Fecha | 2026-11-05 |
| Historia que lo origina | EG-34 (DAG diario) y EG-35 (Silver) |
| Referencias | PR #38 (diseño de Silver), PR #56 (CLI), PR #45 (DAG), [ADR-0007](0007-cierre-mes-ajustes-reliquidacion.md), [ADR-0014](0014-data-lake-parquet-partitions.md) |

## 1. Contexto

El diseño de Silver (PR #38) escribe cada corrida en un prefijo **inmutable** `runs/<run_id>`, con su cuarentena en `quarantine/runs/<run_id>`, y publica al final un marcador `commits/<run_id>.json` sin sobrescribir. Los consumidores leen un `run_id` explícito y verificado; no hay puntero mutable. Quedaban abiertas tres preguntas que bloqueaban habilitar el DAG, y no hubo respuesta del equipo de Silver a tiempo. Se deciden aquí con valores razonables y fáciles de cambiar.

## 2. Decisiones

1. **`fecha` del marcador** = el último día UTC **cerrado** incluido en el snapshot (el día que procesa la corrida). La liquidación mensual exige el marcador del día 2 del mes siguiente (RN-04, `fechas_requeridas`). Es lo que ya implementa `publish_verified_snapshot` y lo que verifica `verificar_silver_publicado`.
2. **Un intento, un prefijo.** El DAG usa `<run_id de Airflow saneado>.<intento>` y nunca reutiliza un prefijo: repetir un `run_id` falla (`FileExistsError`) sin tocar lo publicado.
3. **Retención por edad en S3:** los prefijos `runs/` y `quarantine/runs/` del bucket de Silver **expiran a los 45 días** (variable `silver_runs_retencion_dias`, mínimo 35), publicados u huérfanos. Cubren el mes liquidado, el margen de RN-04 y un re-proceso. Los marcadores de `commits/` **no caducan**.
4. **Rutas:** `silver_root = s3a://<bucket-silver>` y `quarantine_root = s3a://<bucket-silver>/quarantine`. Así `runs/`, `quarantine/runs/` y `commits/` quedan bajo prefijos que la regla de ciclo de vida y el permiso de lectura de Airflow (`commits/*`) distinguen.

## 3. Por qué

- Los datos que la liquidación necesita de forma permanente quedan en Gold (`plays_liquidados`, con su `liquidacion_id`) y en RDS (RNF-03); Silver es reconstruible desde Bronze, así que no hace falta conservarlo indefinidamente.
- El borrado por edad no necesita código ni permisos de borrado en el rol de Spark, y limpia sin distinguir los intentos huérfanos, que son invisibles de todos modos (sin marcador no se pueden leer).
- Conservar los marcadores es barato y hace que leer un run ya expirado falle con un error claro y no con datos a medias.

## 4. Consecuencias y qué no cubre

- Reconstruir el historial completo en cada corrida diaria hace crecer el almacenamiento por corrida (≈ 45 copias vivas); su costo real lo mide EG-39. Si resulta alto, bajar la retención hacia el mínimo de 35 días o pasar a reconstrucción incremental (cambiaría el diseño).
- Un re-proceso de la liquidación de un mes con más de 45 días de antigüedad exige reconstruir Silver desde Bronze.
- La regla de ciclo de vida **no se ha aplicado en AWS**; solo se valida en el CI de Terraform.
- Si María Clara decide otros valores, cambiar la variable o este ADR no exige tocar código.
