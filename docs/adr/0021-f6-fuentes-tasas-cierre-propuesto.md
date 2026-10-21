# ADR-0021 · Propuesta de fuentes y fecha de cierre para F6 / Proposed F6 sources and closing-date policy

| Campo / Field | Valor / Value |
|---|---|
| Estado / Status | **Aceptado / Accepted** — 2026-10-21 (Julián) |
| Fecha / Date | 2026-10-15 |
| Historia / Story | EG-30 (F5, F6, F7) |
| Responsable / Owner | María Clara (propuesta para revisión del TL) |
| Revisor / Reviewer | Julián — aprobó el 2026-10-21 / approved on 2026-10-21 |
| Referencias / References | ADR-0002; `TasaCambio`, `convertir_a_usd` en `reglas/liquidacion.py`; F3 |

## Español

### 1. Contexto
F3 usa CO, MX, BR, AR, CL y PE. F6 debe proporcionar ARS, BRL, CLP, COP, MXN y PEN como **unidades de moneda local por 1 USD**. La integración original usaba Frankfurter **v1** con datos del BCE; según la revisión del TL, no cubre ARS, CLP, COP ni PEN. F6 no puede completarse con esa respuesta. La liquidación exige `TasaCambio.fecha` igual al último día calendario del mes (ADR-0002). Algunos proveedores devuelven una observación del último día hábil, distinta del cierre calendario.

### 2. Criterios
- Cobertura verificable de las seis monedas, sin inventar tasas ni reemplazarlas silenciosamente.
- USD como base y valores positivos convertidos desde texto a `Decimal`.
- Trazabilidad: proveedor, fecha de observación real, fecha de cierre, momento de extracción.
- Compatibilidad con `TasaCambio(moneda, fecha, unidades_por_usd)` y el cierre mensual UTC.
- Preferir costo nulo y uso académico permitido; no incluir credenciales en Git.

### 3. Opciones
| Opción | Ventajas | Riesgos y requisitos | Costo anunciado |
|---|---|---|---|
| A. Frankfurter v2, tasas combinadas | 223 divisas, 104 fuentes oficiales, histórico, sin API key; reutiliza proveedor | La v2 tiene esquema distinto a v1; confirmar las seis monedas y fechas mediante respuestas reales; tasas combinadas son mid-market, no necesariamente TRM oficial de cada país | Gratis |
| B. Open Exchange Rates | Lista ARS/BRL/CLP/COP/MXN/PEN, base USD, histórico diario | Requiere registro y clave; contrastar cobertura histórica, licencia y semántica de las tasas | Plan gratis: 1.000 solicitudes/mes |
| C. Bancos centrales por país | Datos oficiales por jurisdicción | Seis adaptadores y calendarios distintos; algunos exigen tokens; integración más costosa | Variable / normalmente gratuito |
| D. Mantener Frankfurter v1/BCE | Sin cambios de implementación | No cubre monedas obligatorias; bloqueante | Gratis |

### 4. Recomendación **pendiente de aprobación**
**Evaluar primero A (Frankfurter v2)** y usar B como alternativa si la prueba de cobertura, fecha o licencia falla. **La implementación de v2 ya existe en la rama borrador EG-30 para evaluación técnica; su uso y la regla de cierre NO están aprobados.** La documentación oficial de v2 describe fuentes múltiples, filtro por `quotes`, fechas históricas y atribución mediante `expand=providers`. Deben verificarse datos reales para un cierre hábil y otro en fin de semana, y la presencia de PEN.

**Política de cierre propuesta (requiere decisión del TL):** seleccionar la última observación válida **no posterior** al último día calendario del mes; conservar `fecha_observacion` original y `fecha_cierre` calendario por separado; asignar `TasaCambio.fecha = fecha_cierre` solo si el equipo aprueba explícitamente esta regla. Rechazar observaciones futuras, monedas faltantes, valores no positivos y ausencia de datos del mes. No sustituir fechas sin trazabilidad.

**Formato propuesto:** una fila por moneda con `moneda`, `fecha` (cierre), `unidades_por_usd` (decimal como texto), `fecha_observacion`, `proveedor` y `extraido_en_utc`. Los tres primeros campos corresponden al contrato de liquidación; los demás son metadatos auditables. Decidir con EG-24/EG-37 el esquema final de persistencia.

