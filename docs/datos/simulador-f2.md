# Simulador F2 mínimo (EG-19)

Genera eventos de reproducción F2 para el esqueleto local (EG-24). La versión mínima es **determinista**: con la misma semilla escribe exactamente el mismo archivo, byte por byte. La EG-51 (Sprint 3) la extiende.

- Código: [`src/sonoraplay/simulador/f2_minimo.py`](../../src/sonoraplay/simulador/f2_minimo.py) y [`src/sonoraplay/reglas/sesiones.py`](../../src/sonoraplay/reglas/sesiones.py).
- Parámetros: `SimuladorConfig` en [`src/sonoraplay/config.py`](../../src/sonoraplay/config.py).
- Contrato de los eventos: [`eventos-f2.md`](eventos-f2.md) y [ADR-0004](../adr/0004-esquema-eventos-f2.md).
- Pruebas: `tests/simulador/test_f2_minimo.py` y `tests/reglas/test_sesiones.py`.

## Qué genera

Un archivo **JSON Lines**: un evento por línea, en UTF-8, con `\n` como fin de línea (también en Windows) y las claves en el orden del `required` del esquema. Por defecto se escribe en `data/processed/eventos_f2.jsonl`, que Git ignora. Los eventos van ordenados por `device_ts`. RabbitMQ llega en la EG-29; mientras tanto, la EG-24 lee este archivo.

Cada evento:

- **Pasa el esquema** `schemas/f2_evento.schema.json` con `FormatChecker`. `ejecutar` valida todos los eventos antes de escribir y falla si alguno no cumple.
- **Cruza con las fuentes reales:**
  - `user_id` es un usuario de F3 activo en la fecha base;
  - `track_id` es una pista del catálogo F1 cuyo **titular** tiene una condición general (sin territorio) vigente en F4 para esa pista.
- **Cumple el contrato de la sesión:**
  - El primer evento es `start` con `position_ms = 0`, y el último es `end` o `skip`. No hay eventos después del cierre.
  - Mientras suena, `position_ms` avanza lo mismo que `device_ts`. Durante una pausa avanza el reloj y la posición se queda quieta.
  - `position_ms` nunca supera la duración de la pista. **`end` significa que la pista terminó** (`position_ms = duration_ms`); si la reproducción se corta antes, el cierre es `skip`.
- **Es online, en UTC:** `device_ts` y `server_ts` van con `Z` y milisegundos, `server_ts = device_ts + 100 a 500 ms` e `is_offline = false`.
- **País:** `country_playback` es el `pais_facturacion` del usuario. Si es NULL (defecto de F3), se sortea uno de `PAISES` y se mantiene para todas las sesiones de ese usuario.
- **Dispositivo:** `device_id` es `android-<8 hex>`, derivado del usuario: un dispositivo por usuario.
- **Sin solapes:** las sesiones de un mismo usuario no se solapan. Entre una sesión y la siguiente pasan de 30 s a 5 min.

### Determinismo

| Qué | Cómo |
|---|---|
| Azar | `random.Random(f"{semilla}:f2")`, nunca el `random` global |
| `session_id`, `event_id` | `uuid5` con el `NAMESPACE` de F3 (`det_uuid`) y el número de sesión y de evento |
| Fecha | `SimuladorConfig.fecha_base = 2026-09-15`, fija: nunca `now()`. Es septiembre, el mes que liquidaría la EG-24 |
| Fuentes | usuarios ordenados por `usuario_id` y pistas por `track_id` |
| Archivo | claves en orden fijo, JSON compacto, `newline="\n"` |

`generar(fuentes, cfg)` es una función pura (sin E/S ni reloj). `leer_fuentes` y `ejecutar` hacen la E/S, con el mismo patrón que el seed F4.

## Escenarios obligatorios

Los segundos entre paréntesis son `position_ms`. Se generan en todos los archivos, en la mañana de la fecha base (desde las 08:00 UTC), para que el esqueleto ejercite RN-01 y RN-02. Las duraciones salen de `ReglasValidezConfig`: si se recalibra un umbral, los escenarios se mueven con él.

