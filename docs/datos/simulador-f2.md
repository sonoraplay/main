# Simulador F2 mínimo (EG-19)

Genera eventos de reproducción F2 para el esqueleto local (EG-24). La versión mínima es **determinista**: con la misma semilla escribe exactamente el mismo archivo, byte por byte. La EG-51 la extiende (ver [Simulador avanzado](#simulador-avanzado-eg-51)).

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

## Simulador avanzado (EG-51)

`python -m sonoraplay.simulador.f2_avanzado` extiende el mínimo a **un mes UTC y miles de cuentas**. Es una función pura (`generar`) más E/S (`ejecutar`), con el mismo patrón y las mismas fuentes que el mínimo (F3, F1 y F4).

- Código: [`src/sonoraplay/simulador/f2_avanzado.py`](../../src/sonoraplay/simulador/f2_avanzado.py) y [`src/sonoraplay/streaming/carga_pico.py`](../../src/sonoraplay/streaming/carga_pico.py).
- Parámetros: `SimuladorAvanzadoConfig` y `DefectosF2Config` en `config.py`.
- Pruebas: `tests/simulador/test_f2_avanzado.py` y `tests/streaming/test_carga_pico.py`.

### Perfiles de cuenta

Las cuentas se reparten **exactas** (no al azar): la cantidad de cada perfil se redondea una vez, así que la proporción no se aleja de la pedida.

| Perfil | Etiqueta | Qué hace | Señal de RN-03 que debe cumplir |
|---|---|---|---|
| `granja_horas_24h` | granja | 21 a 23 h de escucha seguida | Señal 1: más de 20 h en 24 h |
| `granja_concentracion_artista` | granja | 90 % de sus reproducciones a un artista que nadie más escucha | Señal 2: más del 70 % a un artista con menos de 1.000 oyentes |
| `granja_dispositivo_compartido` | granja | Grupos de 6 o más cuentas con el mismo `device_id` | Señal 3: más de 5 cuentas en un dispositivo |
| `intensivo` | legítima | 12 a 18 h en un día, con 10 artistas distintos | **Ninguna** (para medir falsos positivos) |
| `normal` | legítima | 6 a 12 sesiones en el mes, alternando entre 3 artistas suyos | Ninguna |

`--pct-granjas` (o la variable `FARM_PCT`, por defecto 5) se reparte entre los tres perfiles de granja. Los umbrales salen de `ReglasFraudeConfig`: si se recalibran, los perfiles se mueven con ellos y la configuración rechaza valores que dejarían de cumplir la señal.

### Offline y defectos

- **Offline** (`--pct-offline`, 10 %): toda la sesión se sincroniza junta, de **0 a 30 días** después de su último evento. `server_ts` queda siempre después de `device_ts` e `is_offline = true`.
- **Defectos** (`--defecto NOMBRE=PCT`, 2 % cada uno por defecto), en % de las sesiones de cuentas normales y a lo sumo uno por sesión: `evento_sin_fin`, `reloj_desfasado` (1 a 6 h, adelantado o atrasado), `track_desconocido` (formato válido, fuera de F1), `duplicado_por_reintento` (mismo `event_id`, otro `server_ts`) y `pais_facturacion_distinto` (solo cuentas con país en F3).
- Los intensivos y las granjas no llevan defectos ni offline: así la señal de fraude no se mezcla con la calidad de datos.

### Salidas

| Archivo | Contenido |
|---|---|
| `data/processed/eventos_f2_avanzado.jsonl` | Eventos F2 en orden de llegada (`server_ts`). Pasan el esquema y no llevan ninguna etiqueta |
| `data/processed/etiquetas_f2/cuentas.csv` | `cuenta_id, etiqueta (granja/legitima), perfil`: la verdad para el informe de fraude (EG-43) |
| `data/processed/etiquetas_f2/sesiones.csv` | `session_id, cuenta_id, perfil, is_offline, defecto` |

### Carga pico (CT-06)

```bash
uv run --env-file .env python -m sonoraplay.simulador.f2_avanzado --cuentas 10000 --pico --tasa 120 --duracion 60
```

Publica en la cola de la EG-29 con las mismas garantías (mensajes persistentes, *publisher confirms* y `mandatory`). Cuenta solo lo que el broker **confirmó**, y sale con código 1 si la media baja de **100 eventos/s** o la corrida dura menos de **60 s**. `--tasa` y `--duracion` cambian la prueba.

**Evidencia (22 oct 2026, PostgreSQL 16 y RabbitMQ locales):** 10.000 cuentas, 398.138 eventos, 5,0 % de granjas, 10,0 % offline y 2,0 % por defecto. Carga pico: **7.200 eventos confirmados en 60,0 s (120/s, mínimo y máximo por segundo = 120)**, 7.200 en la cola durable y 0 en la DLQ.

### Cómo se prueba cada criterio

Las pruebas miden sobre los **eventos**, no sobre las etiquetas: detectan cada defecto mirando solo el flujo (como lo haría calidad de datos) y exigen que coincida con la etiqueta.

| Criterio | Prueba |
|---|---|
| 1 · ≥ 100 eventos/s durante 60 s | `test_carga_pico_de_60_s_contra_rabbitmq_real` (con `PICO_60S=1`) y una corrida corta en cada CI |
| 2 · 5 % ± 1 pt de granjas en 10.000 cuentas | `test_diez_mil_cuentas_con_5_por_ciento_de_granjas`; cada granja cumple su señal de RN-03 con `evaluar_cuentas` |
| 3 · intensivos legítimos | `test_ningun_intensivo_es_marcado_por_rn03` |
| 4 · offline de 0 a 30 días | `test_sesiones_offline_llegan_de_0_a_30_dias_tarde` |
| 5 · 5 defectos ± 1 pt | `test_cada_defecto_en_2_por_ciento...` y la prueba con proporciones configurables |
| CA-10 · detección y falsos positivos | `test_ca10_...`: con el detector real (`evaluar_cuentas`) se detecta el 100 % de las granjas y menos del 2 % de las cuentas legítimas se marcan, con catálogos de 60 y 3.000 artistas. Medido con 300 artistas: 500/500 granjas y 1 falso positivo en 9.500 cuentas |
| 6 · semilla, esquema, etiquetas aparte | `test_misma_semilla...`, `test_todos_los_eventos_validan...`, `test_etiquetas_en_csv_aparte` |

### Límites

- El seed F3 `dev` (10.000 usuarios) no alcanza para 10.000 cuentas **activas** el 15 de septiembre (unas 7.900 lo están). Para la corrida completa: `python -m sonoraplay.seed --usuarios 15000`. Con pocas cuentas disponibles el simulador falla con un mensaje que lo explica.
- **Falsos positivos por diseño.** RN-03 señal 2 marca a quien manda más del 70 % de sus reproducciones a un artista con menos de 1.000 oyentes. Con 10.000 cuentas casi todo artista tiene menos de 1.000, así que una cuenta con una sola sesión se marcaría. Por eso las cuentas normales tienen al menos 2 sesiones (la configuración rechaza 1) y alternan entre 3 artistas. Con 1 a 6 sesiones sueltas, la primera versión marcaba el 17 % de las cuentas legítimas.
- Los tres perfiles de granja y los intensivos se generan con el catálogo de F1 que haya cargado; las granjas de artista necesitan al menos 3 artistas.
- La atribución de los eventos offline al mes la hace RN-04 (EG-22), no el simulador.


---

## English — Minimal F2 simulator (EG-19)

The minimal F2 simulator generates playback events for the local walking skeleton (EG-24). Given identical inputs and a fixed seed, its JSON Lines output is **byte-for-byte deterministic**. The advanced simulator (EG-51) extends it, see below.

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

The minimal simulator does **not** generate fraud farms, late offline events, injected defects, peak traffic, or RabbitMQ publishing; these are covered by the advanced simulator (EG-51) and RabbitMQ (EG-29). The minimal reconstruction does not perform the full Silver quality and quarantine process.

### Advanced simulator (EG-51)

`python -m sonoraplay.simulador.f2_avanzado` simulates a full UTC month for thousands of accounts using the same F3, F1 and F4 sources. It generates three farm profiles that each trigger one RN-03 signal (over 20 h in 24 h; over 70 % of plays to an artist with fewer than 1,000 listeners; devices shared by more than 5 accounts), plus legitimate heavy listeners (12–18 h, varied artists) that must stay below every threshold so false positives can be measured. Profile counts are assigned exactly, so `--pct-granjas` / `FARM_PCT` (default 5 %) is reproduced within rounding.

Offline sessions (`--pct-offline`, 10 %) sync 0–30 days after their last event. The five defects (`--defecto NAME=PCT`, 2 % each by default, applied to normal accounts only, at most one per session) are missing end, clock drift, unknown track, retry duplicate and billing/playback country mismatch. Events validate against the F2 schema and carry no labels; ground truth is written separately to `etiquetas_f2/cuentas.csv` and `sesiones.csv` for the fraud report (EG-43). The same seed produces identical events and labels.

Peak mode (`--pico --tasa 120 --duracion 60`) publishes to the EG-29 queue with persistent messages and publisher confirms, counts only broker-confirmed events, and exits non-zero below 100 events/s or 60 s. Evidence (2026-10-22, local PostgreSQL 16 and RabbitMQ): 10,000 accounts, 398,138 events, 5.0 % farms; **7,200 events confirmed in 60.0 s (120/s every second)**, 7,200 in the durable queue, 0 in the DLQ. Normal accounts have 6–12 sessions spread over 3 artists each, because RN-03 signal 2 would otherwise flag accounts with few plays (a first version flagged 17 % of legitimate accounts); with the real detector, 100 % of farms are caught and about 0.01 % of legitimate accounts are flagged (CA-10). Tests measure the event stream itself, not the labels. The `dev` F3 seed has only about 7,900 accounts active on 15 September, so the full 10,000-account run needs `python -m sonoraplay.seed --usuarios 15000`.