### 5. Consecuencias y validación
- F5 ya incluye Argentina y comparte la configuración de seis países con F6; la implementación sigue sujeta a revisión del TL.
- Pruebas offline de seis monedas, precisión decimal, fecha real vs. cierre, error de cobertura y prohibición de escritura parcial.
- Pruebas de integración reales: un cierre de día hábil y mayo de 2026 (31 domingo), y evidencia de proveedor/fecha para cada moneda.
- Antes de aceptar: aprobación del TL sobre fuente, semántica mid-market/oficial, licencia, calendario y campos de auditoría.

## English

### 1. Context
F3 covers CO, MX, BR, AR, CL and PE. F6 requires ARS, BRL, CLP, COP, MXN and PEN, expressed as **local currency units per USD**. The original Frankfurter **v1** ECB-backed endpoint lacks several required currencies, according to the TL review. Royalty conversion requires `TasaCambio.fecha` to equal the calendar month-end (ADR-0002), while some source observations use the last business day.

### 2. Decision criteria
Verified coverage of all six currencies; no invented or silent fallback values; USD base; positive rates parsed to `Decimal` from text; provenance and actual observation date; UTC month-end compatibility; low cost and appropriate licensing.

### 3. Alternatives
- **A — Frankfurter v2 combined rates:** 223 currencies, 104 official providers, historical data, no key and free access. Must verify live coverage (especially PEN), date semantics, provider provenance and mid-market suitability.
- **B — Open Exchange Rates:** supports the six listed currencies, USD base and daily history; requires a key and account. Free tier advertises 1,000 requests/month.
- **C — Country-specific central banks:** authoritative per jurisdiction but requires multiple adapters, calendars and potentially credentials.
- **D — Frankfurter v1 ECB:** cannot cover the required currencies; rejected as the sole source.

### 4. Proposed recommendation — NOT YET ACCEPTED
**Validate option A first**, keeping B as fallback if live coverage, date or license checks fail. **The v2 implementation exists in the EG-30 draft branch for technical evaluation; its use and the month-end policy are NOT approved.** Proposed policy: use the latest valid observation on or before calendar month-end, preserve both `observation_date` and `closing_date`, and populate `TasaCambio.fecha` with the closing date only if explicitly approved. Reject future dates, missing currencies, non-positive values and absent monthly observations.

Proposed normalized output: `moneda`, `fecha`, `unidades_por_usd` (decimal string), `fecha_observacion`, `proveedor`, `extraido_en_utc`. Agree on persistence with EG-24/EG-37.

### 5. Acceptance checks
Offline tests for six currencies, decimal precision, observation-vs-closing dates and failure without partial outputs; live checks for a business-day close and May 2026 (Sunday month-end); TL approval of provenance, license and date policy.

## Fuentes / Sources
- Frankfurter v2 documentation: https://frankfurter.dev/
- Frankfurter providers: https://frankfurter.dev/providers/
- Open Exchange Rates supported currencies: https://docs.openexchangerates.org/reference/supported-currencies
- Open Exchange Rates historical API: https://docs.openexchangerates.org/reference/historical-json
- Open Exchange Rates free plan: https://openexchangerates.org/signup/free
- Central Bank of Chile API: https://si3.bcentral.cl/estadisticas/Principal1/Web_Services/index_API_sec1_es.htm


## Estado de implementación y evidencia / Implementation status and evidence (2026-10-15)

### Español
- **Implementado en la rama borrador EG-30:** módulos separados F5/F6/F7; seis países y monedas; normalización de F6 con fecha de cierre y fecha de observación; validación de cobertura; pruebas offline de reintentos HTTP, escritura por archivo y ejecución simulada.
- **CI verificado:** commit `b88ee009`; trabajos `lint`, `test`, `secretos` y compilación Docusaurus aprobados. Esta evidencia demuestra pruebas automatizadas con respuestas simuladas, **no** disponibilidad real del proveedor.
- **No verificado:** consulta HTTP real de Frankfurter v2 para las seis monedas, especialmente PEN; comportamiento real de fin de semana; licencia/atribución específica de las tasas seleccionadas; integración UPSERT con PostgreSQL.
- **Diferencias respecto a la propuesta:** el JSON actual contiene `moneda`, `fecha`, `unidades_por_usd`, `fecha_observacion`, `proveedor`; aún no contiene `extraido_en_utc`. La validación actual rechaza observaciones de meses anteriores; la política de último dato disponible sigue pendiente de decisión.
- **Decisión solicitada al TL:** aprobar o rechazar Frankfurter v2 (tasas combinadas) y definir el tratamiento del cierre de fin de semana, la procedencia de las tasas y el contrato de persistencia. No usar estos datos para liquidaciones oficiales sin esa decisión y pruebas de integración reales.

