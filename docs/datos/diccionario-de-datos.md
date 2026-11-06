---
title: "EG-46 · Diccionario de datos / Data dictionary"
---

# Diccionario de datos (EG-46, entregable E-10)

Describe cada tabla y columna del modelo en PostgreSQL (`db/ddl/`) y cada conjunto del Data Lake. **Fuente** usa los códigos del enunciado: F1 catálogo de pistas (Kaggle), F2 eventos de reproducción, F3 suscripciones y pagos, F4 contratos, F5 ingresos publicitarios, F6 tasas de cambio, F7 países y monedas. «Derivada» indica que no viene de una fuente externa y nombra la regla que la produce. Los valores de ejemplo son sintéticos.

> **Estado: borrador por revisar.** Escrito a partir de `db/ddl/001` a `004` en `develop` y de los módulos del repositorio el 2026-11-03. **Nadie más lo ha revisado** (criterio 4 de la EG-46 pendiente). Una prueba (`tests/test_diccionario.py`) falla si una tabla o columna del DDL falta aquí o si aquí aparece una que ya no existe, pero **no** valida que las descripciones sean correctas. Las tablas de `db/ddl/005_orquestacion.sql` (`ingesta_diaria_estado`, `corridas_liquidacion`) viven en los PR de EG-34/EG-38 y se agregan cuando se fusionen.

Reglas citadas: RN-01 (30 s continuos), RN-02 (máx. 10 por usuario, pista y día), RN-03 (granjas), RN-04 (mes de atribución y offline), RN-05/RN-06 (bolsa y %), RN-07 (% por fecha), RN-08 (territorios excluidos), RN-10 (familia). Detalle: [ambigüedades](../analisis/ambiguedades-rn.md).

## 1. Base de datos relacional (RDS)

### F3 · Suscripciones

#### `planes`
Catálogo de planes. Fuente: F3 (seed EG-13).

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `plan_id` | smallint | No | Clave. `3` es el plan familiar (lo exige un CHECK de `suscripciones`) | F3 | `3` |
| `codigo` | text | No | `free`, `individual`, `familiar` o `estudiante`. Decide el componente de la bolsa: `free` → publicidad, el resto → suscripción (Q8) | F3 | `familiar` |
| `nombre` | text | No | Nombre comercial | F3 | `Plan Familiar` |
| `precio_usd` | numeric(8,2) | No | Precio mensual en USD, ≥ 0 | F3 | `14.99` |
| `max_miembros` | smallint | No | Miembros permitidos (1 a 6) | F3 | `6` |

#### `usuarios`
Personas con cuenta. Fuente: F3.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `usuario_id` | uuid | No | Clave. Es el `user_id` de los eventos F2 | F3 | `3b6f1a2c-5d4e-4f7a-9b8c-1d2e3f4a5b6c` |
| `nombre` | text | No | Nombre (sintético) | F3 | `Ana Pérez` |
| `email` | text | No | Correo. Sin `UNIQUE` a propósito: el seed inyecta duplicados (`seed_defectos`) | F3 | `ana@example.com` |
| `pais_facturacion` | char(2) | Sí | País ISO-2 que define la bolsa del usuario (Q6, RN-10). Nulo = defecto inyectado (`pais_facturacion_nulo`); la liquidación lanza error en vez de inventarlo | F3 | `CO` |
| `fecha_alta` | timestamptz | No | Alta de la cuenta (UTC) | F3 | `2026-03-04 15:20:00+00` |
| `fecha_baja` | timestamptz | Sí | Baja; si existe, ≥ `fecha_alta`. Insumo del churn (RN-09) | F3 | `2026-09-30 00:00:00+00` |

