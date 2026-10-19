# Eventos F2 · Reproducciones (HU 06 · EG-15)

Fuente F2 de SonoraPlay: los eventos que envía la app cada vez que una reproducción empieza, se pausa, se reanuda, se salta o termina. Con ellos se reconstruyen las reproducciones que evalúan RN-01/RN-02 (EG-17), RN-03 (EG-18) y RN-04 (EG-22).

- Esquema: [`schemas/f2_evento.schema.json`](../../schemas/f2_evento.schema.json) (JSON Schema draft 2020-12).
- Decisiones (deduplicación por `event_id`, UTC con `Z`, versionado): [ADR-0004](../adr/0004-esquema-eventos-f2.md).
- Ejemplos: `schemas/ejemplos/validos/` (uno por `event_type`), `invalidos/` y `defectos/`.
- Pruebas: `tests/schemas/test_evento_f2.py`.

## Cómo validar

```python
import json
from jsonschema import Draft202012Validator, FormatChecker

esquema = json.load(open("schemas/f2_evento.schema.json", encoding="utf-8"))
validador = Draft202012Validator(esquema, format_checker=FormatChecker())
validador.validate(evento)  # lanza ValidationError si el formato es incorrecto
```

Sin `format_checker`, jsonschema **no** revisa `uuid` ni `date-time`. Además, `date-time` solo se revisa si está instalado `rfc3339-validator`; hoy llega con el grupo dev, así que en producción el patrón con `Z` es la garantía mínima de UTC y la prueba `test_format_checker_valida_de_verdad_uuid_y_date_time` avisa si el checker deja de funcionar (ADR-0004).

## Campos

Todos son **obligatorios** y no se admiten campos extra (`additionalProperties: false`). El esquema describe el evento **tal como queda en la cola**, después de que la API de ingesta le añade `server_ts`.

| Campo | Tipo y restricción | Ejemplo | Para qué / regla que lo usa |
|---|---|---|---|
| `schema_version` | string, `const "1.0"` | `"1.0"` | Versionado del contrato. Un cambio incompatible crea `"2.0"` (ADR-0004). |
| `event_id` | string, `format: uuid` | `"c7e1d0a4-0001-4f2b-9a6e-5b3c2d1e0f01"` | Lo genera el dispositivo; un reintento reenvía el mismo. Llave de **deduplicación** (RNF-04, ADR-0004). |
| `event_type` | enum `start`, `pause`, `resume`, `skip`, `end` | `"pause"` | Abre y cierra los tramos continuos de RN-01. |
| `user_id` | string, `format: uuid` | `"3b6f1a2c-5d4e-4f7a-9b8c-1d2e3f4a5b6c"` | Cuenta que escucha = `usuario_id` de F3. RN-02 (tope por usuario y día), RN-03 (señales por cuenta), RN-10 (cuenta familiar, país de facturación). |
| `device_id` | string de 1 a 64, `^[A-Za-z0-9_-]+$` | `"android-7f3a9c21"` | RN-03 señal 3 (dispositivo con más de 5 cuentas). Es opaco: no está en F3. |
| `track_id` | string, `^[0-9A-Za-z]{22}$` | `"23Mcmg5O8rBKAOzxvrTjnD"` | Pista del catálogo F1 → artista y titular. RN-01/RN-02 (por pista), RN-03 señal 2 (artista). Que exista en F1 se revisa en calidad de datos. |
| `session_id` | string, `format: uuid` | `"a1b2c3d4-e5f6-4a7b-8c9d-0e1f2a3b4c5d"` | Agrupa los eventos de **una** reproducción de **un** track (de su `start` a su `end` o `skip`). |
| `device_ts` | string `date-time` en UTC con `Z` | `"2026-09-15T14:00:45.000Z"` | Momento real del evento según el dispositivo. Define el día (RN-02) y el mes (RN-04, RN-05, RN-07) en UTC (ADR-0002). |
| `server_ts` | string `date-time` en UTC con `Z` | `"2026-09-15T14:00:45.210Z"` | Cuándo lo recibió la API de ingesta. Corte offline de RN-04 (día 2, 23:59 UTC) y detección de relojes desfasados. |
| `position_ms` | entero ≥ 0 | `45000` | Posición dentro del track en el momento del evento. La diferencia entre eventos da los ms escuchados (RN-01, RN-03 señal 1). |
| `country_playback` | string, `^[A-Z]{2}$` (ISO 3166-1 alfa-2) | `"CO"` | País donde se reproduce: exclusiones territoriales (RN-08) y analítica. **No** define la bolsa: esa la define el país de facturación de F3 (EG-11 Q6, ADR-0008). |
| `is_offline` | boolean | `false` | `true` si se escuchó sin conexión y se sincronizó después (RN-04). |

