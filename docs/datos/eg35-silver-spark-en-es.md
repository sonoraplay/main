# EG-35 — Spark Silver implementation / Implementación Silver en Spark

## English

**Status: implementation draft, not acceptance evidence.** The Spark job lives in
`src/sonoraplay/spark/silver.py`. It reads F2 JSON with an explicit
`StructType`, keeps the earliest `server_ts` per `event_id`, groups by
`session_id`, and delegates clock correction and segment reconstruction to
`reglas/sesiones.py`. Offline month attribution is delegated to
`reglas/atribucion.py`. It quarantines unknown tracks and inconsistent or
start-less sessions, applies RN-01 and the global daily RN-02 cap, and writes
Silver Parquet partitioned by corrected UTC `year/month` and playback country.

**Local validation:** install compatible PySpark and run
`uv run --with pyspark pytest tests/spark/test_silver.py`.
The tests reuse F2 defect fixtures. The Spark suite has **not yet been executed
in this PR**. Run a real Parquet write/read and record command, environment,
timestamp, input/output counts and paths before checking CA6.

**Open issues / acceptance gates:**
- The current `run()` uses overwrite and is **for isolated test paths only**.
  Do not run against existing S3 partitions until idempotent incremental
  processing, late-arrival reprocessing and safe writes are implemented.
- Validate malformed JSON, duplicate IDs with conflicting payloads, and
  incomplete sessions; the existing reconstruction currently counts open
  segments as zero but does not emit a dedicated `sin_fin` quality flag.
- Add lineage fields (`run_id`, UTC ingestion time and source version), verify
  S3 encryption/IAM, choose compaction and retention, and record a real
  Parquet round trip.
- Confirm `applyInPandas` grouped-session memory behavior and performance at
  the intended volume; test RN-02 across reprocessing windows and day boundaries.
- Verify all RN-01, RN-02 and RN-04 fixtures from EG-17/EG-22, including
  29/30 seconds, the eleventh play and offline cutoff. Existing tests only
  cover selected defect scenarios.
- ADR-0014's Parquet Gold round trip and settlement reconciliation belong
  to EG-37; they are not asserted by this implementation.

## Español

**Estado: borrador de implementación, no evidencia de aceptación.** El trabajo
está en `src/sonoraplay/spark/silver.py`. Lee F2 con `StructType` explícito,
conserva el menor `server_ts` por `event_id`, agrupa por `session_id` y
reutiliza `reglas/sesiones.py` para corregir el reloj y reconstruir los tramos.
La atribución mensual reutiliza `reglas/atribucion.py`. Envía a cuarentena
pistas desconocidas y sesiones inconsistentes o sin inicio, aplica RN-01 y
el tope diario global RN-02, y escribe Parquet particionado por año/mes UTC
corregido y país de reproducción.

**Validación local:** instalar PySpark compatible y ejecutar
`uv run --with pyspark pytest tests/spark/test_silver.py`.
Las pruebas usan fixtures F2 existentes. **Todavía no se han ejecutado**.
Antes de aceptar CA6 hay que probar lectura y escritura reales de Parquet,
registrando comando, entorno, fecha, conteos y rutas.

**Pendientes:** la escritura actual sobrescribe rutas y **solo sirve para
pruebas aisladas**; no usarla sobre S3 existente hasta implementar
reprocesamiento seguro e idempotente. Faltan control de JSON inválido, marcas
de calidad `sin_fin`, metadatos de linaje, cifrado/IAM, compactación,
retención, pruebas de volumen y cobertura completa de EG-17/EG-22 (29/30 s,
reproducción 11 y corte offline). La prueba de Gold y conciliación es EG-37.

**Review owner / Revisor:** Julián reemplaza a Joshua. No se solicita cierre
de EG-35 hasta demostrar todos los criterios y condiciones aplicables.