#### `grupos_familiares`
Un grupo por plan familiar. Fuente: F3.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `grupo_id` | uuid | No | Clave | F3 | `a1b2c3d4-0000-4000-8000-000000000001` |
| `titular_id` | uuid | No | Usuario que paga el plan (único por grupo). Su país de facturación manda sobre el de los miembros (RN-10, Q6) | F3 | `3b6f1a2c-…` |
| `creado_en` | timestamptz | No | Creación del grupo | F3 | `2026-03-04 15:25:00+00` |

#### `miembros_familia`
Miembros de cada grupo (máx. 6, vigilado por el disparador `trg_max_6_miembros`). Fuente: F3.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `grupo_id` | uuid | No | Grupo (clave compuesta) | F3 | `a1b2c3d4-…` |
| `usuario_id` | uuid | No | Miembro; único: un usuario, un grupo | F3 | `9c8d7e6f-…` |
| `rol` | text | No | `titular` o `miembro` | F3 | `miembro` |
| `fecha_union` | timestamptz | No | Cuándo entró al grupo | F3 | `2026-03-10 09:00:00+00` |

#### `suscripciones`
Una fila por periodo de un usuario en un plan. Solo una abierta por usuario. Fuente: F3.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `suscripcion_id` | uuid | No | Clave | F3 | `5e4d3c2b-…` |
| `usuario_id` | uuid | No | Usuario suscrito | F3 | `3b6f1a2c-…` |
| `plan_id` | smallint | No | Plan contratado | F3 | `2` |
| `grupo_id` | uuid | Sí | Solo en plan familiar (CHECK: `plan_id = 3` ⇔ hay grupo) | F3 | `a1b2c3d4-…` |
| `fecha_inicio` | date | No | Inicio | F3 | `2026-03-04` |
| `fecha_fin` | date | Sí | Fin; nulo = abierta. Con `motivo_fin` forman el par que define churn (RN-09) | F3 | `2026-08-31` |
| `motivo_fin` | text | Sí | `cambio_plan` (no es churn), `cancelacion` o `no_renovacion`. Nulo ⇔ `fecha_fin` nula | F3 | `cancelacion` |

#### `pagos`
Pagos de cada suscripción. Su `monto_usd` aprobado es la «suscripción neta» de la bolsa (Q5: no se descuenta nada más). Fuente: F3.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `pago_id` | uuid | No | Clave | F3 | `7a6b5c4d-…` |
| `suscripcion_id` | uuid | No | Suscripción pagada | F3 | `5e4d3c2b-…` |
| `fecha_pago` | date | No | Fecha del cobro | F3 | `2026-09-05` |
| `monto_usd` | numeric(10,2) | No | Monto en USD, ≥ 0 | F3 | `9.99` |
| `estado` | text | No | `aprobado` (cuenta) o `rechazado` (no cuenta) | F3 | `aprobado` |

#### `seed_defectos`
Defectos inyectados a propósito en el seed, para medir la calidad de datos. Derivada del seed.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `entidad` | text | No | Tabla afectada | Derivada (seed) | `usuarios` |
| `entidad_id` | uuid | No | Fila afectada | Derivada (seed) | `3b6f1a2c-…` |
| `tipo` | text | No | `email_duplicado` o `pais_facturacion_nulo` | Derivada (seed) | `pais_facturacion_nulo` |

### F4 · Contratos

#### `titulares_derechos`
Sellos, distribuidoras y sociedades de gestión que cobran regalías. Fuente: F4 (los identificadores salen de `titulares.parquet`, EG-12).

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `titular_id` | uuid | No | Clave | F4 | `00000000-0000-0000-0000-00000000000a` |
| `nombre` | text | No | Nombre del titular | F4 | `Sello Aurora` |
| `tipo` | text | No | `sello`, `distribuidora` o `sociedad_gestion` | F4 | `sello` |
| `pais` | char(2) | No | País del titular | F4 | `CO` |