**Restricciones que van más allá del formato JSON:**

- `device_ts` y `server_ts` **deben** terminar en `Z`. Un desfase como `-05:00` es una fecha válida en RFC 3339, pero el patrón lo rechaza (ADR-0002, regla 1).
- `country_playback` solo valida el formato (dos letras mayúsculas), no que el código exista; la lista de países se revisa en calidad de datos.
- No hay campo de duración ni de artista: la duración sale de `position_ms` y el artista del catálogo F1.

### Contrato de la app para RN-01

Un **seek** (saltar a otra parte del track) no tiene `event_type` propio: la app lo envía como `pause` en la posición de origen seguido de `resume` en la posición de destino. Así un seek antes de los 30 s abre un tramo nuevo, como pide EG-11 Q1.

## Ejemplos

| Carpeta | Contenido | Qué se prueba |
|---|---|---|
| `validos/` | `start`, `pause`, `resume`, `end` de una misma sesión online, y un `skip` offline sincronizado el 2-oct (RN-04) | Pasan el esquema; hay uno por `event_type` |
| `invalidos/` | El `start` válido con una sola mutación: sin `event_id`, sin `server_ts`, `event_type` desconocido (`seek`), `position_ms` negativa o decimal, `event_id` que no es UUID, `device_ts` sin zona o con desfase `-05:00`, fecha imposible (30-feb), país en minúsculas o de 3 letras, `track_id` vacío, `is_offline` como texto, `schema_version` desconocida, campo extra | Fallan el esquema |
| `defectos/` | Un archivo por defecto de negocio (ver abajo), con `defecto`, `descripcion`, `contexto` y `eventos` | Cada evento **pasa** el esquema y el defecto está presente |

## Defectos inyectados

Son defectos de **negocio**, no de formato: todos sus eventos pasan el esquema y se detectan al reconstruir las reproducciones o al cruzar con F1 y F3.

| Defecto | Archivo | Cómo se ve en los eventos | Cómo se detecta y trata |
|---|---|---|---|
| Evento sin fin | `evento_sin_fin.json` | `start` → `pause` → `resume` y nunca llega `end` ni `skip` | Al cerrar la sesión el último tramo queda abierto: cuenta **0 ms** (no se puede saber cuánto duró) y la reproducción se marca `sin_fin`. Los tramos cerrados sí cuentan. |
| Reloj del dispositivo desfasado | `reloj_desfasado.json` | Evento online (`is_offline=false`) con `device_ts` 3 h antes que `server_ts` | En un evento online `server_ts − device_ts` debería ser de milisegundos. Si la mediana de la sesión supera la tolerancia (60 s) se suma ese desfase a todos sus `device_ts` (paso 3, EG-22; ADR-0002 regla 2): el `start` queda a las 14:00:00.250Z y el tramo sigue midiendo 210 760 ms. |
| Track desconocido | `track_desconocido.json` | `track_id` con formato correcto que no está en F1 | El cruce con el catálogo no encuentra artista ni titular: la reproducción va a cuarentena y no entra en la bolsa ni en RN-03 señal 2. |
| Duplicado por reintento | `duplicado_por_reintento.json` | Dos eventos con el **mismo `event_id`** y el mismo contenido; solo cambia `server_ts` | Se deduplica por `event_id` y se conserva el de menor `server_ts` (ADR-0004). Comparar el evento completo **no** sirve, porque `server_ts` difiere. |
| País de facturación ≠ país de reproducción | `pais_facturacion_distinto.json` | `country_playback = "MX"` para una cuenta que factura en `"CO"` en F3 | Se ve al cruzar `user_id` con F3. No es un error: la reproducción cuenta en la bolsa del país de facturación (EG-11 Q6, ADR-0008) y `country_playback` solo se usa para RN-08 y analítica. |

## De eventos a reproducciones

Este es el contrato que usan EG-17 (RN-01, RN-02) y EG-18 (RN-03). Una **sesión** (`session_id`) produce como máximo **una reproducción**.

