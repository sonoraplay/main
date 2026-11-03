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
`uv run --with pyspark==4.0.1 pytest -q tests/spark/test_silver.py`.
The tests reuse F2 defect fixtures. The dedicated `spark-silver` CI job now installs PySpark 4.0.1 and executes
the suite without `importorskip`. Its result must be verified before acceptance. Run a real Parquet write/read and record command, environment,
timestamp, input/output counts and paths before checking CA6.

**Open issues / acceptance gates:**
- The current `run()` uses `errorifexists`, so it refuses to overwrite existing output. This is **not** a complete idempotent late-arrival reprocessing strategy.
  Do not run against existing S3 partitions until idempotent incremental
  processing, late-arrival reprocessing and safe writes are implemented.
- Validate malformed JSON, duplicate IDs with conflicting payloads, and
  incomplete sessions; the existing reconstruction currently counts open
  segments as zero but does not emit a dedicated `sin_fin` quality flag.
- Verify the newly added lineage fields (`run_id`, UTC ingestion time and source version) in CI and downstream Parquet; verify
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
`uv run --with pyspark==4.0.1 pytest -q tests/spark/test_silver.py`.
Las pruebas usan fixtures F2 existentes. Se agregó un job de CI que instala PySpark 4.0.1 y ejecuta las pruebas sin saltarlas.
Es necesario comprobar su resultado antes de aceptar el criterio.
Antes de aceptar CA6 hay que probar lectura y escritura reales de Parquet. Se añadió la prueba de round trip,
pero falta verificar su ejecución y registrar comando, entorno, fecha, conteos y rutas.

**Pendientes:** `run()` utiliza `errorifexists`: no sobrescribe rutas existentes, pero aún
falta una estrategia idempotente para reprocesar datos tardíos en S3. Faltan control de JSON inválido, marcas
de calidad `sin_fin`, pruebas del linaje, cifrado/IAM, compactación,
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

## Lineage contract / Contrato de linaje

**English:** `run()` now requires keyword arguments `run_id` and `source_version`.
It captures one UTC ingestion timestamp for the run and writes all three fields
on both Silver and quarantine rows. The caller is responsible for supplying the
real upstream version and a unique run ID. The transformation accepts these
three fields together for deterministic tests. This is **not** a guarantee of
atomic writes or safe late-arrival replay. CI evidence for this change is pending.

**Español:** `run()` ahora exige `run_id` y `source_version` como argumentos
nombrados. Registra un instante UTC por ejecución y guarda los tres campos en
Silver y cuarentena. Quien ejecuta el proceso debe indicar la versión real del
origen y un identificador único. La transformación permite suministrar los tres
campos para pruebas reproducibles. Esto **no** garantiza escrituras atómicas ni
reprocesamiento seguro de datos tardíos. Falta comprobar este cambio en CI.


## Daily orchestration decision / Decisión de orquestación diaria

**English — decision for the next implementation, not yet delivered:** Keep
ADR-0014's `year/month/country` Silver partitions. Do not introduce a daily
partition. Rebuild each **complete affected playback month to date**, including
events required to finish sessions crossing UTC midnight, and reevaluate RN-02
on the full UTC day. Offline events that arrive after the initial window may
affect an older playback month; they must be detected and their entire affected
month recalculated rather than dropped. Around the RN-04 cutoff, account for
both playback and settlement months without confusing their partition keys.

A daily batch that overwrites a month partition with only one day's plays is
**forbidden**: it would erase prior days. Dynamic partition overwrite is safe
from that specific data-loss bug *only* when the incoming data covers every
record in every partition being replaced. It is still not an atomic S3
transaction. The design therefore needs staged output and a safe publication
protocol before production use, plus integration tests for retries, cross-day
sessions, late events, and an empty or missing source day. Until that work is
proven, `run()` remains non-idempotent and must not be connected to Airflow
as if it met EG-34's idempotency acceptance criterion.

**Español — decisión para la siguiente implementación, todavía pendiente:**
Conservamos las particiones `year/month/country` del ADR-0014. No agregaremos
partición por día. Reconstruiremos cada **mes de reproducción afectado completo
hasta la fecha procesada**, incluyendo los eventos necesarios para cerrar
sesiones que cruzan medianoche UTC, y volveremos a calcular RN-02 con todos los
datos del día UTC. Los eventos offline que lleguen más tarde pueden modificar
un mes de reproducción anterior: habrá que detectar ese mes y recalcularlo
completo, no ignorar la llegada tardía. El mes de liquidación RN-04 es distinto
del mes usado para particionar las reproducciones.

