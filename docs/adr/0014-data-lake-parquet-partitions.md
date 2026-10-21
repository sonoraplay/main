# ADR-0014 — Data Lake Parquet layout / Diseño de particiones Parquet

| Field / Campo | Value / Valor |
|---|---|
| Status / Estado | **Proposed / Propuesto** |
| Date / Fecha | 2026-10-21 |
| Story / Historia | EG-31 |
| Decision owner / Responsable | María Clara; review by Julián and Andrea |

## English

**Context.** SonoraPlay must retain original events, apply deterministic validity rules, calculate royalties with per-play traceability and serve analytical queries. The architecture already specifies S3 Bronze/Silver/Gold and Parquet; this ADR formalizes the logical layout.

**Decision proposed.** Use three private encrypted S3 zones: `bronze/`, `silver/`, `gold/`. Store analytical datasets in Parquet, partitioning by `year=YYYY/month=MM/country=CC` for datasets that have a defined country; source snapshots without country may partition by date only. Bronze keeps raw source payloads in their original format plus immutable metadata, rather than forcing raw JSON into Parquet. Silver and Gold use Parquet. Never partition by user or event ID (excessive small files). Record schema version, UTC ingestion timestamp, run ID and source version. Deduplicate by event ID in Silver, retain rejected records with reasons, and make Gold settlement versions append-only.

**Alternatives.** A single unlayered bucket simplifies setup but loses audit separation; partitioning by user creates too many small partitions. Selected design favors lineage and bounded scan cost.

**Validation before acceptance.** Review exact country semantics, retention, late-arriving data, small-file compaction, encryption and IAM with EG-26/EG-33/EG-35. Verify a real Parquet read/write and a reconciliation run. This ADR does not assert those tests occurred.

## Español

**Contexto.** Se necesita conservar eventos originales, validar reproducciones, calcular regalías trazables y consultar resultados analíticos. La arquitectura ya propone S3 por capas y Parquet.

**Decisión propuesta.** Usar zonas privadas y cifradas `bronze/`, `silver/` y `gold/`. Bronze conserva el formato original de los eventos con metadatos inmutables; Silver y Gold almacenan Parquet. Particionar por `year=YYYY/month=MM/country=CC` cuando el conjunto tenga país definido; para fuentes sin país usar partición por fecha. Evitar particionar por usuario o evento. Guardar versión de esquema, instante UTC, ID de ejecución y versión de la fuente. Silver deduplica por evento y conserva motivos de rechazo. Gold mantiene versiones de liquidación sin sobrescribir.

**Alternativas.** Una única capa reduce configuración pero dificulta auditoría; particionar por usuario produce demasiados archivos pequeños.

**Validación pendiente.** Confirmar país, retención, datos tardíos, compactación, cifrado e IAM con EG-26/EG-33/EG-35. Probar lectura/escritura Parquet real y conciliación antes de aprobar el ADR.


## Amendment — event/play grain and partition semantics (English)

**Proposed, not approved.** Bronze raw transport events retain their original JSON/body and `event_id`; Parquet is required for Silver/Gold, not for raw Bronze payloads. Silver event deduplication uses `event_id`, then reconstructed logical plays use `play_id`; Gold `fact_plays` is one row per `play_id`. Preserve a play-to-event bridge. Use **playback country** for play facts and **billing country** for settlement/pool facts; never silently interchange them. UTC event time determines event/play partition, while the **settlement period** determines settlement partition. For missing country, use an explicitly documented unknown bucket or quarantine policy rather than fabricate a country. Record schema/rule version and late-arrival reprocessing windows; compaction must not mutate published settlement versions. The test gate must compare distinct reconstructed plays and published settlements, not only raw event counts.

## Enmienda — eventos, reproducciones y particiones (Español)

**Propuesta, no aprobada.** Bronze conserva mensajes originales con `event_id`; Silver y Gold usan Parquet. Silver deduplica eventos por `event_id`, reconstruye reproducciones por `play_id` y conserva la tabla puente; Gold tiene una fila por `play_id`. El país de reproducción corresponde a reproducciones y el país de facturación a liquidaciones y bolsas. La partición de eventos se deriva del tiempo UTC; la de liquidación, del período liquidado. Los países faltantes se ponen en cuarentena o en una partición desconocida explícita. Se registra versión de esquema/reglas, ventana de datos tardíos y compactación sin alterar liquidaciones publicadas. Validar conteos de reproducciones lógicas, no solamente mensajes.