### English
- **Implemented in the EG-30 draft branch:** separate F5/F6/F7 modules; six countries and currencies; F6 normalization retaining closing and observation dates; currency-coverage checks; offline tests for HTTP retries, per-file atomic replacement, and simulated end-to-end execution.
- **Verified CI:** commit `b88ee009`; `lint`, `test`, `secretos`, and Docusaurus build passed. These checks use simulated responses and **do not** establish live provider availability.
- **Not verified:** live Frankfurter v2 responses for all six currencies, particularly PEN; actual weekend behavior; rate-specific licensing/attribution; PostgreSQL UPSERT integration.
- **Differences from the proposal:** the current JSON includes `moneda`, `fecha`, `unidades_por_usd`, `fecha_observacion`, and `proveedor`, but not yet `extraido_en_utc`. Current validation rejects observations from earlier months; the last-available-observation policy still requires a decision.
- **Decision requested from the TL:** approve or reject Frankfurter v2 combined rates, define weekend month-end handling, rate provenance, and persistence contract. Do not use these rates for official settlements without that decision and live integration tests.


## Actualización de decisión comunicada / Reported decision update — 2026-10-16

### Español
La responsable de EG-30 comunica que Joshua autorizó **utilizar Frankfurter** y, si el cierre mensual cae **sábado o domingo**, tomar la **cotización disponible del día hábil anterior más cercano**. El campo `fecha` mantiene el último día calendario del mes para la liquidación y `fecha_observacion` conserva el día de cotización real. Por ejemplo, para el domingo 2026-05-31, se espera la observación del viernes 2026-05-29 **si la fuente la publica**. No se generan cotizaciones artificiales.

**Alcance de la evidencia:** aprobación comunicada por la integrante del equipo en la conversación; todavía **no hay confirmación escrita del TL en este ADR/PR**. Por tanto, el estado formal sigue **Propuesto / Proposed** hasta que Joshua lo confirme en GitHub. La autorización reportada menciona Frankfurter, **sin especificar inequívocamente v2 o la modalidad de tasas combinadas**. La implementación actual usa v2 porque v1 no cubre las seis monedas; su cobertura y licenciamiento deben verificarse en vivo. Para feriados o ausencia de cotización el viernes, se necesita definir si se retrocede al último día con tasa publicada. El contrato PostgreSQL también requiere coordinación.

### English
The EG-30 owner reports that Joshua authorized **Frankfurter** and instructed the team to use the **nearest previous business day's available rate** when calendar month-end falls on a **Saturday or Sunday**. The `fecha` field retains the calendar month-end required for settlement, while `fecha_observacion` preserves the actual quotation date. For Sunday 2026-05-31, the expected observation is Friday 2026-05-29 **if published by the provider**. Rates must never be fabricated.

**Evidence scope:** this approval was reported by the team member in conversation; there is **no written TL confirmation in this ADR/PR yet**. Formal ADR status therefore remains **Proposed** until Joshua confirms it on GitHub. The reported approval names Frankfurter but **does not unambiguously specify v2 or blended-rate semantics**. The current adapter uses v2 because v1 lacks required currency coverage; live coverage and licensing checks remain necessary. Holiday cases where Friday has no quotation require a defined fallback policy. PostgreSQL persistence contracts also require coordination.


## Actualización de evidencia técnica / Technical evidence update — 2026-10-20

### Español

**Estado:** Propuesto. Los resultados siguientes corresponden a pruebas locales de EG-30 y no sustituyen la aprobación formal del líder técnico.

**F6 — Tasas de cambio**
- Se verificó una ejecución real de Frankfurter v2 para septiembre de 2026, con las seis monedas ARS, BRL, CLP, COP, MXN y PEN.
- Se generaron seis registros de cierre y 170 observaciones diarias; se mantienen separados el cierre calendario y la fecha real de observación.
- Sigue pendiente una comprobación específica de cierre de fin de semana y festivos, así como la atribución y condiciones de uso de las tasas combinadas.

