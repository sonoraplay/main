# ADR-0004 · Esquema JSON de eventos F2 con deduplicación por `event_id`

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-07 |
| Historia que lo origina | HU 06 · EG-15 |
| Responsable | Andrea |
| Revisó | María Clara |
| Referencias | F2, RNF-04, RN-01, RN-02, RN-03, RN-04, RN-08, EG-11 Q1 / Q4 / Q6, ADR-0002, ADR-0005, ADR-0008, ADR-0013 |

## 1. Contexto

F2 son los eventos de reproducción que envía la app (`start`, `pause`, `resume`, `skip`, `end`). De ellos salen las reproducciones que validan RN-01/RN-02 (EG-17), las señales de granja de RN-03 (EG-18) y la atribución offline de RN-04 (EG-22), así que un evento contado dos veces o perdido mueve dinero.

Los eventos viajan por una cola (RabbitMQ, ADR-0013) con entrega **al menos una vez**: si la app no recibe la confirmación de la API de ingesta, reenvía el evento, y si el consumidor se cae antes de confirmar un mensaje, la cola lo vuelve a entregar. RNF-04 exige que esos reintentos no dupliquen reproducciones (idempotencia). Además, el simulador F2 inyecta cinco defectos de negocio que el esquema debe poder **representar** para que las capas siguientes los detecten: evento sin fin, reloj del dispositivo desfasado, track desconocido, duplicado por reintento y país de facturación distinto del de reproducción.

Hay que fijar dos cosas: el contrato del evento (campos, tipos, formato de fechas) y cómo se reconoce un evento repetido.

## 2. Qué debe cumplir la decisión

- **Requisito:** RNF-04, un reintento no puede crear una reproducción nueva ni sumar ms escuchados.
- **Negocio:** RN-01 (EG-11 Q1), el evento debe permitir reconstruir **tramos continuos**; un seek o una pausa reinician el conteo.
- **Negocio:** RN-02 y RN-04, el día y el mes se toman en UTC (ADR-0002); el corte offline necesita saber cuándo se escuchó (`device_ts`) y cuándo se sincronizó (`server_ts`).
- **Negocio:** RN-03, el evento debe identificar cuenta, dispositivo y track (artista vía F1), con los nombres que usa `Reproduccion` (ADR-0005).
- **Calidad:** los 5 defectos inyectados deben pasar el esquema (son defectos de negocio) y los errores de formato deben fallar antes de entrar al Data Lake.
- **Costo:** ninguno adicional; `jsonschema` ya es dependencia y no se agrega otra.
- **Equipo:** el esquema debe poder cambiar sin romper los consumidores de los sprints siguientes.

## 3. Opciones consideradas

### 3.1 Cómo reconocer un evento repetido (decisión principal)

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · **`event_id` UUID generado en el dispositivo**; se deduplica por esa llave en el consumidor y otra vez en Silver | El reintento lleva el mismo id por construcción; la llave es única y barata de indexar (`PRIMARY KEY` / `ON CONFLICT DO NOTHING`, `dropDuplicates(["event_id"])` en Spark); no depende del contenido | Si la app genera un id nuevo en cada reintento (bug), no se detecta; hay que guardar los ids vistos | 0 |
| B · Llave natural: hash de `user_id`, `device_id`, `session_id`, `event_type`, `device_ts`, `position_ms` | No necesita un campo nuevo; también atrapa reintentos con id regenerado | Dos eventos legítimos distintos pueden coincidir (doble toque en pausa en el mismo ms); la llave cambia cada vez que cambia el esquema; un hash por fila es más caro en Spark | 0 |
| C · Hash del evento completo | Trivial | **No funciona**: `server_ts` lo pone la API en cada recepción, así que el reintento tiene otro hash (ver `defectos/duplicado_por_reintento.json`) | 0 |
| D · Confiar en la cola (exactly-once) y no deduplicar | Sin código | RabbitMQ no garantiza exactly-once de extremo a extremo; el reintento de la app ni siquiera pasa por la misma entrega | 0 |

### 3.2 Formato de las fechas

| Opción | A favor | En contra |
|---|---|---|
| A · **`format: date-time` + patrón que exige `Z`** | Cumple ADR-0002 regla 1; el patrón funciona aunque no esté instalado `rfc3339-validator` | Rechaza fechas válidas con desfase (`-05:00`), que hay que convertir en la app |
| B · Solo `format: date-time` | Estándar | Acepta cualquier zona; y si falta `rfc3339-validator`, jsonschema **no valida nada** en silencio |

### 3.3 Evolución del esquema

| Opción | A favor | En contra |
|---|---|---|
| A · **`additionalProperties: false` + `schema_version` constante** | Un campo mal escrito (`event_typ`) o inesperado falla en la ingesta y no llega vacío a Silver; el consumidor sabe qué versión lee | Agregar un campo exige publicar `"1.1"` / `"2.0"` y que el consumidor acepte ambas durante la transición |
| B · Permitir campos extra | La app puede enviar campos nuevos sin coordinar | Los errores de nombre pasan silenciosos; el contrato deja de documentar la realidad |

## 4. Decisión

**Elegimos 3.1-A, 3.2-A y 3.3-A.**