**No** se puede sobrescribir una partición mensual con datos de un solo día,
porque se borrarían reproducciones anteriores. `dynamic overwrite` solo evita
ese problema concreto si se reconstruye **toda** la información de cada
partición afectada; no convierte la escritura en una transacción atómica de S3.
Antes de usarlo en AWS necesitamos escritura temporal, publicación segura y
pruebas de reintentos, cruces de medianoche, eventos tardíos y ausencia de datos
Bronze del día solicitado. Hasta comprobarlo, `run()` sigue sin ser
idempotente y no debe conectarse al DAG como si cumpliera EG-34.


## F2 validation / Validación F2

**English:** Spark's explicit JSON `StructType` does not enforce non-null
values during ingestion. The transform now fails closed on null or blank
mandatory F2 fields. A session with conflicting playback countries or schema
versions goes to quarantine with an explicit reason instead of inheriting an
arbitrary value. Duplicate or null catalog keys are rejected before the join.
These checks require a passing Spark CI run before being considered verified.

**Español:** Declarar `StructType` no garantiza que Spark rechace campos nulos
al leer JSON. La transformación ahora rechaza los campos F2 obligatorios nulos
o vacíos. Si una sesión contiene países de reproducción o versiones de esquema
contradictorios, pasa a cuarentena con un motivo explícito. También se rechazan
claves duplicadas o nulas en el catálogo F1 antes del `join`. Falta confirmar
estas pruebas en el CI de Spark.


## Airflow CLI guard / Protección del CLI para Airflow

**English:** The module now exposes `python -m sonoraplay.spark.silver
--fecha YYYY-MM-DD` and accepts `--bronze`, `--catalogo`, `--silver`,
`--cuarentena`, `--run-id` and `--source-version`. Paths and lineage
arguments can also be supplied through `SONORAPLAY_BRONZE_PATH`,
`SONORAPLAY_CATALOG_PATH`, `SONORAPLAY_SILVER_PATH`,
`SONORAPLAY_QUARANTINE_PATH`, `SONORAPLAY_RUN_ID` and
`SONORAPLAY_SOURCE_VERSION`. It validates the UTC date and required
arguments, then **exits nonzero without writing**. This is intentional:
the existing `run()` cannot safely replay a date or publish an entire
affected month atomically. Do **not** activate `SILVER_JOB_COMMAND` yet.

**Español:** El módulo ya reconoce el comando `python -m
sonoraplay.spark.silver --fecha AAAA-MM-DD` y los argumentos de rutas y
linaje indicados arriba. Valida la fecha UTC y los parámetros obligatorios,
pero **termina con error sin escribir datos**. Es una protección deliberada:
`run()` todavía no garantiza reejecuciones idempotentes ni publicación
atómica de los meses afectados. **No** habilitar todavía
`SILVER_JOB_COMMAND` en Airflow.


## Bronze read-window planner / Planificación de lectura Bronze

**English:** `bronze_window(fecha)` now returns all UTC server-arrival days
from the first of the month through the closed processing day. For processing
days 1–3, it starts at the first of the previous month, to include the RN-04
grace period. `bronze_partition_paths(root, fecha)` produces paths matching
EG-33's `f2/fecha=YYYY-MM-DD` layout. These are **planning helpers**, not a
complete incremental processing implementation. Because Bronze is partitioned
by `server_ts`, a late offline playback can belong to an older playback month
than this arrival window. A correct production job must inspect affected
playback months and rebuild all affected partitions, including older months
when needed. The helpers do not publish or overwrite Silver.

**Español:** `bronze_window(fecha)` calcula los días de llegada UTC desde el
primero del mes hasta la fecha cerrada. En los días 1–3 incluye el mes anterior
por el margen de RN-04. `bronze_partition_paths(root, fecha)` genera rutas
compatibles con `f2/fecha=AAAA-MM-DD` de EG-33. Son **funciones de
planificación**, no una solución completa de reproceso. Bronze se particiona
por `server_ts`; una reproducción offline tardía puede pertenecer a un mes
de reproducción mucho más antiguo. Antes de publicar, hay que detectar y
reconstruir todos los meses afectados. Estas funciones no sobrescriben Silver.
