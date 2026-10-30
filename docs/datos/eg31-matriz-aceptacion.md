# EG-31 · Matriz de aceptación (borrador para revisión)

**Corte:** 2026-10-30 · **Fuentes:** criterios de EG-31 en Jira, `docs/datos/eg31-modelo-dimensional-en-es.md`, `docs/adr/0014-data-lake-parquet-partitions.md`, `docs/datos/eg31-eg32-acceptance-evidence-en-es.md`.
**Alcance:** esta matriz compara el diseño con los criterios de Jira. No hay ejecución de Spark ni de Parquet, y ningún criterio está demostrado de extremo a extremo.

Leyenda: **D** = diseño documentado · **P** = pendiente de ejecutar · **H** = hueco o decisión abierta.

| # | Criterio de Jira | Lo que dice el diseño | Estado | Hueco o decisión para Julián | Prueba que lo cierra | Quién |
|---|---|---|---|---|---|---|
| 1 | `fact_plays` (grano: una reproducción, con estado de validez) y sus dimensiones: fecha, usuario, canción, artista, titular, país, plan y dispositivo | `fact_plays` tiene una fila por `play_id` (= `session_id`), válida o inválida, con `validity_status` y `invalid_reason`. Las 8 dimensiones están definidas con sus claves y el diagrama Mermaid. | **D** | **H:** el titular **no** se une directo a `fact_plays`. Llega por la asignación contractual (`bridge_play_settlement`) y la vigencia del contrato. El artista llega por la canción. Decidir si eso cumple "sus dimensiones". | Una `play_id` por reproducción tras repetir la carga; los 8 vínculos resueltos o con miembro "desconocido" explícito | María Clara (EG-35) |
| 2 | `fact_settlement` con grano titular × país × mes × versión, tipo original o ajuste (RF-09) | Es una **vista** sobre `fact_settlement_detail`, que añade componente y porcentaje contractual. La bolsa va aparte en `fact_country_pool`. `settlement_type` original/ajuste y `parent_settlement_id`. | **D** | Ninguno de diseño. Falta probar que ajustes solo agregan filas y que cuadra con `reporte_regalias`. | Conciliación por titular × país × mes × versión; bolsa por país sin pasarse de 0,01 USD | Andrea y María Clara (EG-37) |
| 3 | Cada fila de `fact_plays` lleva el ID de la liquidación en que se pagó (RNF-03) | Campo `settlement_id` anulable hasta el pago, que apunta a `liquidaciones.liquidacion_id`. Historial completo en `bridge_play_settlement`. | **D / P** | **H, la reserva:** un campo escalar no refleja todos los ajustes. Si EG-37 no garantiza una liquidación principal única por reproducción, hay que pasar a una vista de la liquidación vigente. Es un cambio al contrato que firmaste el 23-oct. | Consulta de integridad: pagadas con liquidación publicada; inválidas con `settlement_id` nulo | María Clara y Andrea (EG-37) |
| 4 | Capas Bronze / Silver / Gold en Parquet particionado por año, mes y país, documentadas, y ADR-0014 escrito | ADR-0014 escrito. Silver y Gold en Parquet con `year=YYYY/month=MM/country=CC`; sin país, partición por fecha. | **D** | **H:** Bronze **no** es Parquet; guarda el formato original del evento. El criterio dice "Bronze/Silver/Gold en Parquet". Confirmar que esa excepción te parece bien. Aceptado con condiciones el 22-oct, y las condiciones siguen abiertas. | Lectura y escritura reales de Parquet; país, retención, datos tardíos, compactación, cifrado e IAM | María Clara (EG-35), Andrea (EG-37) y tú (cifrado e IAM con EG-26) |
| 5 | El modelo soporta churn (RN-09) y engagement (horas, canciones por sesión) | Churn con suscriptores de pago al inicio del mes como denominador; no cuenta cambios de plan ni usuarios gratis. Engagement con segundos válidos / 3600 y canciones distintas por sesión. | **D** | Ninguno de diseño. Sin consultas de muestra ejecutadas. | Consultas de muestra de EG-42 contra un cálculo manual | María Clara (EG-42) |

## Condiciones abiertas del ADR-0014

| Condición | Cierra | Quién |
|---|---|---|
| Lectura y escritura reales de Parquet en Silver y Gold | EG-35 y EG-37 | María Clara y Andrea |
| Conciliación por `play_id` y liquidaciones publicadas | EG-37 | Andrea |
| Semántica de país, retención, datos tardíos, compactación | EG-35 | María Clara |
| Cifrado e IAM de `silver/` y `gold/` | EG-26 | Julián |

## Qué se aprueba hoy y qué no

- **Aprobable hoy (nivel diseño):** los cinco criterios están cubiertos por el contrato dimensional v2, con los tres puntos H arriba como decisiones explícitas.
- **No aprobable hoy:** cerrar EG-31 como "Finalizada". La evidencia de ejecución depende de EG-35 y EG-37 (Sprint 4).
- La meta del día "EG-31 listo para cierre" se entiende como **diseño aprobado, tarea abierta hasta tener evidencia de Spark/Parquet**.

## Aprobación

| Decisión | Resultado | Fecha |
|---|---|---|
| Criterio 1: titular por asignación contractual, no directo en `fact_plays` | ☐ Aceptado ☐ Cambiar | |
| Criterio 3: `settlement_id` escalar más puente, con la reserva | ☐ Aceptado ☐ Cambiar | |
| Criterio 4: Bronze en formato original, no Parquet | ☐ Aceptado ☐ Cambiar | |
| Diseño de EG-31 aprobado; tarea abierta hasta la evidencia | ☐ Sí ☐ No | |

Aprobado por: Julián Vanegas · Revisado con: María Clara

## Inconsistencias en la documentación existente (para corregir en el PR de consolidación)

- `eg31-eg32-acceptance-evidence-en-es.md` aún dice que PR #3 "needs ADR-0021 decision" y que el PR #7 está pendiente de fusión; ambos ya están fusionados.
- En la fila CA3 de EG-32 de ese mismo archivo el estado es "Parcial", pero la sección correctiva dice "Cumplido".
- El ADR-0014 conserva en el cuerpo "Decision proposed" y "Validación antes de aprobar", aunque el estado es "Aceptado con condiciones".