Los pasos 1 a 4 y 6 (sin artista) están implementados en `src/sonoraplay/reglas/sesiones.py` (`reconstruir`, EG-19; el paso 3 con la corrección del reloj de la EG-22); ver [simulador-f2.md](simulador-f2.md#de-eventos-a-reproducciones-reglassesionespy). La atribución al mes (RN-04) está en [atribucion-offline.md](atribucion-offline.md).

### Pasos

1. **Deduplicar** por `event_id`; si se repite, se conserva el de menor `server_ts` (ADR-0004).
2. **Agrupar** por `session_id`. Todos sus eventos deben tener el mismo `user_id`, `device_id` y `track_id`; si no, la sesión va a cuarentena.
3. **Corregir el reloj por sesión** (defecto 2, EG-22, `corregir_reloj_sesion`) y **ordenar** por `device_ts` corregido; a igual `device_ts`, por `server_ts`.
   - Desfase de la sesión = mediana de `server_ts − device_ts` de sus eventos online.
   - Si supera la tolerancia (`AtribucionOfflineConfig.tolerancia_reloj_segundos`, 60 s), se suma ese **mismo** desfase al `device_ts` de **todos** los eventos de la sesión: los tramos conservan su duración.
   - Una sesión con algún evento offline **no** se corrige: su `server_ts` es la sincronización tardía, no la hora de la escucha.
4. **Armar tramos continuos.** Un tramo **abre** con `start` o `resume` y **cierra** con el siguiente `pause`, `skip` o `end`.
   - ms del tramo = `position_ms` al cerrar − `position_ms` al abrir.
   - Si sale negativo, o si avanza más que el tiempo transcurrido entre los dos `device_ts` (más una tolerancia), el tramo es inconsistente: cuenta `min(Δposition_ms, Δdevice_ts)` y se marca para calidad.
   - Un tramo sin cierre (defecto 1) cuenta 0 ms.
   - Eventos fuera de orden (p. ej. `pause` sin tramo abierto) se ignoran y se marcan.
5. **Resolver el artista** con el catálogo F1: `track_id` → `artista_principal`. Sin coincidencia → cuarentena (defecto 3).
6. **Emitir la reproducción** con los campos de la tabla siguiente.

### Correspondencia con `Reproduccion` (`reglas/fraude.py`, RN-03) y `ReproduccionValidez` (`reglas/validez.py`, RN-01/RN-02)

Hoy son dos clases (más `ReproduccionF2`, que extiende `ReproduccionValidez` con lo de RN-04); Silver (EG-35) arma un solo registro con todos estos campos.

| Reproducción | Sale de | ¿Dónde existe hoy? |
|---|---|---|
| `reproduccion_id` | `session_id` (una sesión es una reproducción) | En `ReproduccionValidez` (EG-17); desempata el orden del tope diario. |
| `cuenta_id` | `user_id` | Sí, **con otro nombre** (F2 usa `user_id`, F3 usa `usuario_id`) |
| `dispositivo_id` | `device_id` | Sí, **con otro nombre** |
| `artista_id` | `track_id` → `artista_principal` del catálogo F1 | Sí, pero **F1 no tiene un id de artista**: hoy es el nombre del artista principal (texto). Dos artistas homónimos se juntarían. |
| `inicio` | `device_ts` corregido del `start`, en UTC | Sí (aware y normalizado a UTC) |
| `ms_escuchados` | **suma** de los ms de todos los tramos | Sí. RN-03 señal 1 lo usa como horas escuchadas. |
| `track_id` | `track_id` | En `ReproduccionValidez` (EG-17); lo usa RN-02 (10 por pista, usuario y día). |
| `ms_continuos_max` | el **mayor** tramo continuo | En `ReproduccionValidez` (EG-17); lo usa RN-01: válida si ≥ 30 000 ms (EG-11 Q1). |
| `is_offline`, `sincronizado` (`server_ts` del último evento) | `is_offline` (alguno de la sesión), `server_ts` | En `ReproduccionF2` (`reglas/sesiones.py`, EG-22), subclase de `ReproduccionValidez`. Entradas de `atribuir_reproduccion` (RN-04). |
| `pais_reproduccion` | `country_playback` | **No.** RN-08. |

**Ojo con `Reproduccion.fin`:** se calcula como `inicio + ms_escuchados`, es decir, como si los tramos fueran seguidos. Con pausas largas el fin real es más tarde. Para RN-03 señal 1 la diferencia es menor (cuenta lo escuchado, no lo transcurrido), pero si EG-18 necesita precisión se deberían pasar los tramos en vez de una sola reproducción.

### Ejemplo

La sesión de `schemas/ejemplos/validos/` (`start`, `pause`, `resume`, `end`):

| Evento | `device_ts` | `position_ms` | Tramo |
|---|---|---|---|
| `start` | 14:00:00.000Z | 0 | abre tramo 1 |
| `pause` | 14:00:45.000Z | 45 000 | cierra tramo 1 = **45 000 ms** |
| `resume` | 14:01:30.000Z | 45 000 | abre tramo 2 |
| `end` | 14:04:15.760Z | 210 760 | cierra tramo 2 = **165 760 ms** |

Resultado: `cuenta_id = 3b6f1a2c-…`, `dispositivo_id = android-7f3a9c21`, `track_id = 23Mcmg5O8rBKAOzxvrTjnD`, `artista_id = "Kitri"`, `inicio = 2026-09-15T14:00:00Z`, `ms_escuchados = 210 760`, `ms_continuos_max = 165 760` → válida para RN-01.

En `evento_sin_fin.json` el tramo 1 cierra con 40 000 ms y el tramo 2 queda abierto (0 ms): `ms_escuchados = 40 000`, `ms_continuos_max = 40 000` → válida para RN-01 aunque nunca llegó el `end`, y marcada `sin_fin`.


---

## English — F2 playback event contract (HU 06 · EG-15)

F2 contains app-generated playback events used to reconstruct listening sessions for RN-01/RN-02 (validity and daily cap), RN-03 (fraud detection), and RN-04 (offline attribution). The normative schema is `schemas/f2_evento.schema.json` (JSON Schema 2020-12), with examples under `schemas/ejemplos/` and tests in `tests/schemas/test_evento_f2.py`. ADR-0004 governs deduplication, UTC, and schema versioning.

### Validation and fields

All fields are mandatory; additional properties are rejected. Validate using `Draft202012Validator(schema, format_checker=FormatChecker())`. Without a format checker, UUID and RFC 3339 date-time formats may not be enforced. Timestamps must end in `Z` (UTC).

| Field | Contract and purpose |
|---|---|
| `schema_version` | Exact value `1.0`; incompatible changes require a new version |
| `event_id` | UUID generated by the device; retries reuse the same ID, which is the deduplication key |
| `event_type` | One of `start`, `pause`, `resume`, `skip`, `end` |
| `user_id` | UUID of the F3 listening account |
| `device_id` | 1–64 alphanumeric, underscore or hyphen characters; opaque device identifier |
| `track_id` | Exactly 22 alphanumeric characters; must be reconciled against F1 |
| `session_id` | UUID identifying one playback of one track |
| `device_ts` | Device event time in UTC with `Z`; determines the listening day and month |
| `server_ts` | API receipt time in UTC with `Z`; supports offline cutoff and clock-drift detection |
| `position_ms` | Nonnegative integer position within the track |
| `country_playback` | Uppercase two-letter country code; territory checks and analytics, **not** revenue-pool country |
| `is_offline` | Boolean indicating offline listening synchronized later |

A seek is represented as `pause` at the old position followed by `resume` at the new one, not as a new event type. The schema validates country-code **format**, not actual country membership.

### Reconstruction and quality rules

1. Deduplicate by `event_id`, retaining the earliest `server_ts` (ADR-0004).
2. Group by `session_id` and require consistent user, device, and track; inconsistent sessions require quarantine.
3. Correct online session clock drift using the median server/device offset, then sort by corrected device time and server time. Offline sessions are not shifted based on late receipt timestamps (EG-22).
4. Continuous segments open on `start`/`resume` and close on `pause`/`skip`/`end`. Negative or impossible position changes are capped against elapsed time and flagged; unclosed segments count zero.
5. Resolve `track_id` to the principal artist in F1; unknown tracks are quarantined.
6. Emit at most one playback per session, including `reproduccion_id`, `cuenta_id`, `inicio`, total listened milliseconds, maximum continuous milliseconds, track, device, and offline synchronization metadata. Some attributes are assembled later in Silver (EG-35).

**RN-01:** at least 30,000 continuous milliseconds are required; separate listening segments cannot be added to meet the threshold. **RN-02:** at most ten payable plays per account, track, and UTC day. **RN-08:** playback country is used for territorial exclusion; the revenue pool is determined by F3 billing country (ADR-0008).

### Defects and known limitations

Test examples include a missing end event, clock drift, unknown track, a retry duplicate with different `server_ts`, and a billing-country/playback-country mismatch (the latter is not itself an error). The current principal artist is text rather than a stable artist ID, so namesakes could be combined. `Reproduccion.fin` may reflect accumulated listening time rather than wall-clock time across pauses. The full Silver quality/quarantine record is a downstream responsibility, not an F2 schema guarantee.
