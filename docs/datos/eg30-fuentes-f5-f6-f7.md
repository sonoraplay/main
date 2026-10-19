# EG-30 · Fuentes F5, F6 y F7 / F5, F6 and F7 sources

## Español

**Estado:** en curso, solo en `develop` (se sacó de `main` hasta completar la aceptación). La descarga, la validación, el CSV F5 y la **carga transaccional en PostgreSQL** están implementados y probados con APIs simuladas y una base PostgreSQL real. **Falta la verificación contra las APIs reales y la aprobación escrita del ADR-0021.**

### Qué hace

1. Descarga **F7** de REST Countries v3 (ISO-2, región y monedas; exige al menos 200 países).
2. Descarga **F6** de Frankfurter **v2** con USD como base para ARS, BRL, CLP, COP, MXN y PEN:
   - **serie diaria** (por defecto): solo los días con cotización publicada; no se inventan fines de semana ni festivos;
   - **tasa de cierre**: la última cotización publicada del mes, guardada con la fecha del último día del mes (RN-05, ADR-0002) y su `fecha_observacion` real.
3. Genera **F5**: CSV mensual determinista de ingresos publicitarios simulados (semilla fija, dos decimales, seis países, menos de 1.000 filas). La moneda de cada país se contrasta con F7.
4. **Valida todo antes de guardar nada.** Si falta una moneda, un país o la API falla, no se carga ni se escribe nada.
5. Con `--cargar`, guarda las tres fuentes en PostgreSQL **en una sola transacción** con UPSERT.
6. Escribe los archivos (`f5_publicidad_AAAA-MM.csv`, `f6_tasas_AAAA-MM-DD.json`, `f6_tasas_diarias_AAAA-MM.json`, `f7_paises.json`): primero todos los temporales y luego los reemplaza, para no dejar un conjunto mezclado.

### Tablas (`db/ddl/004_fuentes_f5_f6_f7.sql`)

| Tabla | Llave | Contenido |
|---|---|---|
| `paises` | `pais` | F7: región y monedas de cada país |
| `tasas_cambio` | `moneda`, `fecha`, `tipo` | F6: unidades por USD; `tipo` = `diaria` o `cierre` |
| `ingresos_publicidad` | `periodo`, `pais` | F5: ingresos del mes en moneda local y semilla usada |

La base rechaza tasas no positivas, cierres que no caen el último día del mes y filas de F5 de países que no están en F7.

### Criterios de aceptación

| # | Criterio | Estado |
|---|---|---|
| 1 | Tasas diarias a USD de las 6 monedas, incluido el último día del mes | ✅ Implementado y probado con datos simulados · ⏳ falta verificar con la API real |
| 2 | Cobertura de las 6 monedas y fuente alternativa documentada en un ADR | 🟡 La cobertura se comprueba y falla si falta una moneda · ⏳ ADR-0021 propuesto, falta fuente alternativa si alguna moneda no está |
| 3 | ~250 países con moneda y región | ✅ Implementado (mínimo 200) · ⏳ falta verificar con la API real |
| 4 | CSV F5 mensual, menos de 1.000 filas, semilla fija, monedas coherentes con F7 | ✅ |
| 5 | Repetir la carga no duplica filas | ✅ UPSERT por llave primaria; probado |
| 6 | Si la API falla: reintentos y sin datos a medias | ✅ 3 intentos para errores transitorios; una transacción; probado que un fallo a mitad deshace todo |

### Cómo ejecutarlo (requiere internet)

```bash
# Solo archivos
uv run python -m sonoraplay.fuentes.eg30 --mes 2026-09

# Archivos + carga en PostgreSQL (usa DATABASE_URL de .env)
uv run --env-file .env python -m sonoraplay.fuentes.eg30 --mes 2026-09 --cargar

# Pruebas (las de carga necesitan TEST_DATABASE_URL)
uv run --env-file .env python -m pytest tests/fuentes -v
```

Opciones: `--salida` (por defecto `data/generated/eg30`), `--semilla` (2026) y `--sin-diarias` (solo la tasa de cierre).

