# EG-30 · Fuentes F5, F6 y F7 / F5, F6 and F7 sources

## Español

**Estado:** implementación en PR borrador #29. CI y compilación Docusaurus aprobados en el commit `68715c45` (verificación de pruebas simuladas, no de consultas HTTP reales). **La aceptación final y el despliegue real siguen pendientes.**

- **F5:** CSV mensual determinista de ingresos publicitarios simulados, semilla fija, importes con dos decimales y seis países (AR, BR, CL, CO, MX, PE), menos de 1.000 filas. Las monedas se contrastan con F7.
- **F6:** adaptador Frankfurter **v2** con USD como base y las seis monedas ARS, BRL, CLP, COP, MXN y PEN. Las tasas de cierre conservan `fecha_observacion` y `fecha` calendario; una serie diaria **opcional** conserva únicamente las fechas publicadas, sin inventar tasas en festivos. La cobertura y el proveedor deben validarse con respuestas reales. La integrante responsable informó que Joshua autorizó Frankfurter y el día hábil anterior para cierres de fin de semana; ADR-0021 sigue **formalmente propuesto** hasta constancia escrita en GitHub. Frankfurter v2 y las seis monedas aún requieren verificación real.
- **F7:** REST Countries v3, ISO-2, región y monedas; se exigen al menos 200 países.
- **Fallos:** tres intentos para errores HTTP transitorios. Se validan las tres fuentes antes de comenzar a escribir. Cada archivo se reemplaza atómicamente; **no existe transacción atómica entre todos los archivos**.
- **Idempotencia local:** ejecutar de nuevo con el mismo mes y semilla reemplaza archivos, no añade filas. **La idempotencia transaccional en PostgreSQL todavía no está implementada**.
- **Pendientes:** registrar la confirmación formal de v2, licencia y tratamiento de festivos con Joshua; pruebas HTTP reales para seis monedas y fechas de fin de semana; carga transaccional UPSERT en PostgreSQL con esquema acordado; evidencias de despliegue.

Ejecutar (requiere internet):

```bash
uv run python -m sonoraplay.fuentes.eg30 --mes 2026-09 --salida data/generated/eg30 --diarias
uv run pytest tests/fuentes/test_eg30.py
```

La opción `--diarias` descarga observaciones publicadas durante el mes y crea `f6_tasas_diarias_2026-09.json`. No se asume que todos los días calendario tengan cotización. La normalización diaria no reemplaza la aprobación de la política de cierre.

## English

**Status:** implementation in draft PR #29. CI and Docusaurus build passed at commit `68715c45` (mock-based tests, not live HTTP verification). **Final acceptance and live deployment remain outstanding.**

- **F5:** deterministic monthly simulated advertising-revenue CSV, fixed seed, two-decimal amounts and six countries (AR, BR, CL, CO, MX, PE), fewer than 1,000 rows. Currencies are checked against F7.
- **F6:** Frankfurter **v2** adapter using USD as base and the six currencies ARS, BRL, CLP, COP, MXN and PEN. Closing rates retain both the actual observation date and calendar closing date; an **optional** daily series preserves only published observations, without inventing holiday rates. Live source and coverage verification are still required. The EG-30 owner reports Joshua approved Frankfurter and the preceding business day for weekend month-ends; ADR-0021 remains **formally proposed** pending written GitHub confirmation. Frankfurter v2 and six-currency coverage still require live verification.
- **F7:** REST Countries v3, ISO-2, region and currencies; at least 200 countries required.
- **Failures:** three attempts for transient HTTP errors. All three sources are validated before writing. Each file is replaced atomically; **there is no transaction across all output files**.
- **Local idempotency:** rerunning with the same month and seed replaces output files rather than appending rows. **Transactional PostgreSQL idempotency is not yet implemented**.
- **Outstanding:** written confirmation of v2, licensing and holiday fallback from Joshua; live HTTP checks for six currencies and weekend dates; transactional PostgreSQL UPSERT with an agreed schema; deployment evidence.

Run (requires internet):

```bash
uv run python -m sonoraplay.fuentes.eg30 --mes 2026-09 --salida data/generated/eg30 --diarias
uv run pytest tests/fuentes/test_eg30.py
```

The `--diarias` option downloads published observations during the month and creates `f6_tasas_diarias_2026-09.json`. Not every calendar day is expected to have a published rate. Daily normalization does not replace approval of the closing-date policy.