| | Eventos | Tramo más largo | Resultado con `reconstruir` + `aplicar_tope_diario` |
|---|---|---|---|
| **A** | `start`(0) → `skip`(29 s) | 29 000 ms | No válida: `DURACION_INSUFICIENTE` (RN-01) |
| **B** | `start`(0) → `skip`(30 s) | 30 000 ms | Válida, en el límite (exactamente 30 s cuenta) |
| **C** | `start`(0) → `pause`(15 s) → `resume`(15 s, 10 s después) → `skip`(35 s) | 20 000 ms | No válida: la pausa reinicia el conteo y 15 s + 20 s no suman (EG-11 Q1) |
| **D** | 11 × `start` → `end`, mismo usuario y pista, pista de 1 a 10 min | ≥ 60 000 ms | 10 `PAGABLE` y **1 `TOPE_DIARIO`** (RN-02) |

- **D es exacto.** Su par (usuario, pista) se elige primero y ninguna otra sesión del archivo lo usa. Así el grupo tiene exactamente 11 reproducciones válidas y un solo `TOPE_DIARIO`.
- **Mínimo de eventos.** Los escenarios suman 2 + 2 + 4 + 2 × 11 = **30 eventos**. `SimuladorConfig(eventos=29)` lanza `ValueError` y la CLI muestra el error.
- **Relleno.** El resto se completa con sesiones aleatorias de 2 eventos (`start` → `end`/`skip`), 3 (`start` → `pause` → `skip`, cerrada en pausa) o 4 (`start` → `pause` → `resume` → `end`/`skip`), entre las 10:00 y las 22:00 UTC. El tamaño de cada sesión se elige para llegar **exactamente** a `--eventos` sin cortar ninguna sesión. Si sobra un solo evento (por ejemplo, `--eventos 31`), A se emite en 3 eventos (`start` → `pause`(29 s) → `skip`) y sigue sin ser válida.

## Cómo correrlo

Antes hay que tener cargados el catálogo F1, F3 y F4, en este orden:

```bash
docker compose up -d --wait
uv run python -m sonoraplay.catalogo                                  # F1 → data/processed/
uv run --env-file .env python -m sonoraplay.seed --modo dev           # F3
uv run --env-file .env python -m sonoraplay.seed.f4_contratos         # F4 sobre el mismo catálogo
uv run --env-file .env python -m sonoraplay.simulador --eventos 100 --semilla 42
```

| Opción | Por defecto | Qué hace |
|---|---|---|
| `--eventos N` | 100 | Eventos exactos del archivo (mínimo 30) |
| `--semilla N` | 42 | Misma semilla, mismo archivo |
| `--salida RUTA` | `data/processed/eventos_f2.jsonl` | Archivo JSON Lines |
| `--datos-f1 DIR` | `data/processed` | Carpeta con `catalogo_f1.parquet` |

- **Faltan fuentes.** Si no hay usuarios activos, catálogo o contratos, el simulador dice qué comando correr.
- **Usa F4 sobre el mismo catálogo.** F4 tiene que estar cargado sobre **el mismo** `catalogo_f1.parquet` que se le pasa al simulador. Si F4 se cargó con otro catálogo (por ejemplo, la muestra), solo entran las pistas cuyo par (pista, titular) coincide.

## De eventos a reproducciones (`reglas/sesiones.py`)