Si la base ya existía antes de este cambio, aplica el DDL a mano (es idempotente): `docker exec -i sonoraplay-postgres psql -U sonora -d sonoraplay < db/ddl/004_fuentes_f5_f6_f7.sql`.

### Pendientes

- **Verificación real:** ejecutar contra Frankfurter v2 y REST Countries y guardar la evidencia (conteos y salida). Comprobar en especial que Frankfurter publica ARS, CLP, COP y PEN con cotización **dentro de cada mes**: si alguna solo se publica de forma trimestral, la tasa de cierre de los meses intermedios fallará.
- **ADR-0021:** confirmación escrita de Joshua y, si alguna moneda no tiene cobertura, la fuente alternativa.

## English

**Status:** in progress, only in `develop` (removed from `main` until acceptance is complete). Download, validation, the F5 CSV and the **transactional PostgreSQL load** are implemented and tested with simulated APIs and a real PostgreSQL database. **Verification against the live APIs and written approval of ADR-0021 are still pending.**

### What it does

1. Downloads **F7** from REST Countries v3 (ISO-2, region and currencies; at least 200 countries).
2. Downloads **F6** from Frankfurter **v2**, USD base, for ARS, BRL, CLP, COP, MXN and PEN:
   - **daily series** (default): only days with a published rate; weekends and holidays are never invented;
   - **closing rate**: the last published rate of the month, stored with the last calendar day of the month (RN-05, ADR-0002) and its actual `fecha_observacion`.
3. Generates **F5**: a deterministic monthly CSV of simulated advertising revenue (fixed seed, two decimals, six countries, fewer than 1,000 rows). Each country's currency is checked against F7.
4. **Validates everything before saving anything.** If a currency or country is missing or an API fails, nothing is loaded or written.
5. With `--cargar`, stores the three sources in PostgreSQL **in a single transaction** using UPSERT.
6. Writes the output files: all temporary files first, then replaces them, so the set is never mixed.

### Tables (`db/ddl/004_fuentes_f5_f6_f7.sql`)

| Table | Key | Contents |
|---|---|---|
| `paises` | `pais` | F7: region and currencies per country |
| `tasas_cambio` | `moneda`, `fecha`, `tipo` | F6: units per USD; `tipo` = `diaria` or `cierre` |
| `ingresos_publicidad` | `periodo`, `pais` | F5: monthly revenue in local currency and the seed used |

The database rejects non-positive rates, closing rates not on the last day of the month, and F5 rows for countries missing from F7.

### Acceptance criteria

| # | Criterion | Status |
|---|---|---|
| 1 | Daily USD rates for the 6 currencies, including the last day of the month | ✅ Implemented and tested with simulated data · ⏳ live API check pending |
| 2 | Coverage of the 6 currencies and a fallback source documented in an ADR | 🟡 Coverage is checked and fails if a currency is missing · ⏳ ADR-0021 proposed; fallback source needed if a currency is not covered |
| 3 | ~250 countries with currency and region | ✅ Implemented (minimum 200) · ⏳ live API check pending |
| 4 | Monthly F5 CSV, fewer than 1,000 rows, fixed seed, currencies consistent with F7 | ✅ |
| 5 | Rerunning the load does not duplicate rows | ✅ UPSERT on primary keys; tested |
| 6 | On API failure: retries and no partial data | ✅ 3 attempts for transient errors; one transaction; tested that a mid-load failure rolls everything back |

### How to run (requires internet)

```bash
uv run python -m sonoraplay.fuentes.eg30 --mes 2026-09
uv run --env-file .env python -m sonoraplay.fuentes.eg30 --mes 2026-09 --cargar
uv run --env-file .env python -m pytest tests/fuentes -v
```

Options: `--salida` (default `data/generated/eg30`), `--semilla` (2026) and `--sin-diarias` (closing rate only).

### Outstanding

- **Live verification:** run against Frankfurter v2 and REST Countries and keep the evidence. Check in particular that Frankfurter publishes ARS, CLP, COP and PEN **within every month**: if a currency is only published quarterly, the closing rate of intermediate months will fail.
- **ADR-0021:** written confirmation from Joshua and, if a currency lacks coverage, the fallback source.