**F7 — Países**
- REST Countries v3.1 dejó de estar disponible; el equipo optó por no migrar a v5 debido a sus requisitos de clave y restricciones de uso.
- La implementación utiliza el dataset público `mledoze/countries`, fijado al commit `c2ac0049c14edcf2436c7aa1b2493222a020b462`.
- Una recuperación real validó 250 países. Fijar la revisión evita cambios inesperados y mejora la reproducibilidad.

**Persistencia e integridad**
- Una carga real a PostgreSQL produjo 6 registros F5, 6 cierres F6, 170 tasas diarias F6 y 250 países F7.
- La repetición de la carga conservó esos conteos (idempotencia para el conjunto probado).
- Una prueba de integración provocó un error después de iniciar inserciones y comprobó el rollback sin dejar países de prueba.
- Se mejoró el mensaje de error ante fallos de conexión; las pruebas locales de fuentes finalizaron con **24 aprobadas**.

**Pendiente:** aprobación formal de Julián sobre Frankfurter v2 y tasas combinadas, política de cierres no hábiles, procedencia y condiciones de uso de las fuentes, sustitución de F7, revisión del PR y resultados de CI. La referencia histórica a la autorización comunicada por Joshua (2026-10-16) se conserva como antecedente, no como aprobación formal.

### English

**Status:** Proposed. The results below are from local EG-30 validation and do not replace formal approval by the technical lead.

**F6 — Exchange rates**
- A live Frankfurter v2 run for September 2026 verified all six required currencies: ARS, BRL, CLP, COP, MXN, and PEN.
- Six closing-rate records and 170 daily observations were generated, retaining separate calendar closing and actual observation dates.
- Weekend and holiday month-end behavior, as well as attribution and terms of use for blended rates, still require specific verification.

**F7 — Country data**
- REST Countries v3.1 became unavailable; the team chose not to migrate to v5 because of API-key requirements and usage restrictions.
- The implementation uses the public `mledoze/countries` dataset pinned to commit `c2ac0049c14edcf2436c7aa1b2493222a020b462`.
- A live retrieval validated 250 countries. Pinning the revision prevents unexpected dataset changes and improves reproducibility.

**Persistence and integrity**
- A live PostgreSQL load produced 6 F5 records, 6 F6 closing rates, 170 F6 daily rates, and 250 F7 countries.
- Re-running the load preserved these counts (idempotency for the tested dataset).
- An integration test intentionally triggered a failure after insertions began and confirmed rollback without leaving test countries.
- Connection failure reporting was improved; the local sources test suite completed with **24 passing tests**.

**Pending:** Julián's formal approval of Frankfurter v2 and blended-rate semantics, non-business-day closing policy, source provenance and terms of use, F7 replacement, PR review, and CI results. The historical report of Joshua's authorization (2026-10-16) is retained as context, not treated as formal approval.

## Decisión solicitada a Julián / Decision requested from Julián — 2026-10-21

**Estado / Status:** **Aceptado / Accepted** el 2026-10-21 por Julián. / Accepted on 2026-10-21 by Julián.

### Español

**Decisión 1 · Fuente alternativa de países F7: dataset `mledoze/countries`.**
- **Qué es:** dataset público fijado al commit `c2ac0049c14edcf2436c7aa1b2493222a020b462`. REST Countries v3.1 ya no está disponible y la v5 exige clave. Una recuperación real validó 250 países.
- **Licencia (verificada el 2026-10-21 en el repositorio):** ODbL 1.0. Exige **atribución**; si se publicara una base de datos derivada, habría que licenciarla igual. El repositorio no publica la base derivada. Las banderas no están cubiertas por la ODbL y el proyecto no las usa.
- **Recomendación:** aceptar, con estas condiciones: (a) registrar la atribución «mledoze/countries, ODbL 1.0, commit `c2ac0049…`» en la documentación de fuentes de EG-30; (b) cambiar el commit fijado solo con revisión; (c) no publicar la tabla de países derivada sin revisar la ODbL.