1. **Deduplicación por `event_id`** (RNF-04). El dispositivo genera un UUID por evento y lo conserva en todos los reintentos. Se deduplica en dos puntos: el consumidor de la cola hace `INSERT … ON CONFLICT (event_id) DO NOTHING` (o equivalente) y Silver vuelve a deduplicar por `event_id` dentro de la partición del mes **y** del mes anterior, porque un evento offline puede llegar hasta el día 2 del mes siguiente (RN-04). Ante un repetido se conserva el de menor `server_ts`. La opción B queda como **control de calidad**: si aparecen eventos con distinto `event_id` y la misma llave natural, se reportan (posible bug de la app), pero no se borran.
2. **Fechas en UTC con `Z`**: `device_ts` (reloj del dispositivo, momento real) y `server_ts` (lo pone la API de ingesta) son obligatorios. El esquema describe el evento **ya ingerido**: el payload de la app no trae `server_ts` y la API lo agrega antes de publicarlo en la cola.
3. **Contrato cerrado y versionado**: `additionalProperties: false`, todos los campos obligatorios y `schema_version: "1.0"`. Se valida siempre con `FormatChecker`.

**Ajustes frente a los campos propuestos en la historia:**

- No hay campo de **duración**: los ms escuchados salen de `position_ms` y de los timestamps; la "duración negativa" se cubre con `position_ms ≥ 0`.
- No hay `event_type` **`seek`**: la app envía un seek como `pause` + `resume` con la nueva posición, lo que reinicia el tramo como pide EG-11 Q1 sin ampliar el enum.
- `device_id` es texto opaco (no UUID) porque no existe en ninguna fuente maestra; `track_id` exige el formato de F1 (22 caracteres base62) pero **no** su existencia, que se revisa contra el catálogo (defecto "track desconocido").
- No se incluye el **país de facturación**: está en F3 y se cruza por `user_id` (EG-11 Q6, ADR-0008). Repetirlo en cada evento permitiría que ambos valores no coincidieran.

## 5. Consecuencias

- **Positivas:**
  - Un reintento, de la app o de la cola, no duplica reproducciones ni ms (RNF-04).
  - Los 5 defectos inyectados pasan el esquema y se detectan donde corresponde: reconstrucción de sesiones, cruce con F1 y con F3 (`docs/datos/eventos-f2.md`).
  - Errores de formato (zona horaria, tipos, campos extra) se rechazan en la ingesta, antes de ensuciar el Data Lake.
- **Negativas / lo que aceptamos:**
  - Hay que guardar los `event_id` vistos: índice único en la tabla de ingesta y una deduplicación por partición en Spark.
  - Un `event_id` regenerado por error en la app pasa como evento distinto; solo lo detecta el control de calidad de la llave natural.
  - Agregar un campo obliga a publicar una versión nueva del esquema.
- **Riesgos y mitigación:**
  - *`rfc3339-validator` no está instalado en producción* (hoy llega solo con el grupo dev, vía `jupyter`) → el patrón con `Z` garantiza UTC y la prueba `test_format_checker_valida_de_verdad_uuid_y_date_time` falla si el checker deja de validar. Si se valida en producción con este módulo, se agrega `jsonschema[format-nongpl]` a las dependencias (decisión pendiente del equipo).
  - *Nombres distintos entre F2 y `Reproduccion`* (`user_id`/`cuenta_id`, `device_id`/`dispositivo_id`, artista como nombre y no id) → la correspondencia está documentada en `docs/datos/eventos-f2.md`; EG-17 (PR #12) puso `track_id` y `ms_continuos_max` en `ReproduccionValidez`; Silver (EG-35) une ambas clases en un solo registro.

## 6. Cómo sabremos que funciona

- **Pruebas (EG-15):** `tests/schemas/test_evento_f2.py` valida el esquema (`check_schema`), un ejemplo válido por `event_type`, 15 inválidos y los 5 defectos (pasan el esquema y el defecto está presente; el duplicado repite `event_id` y difiere solo en `server_ts`).
- **HU 20 (EG-29):** reiniciar el consumidor a mitad de carga y reenviar eventos no pierde ni duplica eventos: el conteo por `event_id` antes y después es igual.
- **Silver (EG-35):** número de `event_id` repetidos descartados por mes, publicado como métrica de calidad junto con los otros 4 defectos.

## 7. Fuentes

- JSON Schema draft 2020-12, `format` y `additionalProperties`: https://json-schema.org/draft/2020-12/json-schema-validation
- jsonschema (Python), validación de formatos y dependencias opcionales: https://python-jsonschema.readthedocs.io/en/stable/validate/#validating-formats
- RFC 3339, fechas en Internet: https://www.rfc-editor.org/rfc/rfc3339
- RFC 9562, UUID: https://www.rfc-editor.org/rfc/rfc9562
- RabbitMQ, confirmaciones y garantías de entrega: https://www.rabbitmq.com/docs/reliability
- [ADR-0002](0002-zona-horaria-dia-mes.md) (UTC) y [ADR-0005](0005-umbrales-granjas.md) (`Reproduccion` de RN-03).
- Supuestos de negocio: [ambiguedades-rn.md](../analisis/ambiguedades-rn.md) (Q1, Q4, Q6).


---

## English — Decision summary

**Accepted (October 7, 2026; EG-15).** Deduplicate F2 events by the device-generated `event_id`, preserving the earliest `server_ts`. Ingestion and Silver both enforce deduplication, including the previous month for late offline arrivals. `device_ts` and API-generated `server_ts` are required UTC timestamps ending in `Z`. The schema is closed (`additionalProperties: false`), all fields are mandatory, and `schema_version` is `1.0`. A seek is encoded as `pause` plus `resume`; listened duration is reconstructed from positions and timestamps.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
