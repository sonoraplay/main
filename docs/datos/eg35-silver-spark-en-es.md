# EG-35 — Spark Silver implementation / Implementación Silver en Spark

## English

**Status: implementation draft, not acceptance evidence.** The Spark job lives in
`src/sonoraplay/spark/silver.py`. It reads F2 JSON with an explicit
`StructType`, keeps the earliest `server_ts` per `event_id`, groups by
`session_id`, and delegates clock correction and segment reconstruction to
`reglas/sesiones.py`. Offline month attribution is delegated to
`reglas/atribucion.py`. It quarantines unknown tracks and inconsistent or
start-less sessions, applies RN-01 and the RN-02 daily cap per user, track and UTC day, and writes
Silver Parquet partitioned by corrected UTC `year/month` and playback country.

**Local validation:** install compatible PySpark and run
`uv run --with pyspark pytest tests/spark/test_silver.py`.
The tests reuse F2 defect fixtures. The dedicated `spark-silver` CI job now installs PySpark 3.5.7 and executes
the suite without `importorskip`. Its result must be verified before acceptance. Run a real Parquet write/read and record command, environment,
timestamp, input/output counts and paths before checking CA6.

**Open issues / acceptance gates:**
- The current `run()` uses `errorifexists`, so it refuses to overwrite existing output. This is **not** a complete idempotent late-arrival reprocessing strategy.
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
  29/30 seconds, the eleventh play and offline cutoff. Existing tests cover selected defect scenarios and the 30-second boundary;
  29 seconds, the eleventh play and the offline cutoff still need Spark coverage.
- ADR-0014's Parquet Gold round trip and settlement reconciliation belong
  to EG-37; they are not asserted by this implementation.

## Español

**Estado: borrador de implementación, no evidencia de aceptación.** El trabajo
está en `src/sonoraplay/spark/silver.py`. Lee F2 con `StructType` explícito,
conserva el menor `server_ts` por `event_id`, agrupa por `session_id` y
reutiliza `reglas/sesiones.py` para corregir el reloj y reconstruir los tramos.
La atribución mensual reutiliza `reglas/atribucion.py`. Envía a cuarentena
pistas desconocidas y sesiones inconsistentes o sin inicio, aplica RN-01 y
el tope RN-02 por usuario, pista y día UTC, y escribe Parquet particionado por año/mes UTC
corregido y país de reproducción.

**Validación local:** instalar PySpark compatible y ejecutar
`uv run --with pyspark pytest tests/spark/test_silver.py`.
Las pruebas usan fixtures F2 existentes. Se agregó un job de CI que instala PySpark 3.5.7 y ejecuta las pruebas sin saltarlas.
Es necesario comprobar su resultado antes de aceptar el criterio.
Antes de aceptar CA6 hay que probar lectura y escritura reales de Parquet. Se añadió la prueba de round trip,
pero falta verificar su ejecución y registrar comando, entorno, fecha, conteos y rutas.

**Pendientes:** `run()` utiliza `errorifexists`: no sobrescribe rutas existentes, pero aún
falta una estrategia idempotente para reprocesar datos tardíos en S3. Faltan control de JSON inválido, marcas
de calidad `sin_fin`, metadatos de linaje, cifrado/IAM, compactación,
retención, pruebas de volumen y cobertura completa de EG-17/EG-22 (29/30 s,
reproducción 11 y corte offline). La prueba de Gold y conciliación es EG-37.

**Review owner / Revisor:** Julián reemplaza a Joshua. No se solicita cierre
de EG-35 hasta demostrar todos los criterios y condiciones aplicables.

## Acceptance evidence / Evidencia de aceptación

**English:** This PR is still a draft. A CI test passing without PySpark does not
count as Spark evidence. Check the dedicated `spark-silver` job and preserve its
run URL and test counts. A local Parquet round trip does not prove S3 encryption,
IAM, compaction, safe late-event reprocessing, or the Gold reconciliation in
ADR-0014. Do not close EG-31 or EG-35 based on this draft alone.

**Español:** Este PR sigue en borrador. Un test aprobado sin PySpark no demuestra
que Spark funcione. Hay que revisar el job `spark-silver` y guardar el enlace de
la ejecución y sus resultados. El round trip local de Parquet no demuestra
cifrado en S3, permisos IAM, compactación, reproceso seguro de eventos tardíos
ni conciliación Gold del ADR-0014. EG-31 y EG-35 siguen pendientes de evidencia.