#### `contratos`
Condiciones por titular y pista, con vigencia y territorio opcional. Una restricción de exclusión impide vigencias solapadas de la misma condición (RN-07). Fuente: F4.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `contrato_id` | uuid | No | Clave | F4 | `d0c0ffee-…` |
| `titular_id` | uuid | No | Titular del contrato | F4 | `00000000-…-0a` |
| `track_id` | varchar(22) | No | Pista (`track_id` de F1) | F4 / F1 | `23Mcmg5O8rBKAOzxvrTjnD` |
| `porcentaje` | numeric(5,2) | No | % del titular, de 0 a 100 (RN-06) | F4 | `80.00` |
| `territorio` | char(2) | Sí | Nulo = condición general; un país = condición propia de ese territorio (Q7) | F4 | `MX` |
| `valido_desde` | date | No | Inicio inclusivo de la vigencia (UTC) | F4 | `2026-01-01` |
| `valido_hasta` | date | Sí | Fin inclusivo; nulo = sin fin | F4 | `2026-09-14` |

#### `exclusiones_territoriales`
Países donde un contrato no paga (RN-08: 0 % e incidente). Fuente: F4.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `contrato_id` | uuid | No | Contrato (borrado en cascada) | F4 | `d0c0ffee-…` |
| `pais` | char(2) | No | País excluido | F4 | `AR` |

### Liquidación (reporte de regalías)

#### `liquidaciones`
Una fila por corrida de liquidación de un mes. **Append-only** (ADR-0007): volver a liquidar crea una fila nueva; la API muestra la de mayor `publicada_en`. Derivada.

| Columna | Tipo | Nulo | Descripción | Fuente / regla | Ejemplo |
|---|---|---|---|---|---|
| `liquidacion_id` | uuid | No | Clave. Trazabilidad: cada reproducción pagada conserva este ID (RNF-03) | Derivada (EG-37; determinista por `run_id`) | `0b9e…` |
| `periodo` | date | No | Primer día del mes UTC liquidado (ADR-0002) | Derivada | `2026-09-01` |
| `creada_en` | timestamptz | No | Inicio de la corrida | Derivada | `2026-10-03 06:00:00+00` |
| `publicada_en` | timestamptz | Sí | Nulo = en proceso; la API nunca muestra una liquidación sin publicar | Derivada | `2026-10-03 06:41:00+00` |

#### `reporte_regalias`
Una fila por titular, país de facturación, componente y % contractual. **Contrato de lectura de la API de sellos** (RF-05). Derivada. Se cumple `regalia_usd ≈ bolsa × participacion × porcentaje_contractual / 100`.

| Columna | Tipo | Nulo | Descripción | Fuente / regla | Ejemplo |
|---|---|---|---|---|---|
| `liquidacion_id` | uuid | No | Liquidación a la que pertenece (clave compuesta) | Derivada | `0b9e…` |
| `titular_id` | uuid | No | Titular que cobra | F4 | `00000000-…-0a` |
| `periodo` | date | No | Mes liquidado; coincide con el de su liquidación (FK compuesta) | Derivada | `2026-09-01` |
| `pais` | char(2) | No | País de **facturación**, que define la bolsa (Q6) | Derivada (RN-10) | `CO` |
| `componente` | text | No | `suscripcion` o `publicidad`; denominadores separados (Q8) | Derivada (ADR-0008) | `suscripcion` |
| `reproducciones_validas` | integer | No | Reproducciones pagables de esa fila | Derivada (RN-01, RN-02, RN-03) | `1840` |
| `participacion` | numeric(9,6) | No | Fracción de las reproducciones del componente en ese país, 0 a 1. Solo informativa | Derivada | `0.184000` |
| `porcentaje_contractual` | numeric(5,2) | No | % aplicado a esas reproducciones; una fila por % si cambió en el mes | F4 (RN-07, RN-08, Q7) | `80.00` |
| `regalia_usd` | numeric(14,2) | No | Regalía en USD, redondeada al centavo por mayor residuo (RNF-02, ADR-0007) | Derivada (RN-05, RN-06) | `412.37` |