`reconstruir(eventos) -> list[ReproduccionValidez]` es una función pura. Implementa los pasos de [eventos-f2.md, "De eventos a reproducciones"](eventos-f2.md#de-eventos-a-reproducciones) que necesitan RN-01 y RN-02. La EG-24 la reutiliza.

1. **Deduplica** por `event_id` y conserva el de menor `server_ts` (ADR-0004).
2. **Agrupa** por `session_id` y **ordena** por `device_ts`; a igual `device_ts`, por `server_ts`.
3. **Arma los tramos:** un tramo abre con `start` o `resume` y cierra con el siguiente `pause`, `skip` o `end`.
   - Cada tramo cuenta `min(Δposition_ms, Δdevice_ts)` y nunca menos de 0.
   - Un tramo sin cierre cuenta 0.
   - Los eventos fuera de orden y los que llegan después del cierre se ignoran.
4. **Emite** una reproducción por sesión con `start`:
   - `reproduccion_id` = `session_id`;
   - `cuenta_id` = `user_id`;
   - `inicio` = `device_ts` del `start`;
   - `ms_continuos_max` = el tramo más largo.

   Una sesión sin `start` no produce reproducción.

**No incluye** la corrección de relojes desfasados (EG-22), la resolución de artista ni la cuarentena (EG-18, EG-35), ni las marcas de calidad (`sin_fin`, tramo inconsistente). Silver (EG-35) arma el registro completo.

## Qué queda para la EG-51 (Sprint 3)

Esta versión solo genera tráfico **limpio y online** de un día. La EG-51 agrega:

- granjas de reproducción y oyentes intensivos (señales de RN-03);
- eventos offline sincronizados después (RN-04);
- los 5 defectos de `eventos-f2.md`: evento sin fin, reloj desfasado, track desconocido, duplicado por reintento y país de facturación distinto;
- carga pico y publicación en RabbitMQ (con la EG-29).


---

## English — Minimal F2 simulator (EG-19)

The minimal F2 simulator generates playback events for the local walking skeleton (EG-24). Given identical inputs and a fixed seed, its JSON Lines output is **byte-for-byte deterministic**. EG-51 (Sprint 3) is responsible for extending it.

**Source:** `src/sonoraplay/simulador/f2_minimo.py`, `src/sonoraplay/reglas/sesiones.py`. **Configuration:** `SimuladorConfig`. **Tests:** `tests/simulador/test_f2_minimo.py` and `tests/reglas/test_sesiones.py`.

### Output and validity

The default output is `data/processed/eventos_f2.jsonl`: UTF-8 JSON Lines, one event per line, LF line endings, and schema-required key order. Events are ordered by `device_ts`. Each event passes `schemas/f2_evento.schema.json` with `FormatChecker` before the file is written. Users come from active F3 subscriptions; tracks come from F1 and must have a valid general F4 contract. A session starts with `start` at position zero and ends with `end` (at track duration) or `skip` (early stop); no events follow termination. Timestamps use UTC `Z` with milliseconds; server time is 100–500 ms after device time, and all generated sessions are online. Playback country follows F3 billing country, with a stable generated fallback for null values. Each user has one derived Android device and non-overlapping sessions separated by 30 seconds to five minutes.

### Determinism

Random values come from `random.Random(f"{semilla}:f2")`, IDs from deterministic UUID5, and the fixed base date is `2026-09-15`. Input users and tracks are sorted; output uses fixed key order and compact JSON. `generar(fuentes, cfg)` is pure; `leer_fuentes` and `ejecutar` handle I/O.

### Required scenarios

| Scenario | Playback events | Expected outcome |
|---|---|---|
| A | `start(0) → skip(29 s)` | Invalid: `DURACION_INSUFICIENTE` |
| B | `start(0) → skip(30 s)` | Valid at the 30-second boundary |
| C | `start(0) → pause(15 s) → resume(15 s) → skip(35 s)` | Invalid: longest continuous segment is 20 seconds; separate segments cannot be added |
| D | 11 `start → end` sessions for the same user and track | 10 `PAGABLE`, 1 `TOPE_DIARIO` |

The required scenarios total **30 events**. A request for 29 events fails. Remaining events are generated in complete sessions of two, three, or four events, reaching the requested total without truncating a session. If exactly one extra event is needed, scenario A uses a three-event variant.

### Run locally

First load F1, F3, and F4 using the commands in the Spanish section above; F4 must refer to the **same F1 catalog** passed to the simulator. Then run:

```bash
uv run --env-file .env python -m sonoraplay.simulador --eventos 100 --semilla 42
```

Options: `--eventos` defaults to 100 (minimum 30), `--semilla` defaults to 42, `--salida` defaults to `data/processed/eventos_f2.jsonl`, and `--datos-f1` defaults to `data/processed`. Missing users, catalog, or contracts produce actionable errors.

### Event reconstruction and limitations

`reconstruir(eventos)` deduplicates by `event_id` (earliest `server_ts` wins), groups by `session_id`, orders by device time (then server time), and measures continuous segments opened by `start`/`resume` and closed by `pause`/`skip`/`end`. Each segment contributes at most the lesser of position delta and elapsed time; incomplete segments contribute zero. A session without `start` produces no playback. Its output includes session ID, account ID, start time, and maximum continuous listening duration.

The minimal simulator does **not** generate fraud farms, late offline events, injected defects, peak traffic, or RabbitMQ publishing; these are EG-51/EG-29 follow-ups. The minimal reconstruction does not perform the full Silver quality and quarantine process.