**Decisión 2 · Cotización de cierre de mes.** La `fecha` queda como el último día calendario (UTC) y `fecha_observacion` conserva el día real de la tasa. Ya está probado el cierre en sábado y domingo (usa el viernes anterior; caso mayo de 2026).
- **Lo que hace hoy el código** (`validar_tasas`, `f6_tasas.py`): toma la última cotización del mes que sea anterior o igual al cierre. **No limita la antigüedad**: si la última cotización fuera del día 10, la aceptaría.
- **Opción A:** dejarlo como está. Cubre fines de semana y festivos mientras haya alguna cotización en el mes.
- **Opción B (recomendada):** añadir un **tope de 5 días corridos** antes del cierre; si la última cotización es más antigua, la carga falla y no se inventa nada. Requiere un cambio pequeño en `validar_tasas` y una prueba (festivo con la cotización del día hábil anterior, y caso sin cotización dentro del tope).

**Decisión 3 · Frankfurter v2 con tasas combinadas.** Son tasas de mercado (mid-market), no la tasa oficial de cada país. Falta aprobar esa semántica y la atribución del proveedor.

**Resolución (2026-10-21):**
- [x] **Fuente F7 `mledoze/countries`: aprobada** con las condiciones (a), (b) y (c).
- [x] **Regla de cierre: opción B** (tope de 5 días corridos). Julián delegó la elección («la que veas mejor») y se adopta la B porque evita aceptar en silencio una cotización antigua.
- [x] **Frankfurter v2 con tasas combinadas: aprobado.**

**Implementado:** `validar_tasas` rechaza cotizaciones de más de 5 días antes del cierre (`MAX_ANTIGUEDAD_DIAS`), con pruebas de festivo, del límite exacto (5 días), del rechazo a los 6 días y del tope por moneda; la atribución ODbL queda en el registro de fuentes y en `f7_paises.py`. **Pendiente:** revisión del PR #3, prueba real de un cierre en fin de semana o festivo, y que el contrato de persistencia no cambie.

### English

**Decision 1 · Alternative F7 country source: the `mledoze/countries` dataset.**
- **What it is:** a public dataset pinned to commit `c2ac0049c14edcf2436c7aa1b2493222a020b462`. REST Countries v3.1 is no longer available and v5 requires a key. A live retrieval validated 250 countries.
- **License (checked on 2026-10-21 in the repository):** ODbL 1.0. It requires **attribution**, and a publicly shared derived database would have to be licensed the same way. This repository does not publish the derived database. Flags are not covered by the ODbL and the project does not use them.
- **Recommendation:** accept, on three conditions: (a) record the attribution "mledoze/countries, ODbL 1.0, commit `c2ac0049…`" in the EG-30 sources documentation; (b) change the pinned commit only after review; (c) do not publish the derived country table without reviewing the ODbL.

**Decision 2 · Month-end rate.** `fecha` stays the last calendar day (UTC) and `fecha_observacion` keeps the actual quotation day. Saturday and Sunday closings are already tested (the previous Friday is used; May 2026 case).
- **What the code does today** (`validar_tasas`, `f6_tasas.py`): it takes the latest quotation in the month on or before the closing date. **It has no staleness limit**: a last quotation from the 10th would be accepted.
- **Option A:** keep it as is. It covers weekends and holidays as long as the month has any quotation.
- **Option B (recommended):** add a **5-calendar-day cap** before the closing date; an older last quotation makes the load fail and nothing is invented. It needs a small change in `validar_tasas` and a test (holiday using the previous business day's quotation, and a case with no quotation inside the cap).

**Decision 3 · Frankfurter v2 combined rates.** These are mid-market rates, not each country's official rate. The semantics and the provider attribution still need approval.

**Resolution (2026-10-21):**
- [x] **F7 source `mledoze/countries`: approved** with conditions (a), (b) and (c).
- [x] **Closing rule: option B** (5-calendar-day cap). Julián delegated the choice ("whichever you think is best") and B is adopted because it avoids silently accepting a stale quotation.
- [x] **Frankfurter v2 combined rates: approved.**

**Implemented:** `validar_tasas` rejects quotations more than 5 days before the closing date (`MAX_ANTIGUEDAD_DIAS`), with tests for a holiday, the exact 5-day limit, rejection at 6 days and the per-currency cap; the ODbL attribution is in the sources register and in `f7_paises.py`. **Pending:** PR #3 review, a live test of a weekend or holiday closing, and keeping the persistence contract unchanged.