### F5, F6 y F7 · Fuentes de la bolsa

#### `fuente_f7_paises`
Países y sus monedas. Fuente: F7 (dataset `mledoze/countries`, ADR-0021).

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `pais` | char(2) | No | ISO-2 en mayúsculas (clave) | F7 | `CO` |
| `region` | text | No | Región geográfica | F7 | `Americas` |
| `monedas` | text[] | No | Códigos ISO-4217 del país | F7 | `{COP}` |
| `actualizado_en` | timestamptz | No | Última carga | Derivada | `2026-10-20 12:00:00+00` |

#### `fuente_f6_tasas_diarias`
Cotizaciones diarias de moneda por USD. Fuente: F6 (Frankfurter v2).

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `moneda` | char(3) | No | ISO-4217 (clave) | F6 | `COP` |
| `fecha_observacion` | date | No | Día de la cotización (clave) | F6 | `2026-09-30` |
| `unidades_por_usd` | numeric(24,10) | No | Cuántas unidades de la moneda vale 1 USD, > 0 | F6 | `4123.5000000000` |
| `proveedor` | text | No | Origen del dato | F6 | `Frankfurter v2 (tasas combinadas)` |
| `extraido_en_utc` | timestamptz | No | Cuándo se descargó | Derivada | `2026-10-20 12:00:00+00` |

#### `fuente_f6_cierres`
Tasa de cierre de cada mes, la que convierte a USD (ADR-0021: no más de 5 días de antigüedad). Fuente: F6.

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `moneda` | char(3) | No | ISO-4217 (clave) | F6 | `COP` |
| `fecha_cierre` | date | No | Último día del mes (clave) | Derivada | `2026-09-30` |
| `fecha_observacion` | date | No | Día real de la cotización usada, ≤ `fecha_cierre` | F6 | `2026-09-30` |
| `unidades_por_usd` | numeric(24,10) | No | Unidades por USD, > 0 | F6 | `4123.5000000000` |
| `proveedor` | text | No | Origen del dato | F6 | `Frankfurter v2 (tasas combinadas)` |
| `extraido_en_utc` | timestamptz | No | Cuándo se descargó | Derivada | `2026-10-20 12:00:00+00` |

#### `fuente_f5_publicidad`
Ingresos publicitarios por país y mes, en moneda local. Fuente: F5 (generado reproduciblemente por la EG-30).

| Columna | Tipo | Nulo | Descripción | Fuente | Ejemplo |
|---|---|---|---|---|---|
| `mes` | date | No | Primer día del mes (clave) | F5 | `2026-09-01` |
| `pais` | char(2) | No | País (clave); existe en F7 | F5 | `CO` |
| `moneda` | char(3) | No | Moneda local del ingreso | F5 / F7 | `COP` |
| `ingresos_publicidad` | numeric(18,2) | No | Ingreso en moneda local, ≥ 0. Se convierte con la tasa de cierre y alimenta el 45 % del componente de publicidad (Q8) | F5 | `523481.00` |

## 2. Data Lake (S3, Parquet)

Zonas privadas y cifradas `bronze/`, `silver/` y `gold/`; particiones y reglas en [ADR-0014](../adr/0014-data-lake-parquet-partitions.md). `play_id` = `session_id`.

