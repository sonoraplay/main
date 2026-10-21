# ADR-0021 · Propuesta de fuentes y fecha de cierre para F6 / Proposed F6 sources and closing-date policy

| Campo / Field | Valor / Value |
|---|---|
| Estado / Status | **Propuesto / Proposed — NO aprobado / NOT approved** |
| Fecha / Date | 2026-10-15 |
| Historia / Story | EG-30 (F5, F6, F7) |
| Responsable / Owner | María Clara (propuesta para revisión del TL) |
| Revisor / Reviewer | Joshua — pendiente / pending |
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