| Conjunto | Capa y ruta | Partición | Grano | Origen y estado |
|---|---|---|---|---|
| **Eventos F2 crudos** | Bronze `f2/fecha=AAAA-MM-DD/lote-*.jsonl` | Fecha UTC del `server_ts` | Un evento por línea, tal como llegó + `_ingested_at_utc` | Consumidor de RabbitMQ (EG-33). Duplicados por reintento posibles; se quitan por `event_id` |
| **Catálogo F1** | `catalogo_f1.parquet` (+ `track_generos.parquet`, `titulares.parquet`) | Sin partición (pequeño) | Una fila por `track_id` | EG-12; ver abajo |
| **Silver · reproducciones** | Silver | `year/month/country` (UTC corregido y país de reproducción) | Una fila por `play_id`, con `pagable` y `motivo_validez` | EG-35, **en borrador** (PR #38): columnas por confirmar |
| **Silver · cuarentena** | Silver | — | Una fila por reproducción rechazada, con `motivo_cuarentena` (`track_desconocido`, `sesion_sin_inicio`, `identidad_sesion_inconsistente`) | EG-35, en borrador |
| **Gold · reproducciones liquidadas** | Gold `plays_liquidados` | `periodo/pais_facturacion/liquidacion_id` | Una fila por reproducción pagada | EG-37 (PR en revisión) |

### Eventos F2 (Bronze)
Contrato completo en [eventos-f2.md](eventos-f2.md); esquema en `schemas/f2_evento.schema.json`.

| Campo | Tipo | Descripción | Ejemplo |
|---|---|---|---|
| `schema_version` | string | Versión del esquema (`1.0`) | `1.0` |
| `event_id` | uuid | Identificador del evento; clave de deduplicación (ADR-0004) | `c7e1d0a4-0401-4f2b-9a6e-5b3c2d1e0f01` |
| `event_type` | string | `start`, `pause`, `resume`, `skip` o `end` | `start` |
| `user_id` | uuid | = `usuarios.usuario_id` | `3b6f1a2c-…` |
| `device_id` | string | Dispositivo emisor | `android-7f3a9c21` |
| `track_id` | string | = `contratos.track_id` y F1 | `23Mcmg5O8rBKAOzxvrTjnD` |
| `session_id` | uuid | Una reproducción de una pista = `play_id` | `a7b8c9d0-…` |
| `device_ts` | timestamp UTC | Reloj del dispositivo, puede estar desfasado; se corrige en Silver (EG-22) | `2026-09-19T18:30:00.000Z` |
| `server_ts` | timestamp UTC | Reloj del servidor; define la partición y el mes (RN-04) | `2026-09-19T18:30:00.200Z` |
| `position_ms` | entero | Posición dentro de la pista, ms | `0` |
| `country_playback` | char(2) | País de **reproducción** (≠ país de facturación) | `CO` |
| `is_offline` | booleano | Reproducido sin conexión y sincronizado después (RN-04) | `false` |
| `_ingested_at_utc` | timestamp UTC | Solo en Bronze S3: instante en que el consumidor lo recibió (EG-33) | `2026-09-19T18:30:01.113Z` |

### Catálogo F1 (`catalogo_f1.parquet`)
Una fila por `track_id` (ADR-0003). Columnas de Kaggle conservadas más las derivadas.

| Columna | Descripción | Fuente | Ejemplo |
|---|---|---|---|
| `track_id` | Identificador de la pista (22 caracteres) | F1 | `23Mcmg5O8rBKAOzxvrTjnD` |
| `artists` | Artista(s) | F1 | `Kitri` |
| `album_name` | Álbum | F1 | `Hikare Inochi` |
| `track_name` | Título | F1 | `Sympathy` |
| `popularity` | Popularidad 0 a 100 | F1 | `49` |
| `duration_ms` | Duración en ms | F1 | `210760` |
| `explicit` | Contenido explícito | F1 | `False` |
| `danceability`, `energy`, `key`, `loudness`, `mode`, `speechiness`, `acousticness`, `instrumentalness`, `liveness`, `valence`, `tempo`, `time_signature` | Características de audio de Spotify | F1 | `0.69`, `0.423`, … |
| `genero_principal` | Género de la fila de mayor popularidad; empate → primero alfabético | Derivada (ADR-0003) | `acoustic` |
| `n_generos` | Cuántos géneros tiene la pista (detalle en `track_generos.parquet`) | Derivada | `1` |
| `titular_id` | Titular asignado por el seed (EG-12) | Derivada | `00000000-…-0a` |
