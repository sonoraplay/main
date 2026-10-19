# SonoraPlay Royalties — Business Rule Ambiguities

| Field | Value |
|---|---|
| Jira | EG-11 · 02 · Resolve business rule ambiguities with the instructor |
| Sprint | S1 · Discovery & Design |
| Owner | María Clara |
| Decided by | Team (María Clara, Joshua, Andrea) |
| Date | 2026-10-02 |
| Status | **Assumptions** — pending instructor validation |
| Questions sent to instructor | 2026-09-30 |
| Repo path | `docs/analisis/ambiguedades-rn.md` |

## Purpose

This document records the 10 business-rule ambiguities listed in section 7 of the project analysis. The instructor has not answered yet, so, as allowed by acceptance criterion 4 of EG-11, the team records an explicit working **Assumption** for each one so development is not blocked.

These assumptions are **not** instructor-approved requirements. When the instructor answers, the row is updated (answer, date, who answered) and every affected story, test, `config.py` value and ADR is updated in the same PR.

## Summary table

| # | Rule | Question | Answer (type) | Date | Answered by | Impact | Story / ADR |
|---|---|---|---|---|---|---|---|
| Q1 | RN-01 | Does a pause inside the 30 s reset the count? | Yes, it resets (**Assumption**) | 2026-10-02 | Team | Validity function and CA-01 tests | EG-17 · EG-35 |
| Q2 | RN-03 | "< 1,000 listeners": per day, month or all-time? | Monthly unique listeners (**Assumption**) | 2026-10-02 | Team | Fraud signal 2 and its window | EG-18 · EG-36 · ADR-0005 |
| Q3 | RN-03 | Exclude the account for the day or the whole month? | Whole settlement month, under review (**Assumption**) | 2026-10-02 | Team | Exclusion period in `config.py` | EG-18 · EG-36 · EG-43 · ADR-0005 · ADR-0007 |
| Q4 | RN-02 / RN-04 | Which time zone defines "day" and "month"? | UTC (**Assumption**) | 2026-10-02 | Team | Daily cap, month boundaries, offline cut-off | EG-17 · EG-22 · EG-15 · **ADR-0002** |
| Q5 | RN-05 | "Net" subscription revenue, net of what? | Net value as stored in F3; nothing else deducted (**Assumption**) | 2026-10-02 | Team | Pool formula input | EG-13 · EG-23 · EG-37 |
| Q6 | RN-10 | Family members in different countries: which country gets the revenue? | Billing country of the family account (**Team decision**, ADR-0008) | 2026-10-13 | Team | Country pool attribution | EG-23 · EG-37 · [ADR-0008](../adr/0008-pais-bolsa-dos-componentes.md) |
| Q7 | RN-06 | Does the contractual % change by territory? | Only if the contract defines it explicitly (**Assumption**) | 2026-10-02 | Team | F4 data model and settlement join | EG-14 · EG-20 · EG-23 |
| Q8 | RN-05 / RN-06 | Do Free-plan plays enter the subscription denominator? | No; two components with separate denominators (**Team decision**, ADR-0008; to confirm with the instructor) | 2026-10-13 | Team | Settlement formula | EG-23 · EG-37 · [ADR-0008](../adr/0008-pais-bolsa-dos-componentes.md) |
| Q9 | F1 | Unify duplicate tracks by `track_id`? | Yes, one canonical row per `track_id` (**Assumption**) | 2026-10-02 | Team | Clean catalog | EG-12 · ADR-0003 |
| Q10 | Demo | Full 900k users on AWS or a subset? | Configurable subset; full volume possible (**Assumption**) | 2026-10-02 | Team | Seed volume, AWS cost | EG-28 · EG-45 · EG-32 · E-14 |

## Questions and working assumptions

### Q1 — RN-01: Continuous playback

**Question:** If a user pauses or interrupts a track before reaching 30 seconds, does the continuous-playback counter reset?

**Assumption:** Yes. The 30 seconds must be continuous. A pause, seek or interruption before reaching the threshold resets the count. A play is valid when one uninterrupted segment is ≥ 30 s (exactly 30 s is valid).

**Impact:** `src/sonoraplay/reglas/validez.py` (created in EG-17) and CA-01 tests (EG-17, done in PR #12 — `tests/reglas/test_validez.py` covers "15 s + pause + 20 s = not valid"); Spark Silver layer (EG-35).

### Q2 — RN-03: Artist listener threshold

**Question:** Is the "< 1,000 listeners" count calculated daily, monthly or historically?

**Assumption:** Monthly unique listeners of the artist within the settlement month (UTC, see Q4), aligned with the monthly settlement. Signal 2 is therefore evaluated at month close, not in real time.

**Impact:** Fraud signal 2 in EG-18 and EG-36; window documented in ADR-0005.

### Q3 — RN-03: Scope of suspicious-account exclusion

**Question:** When an account is flagged as suspicious, are its streams excluded only for the affected day or for the entire settlement month?

**Assumption:** For the **entire settlement month** in which the account is flagged. All its streams that month are excluded from the pool and marked `under_review`. If the review clears the account, its streams are released as an **adjustment** in the next settlement (append-only, never overwriting a closed month).

**Why:** RN-03 says excluded streams "remain under review", which only makes sense if they can be paid later; and paying fraud by mistake is costlier for the labels than a delayed payment to a legitimate user. The false-positive cost is controlled by CA-10 (< 2%).

**Impact:** Exclusion period in `config.py` (EG-18, done in PR #8 — `ReglasFraudeConfig.periodo_exclusion = "mes"`); ADR-0005 (thresholds and period), ADR-0007 (adjustments), fraud report EG-43.

### Q4 — RN-02 / RN-04: Time zone

**Question:** Which time zone defines a "day" and a "month" for play limits and offline-stream attribution?

**Assumption:** UTC for every day and month boundary. RN-04 already states its cut-off in UTC ("day 2, 23:59 UTC"), so using UTC everywhere keeps the rules consistent.

**Impact:** Daily cap (EG-17), offline attribution (EG-22), F2 timestamps in UTC (EG-15). Decision recorded in **ADR-0002 — Accepted (2026-10-02)** (`docs/adr/0002-zona-horaria-dia-mes.md`).

### Q5 — RN-05: Net subscription revenue

**Question:** What deductions are included in "net subscription revenue"?

**Assumption:** Use the net amount stored in the F3 subscription source, before applying the 52% allocation. No taxes, store fees or commissions are invented unless the source provides them.

**Impact:** F3 exposes it as `pagos.monto_usd` with `estado = 'aprobado'` (EG-13, PR #4); that amount is taken as net; pool function in EG-23 and EG-37.

### Q6 — RN-10: Family accounts across countries

**Question:** If members of the same family account stream from different countries, which country receives the subscription revenue?

**Team decision ([ADR-0008](../adr/0008-pais-bolsa-dos-componentes.md), EG-23, 2026-10-13):** The **billing country** of the family account. For settlement, the valid streams of all members are also counted in the billing country's pool (numerator and denominator), so revenue and streams stay in the same pool. The stream country is kept only for consumption analytics and for RN-08 (territorial exclusions).

**Impact:** implemented in EG-23 (`paises_facturacion` and `suscripcion_neta_por_pais` in `src/sonoraplay/reglas/liquidacion.py`: members inherit the family holder's billing country and the family payment enters the pool once); reused by EG-37. Decision and alternatives in ADR-0008.

### Q7 — RN-06: Contract percentage by territory

**Question:** Can the contractual royalty percentage vary by territory?

**Assumption:** The F4 model supports an optional territory on each contract condition. A territory-specific percentage is applied only when the contract explicitly defines one; otherwise the general percentage applies. Validity date (RN-07) and territorial exclusions (RN-08) still apply.

**Impact:** F4 seed (EG-14, done in PR #13: `contratos.territorio IS NULL` is the general condition), F4 API (EG-20), settlement join (EG-23).

### Q8 — Free plan and subscription denominator

**Question:** Do Free-plan streams enter the denominator used to distribute the subscription component of the pool?

**Team decision ([ADR-0008](../adr/0008-pais-bolsa-dos-componentes.md), EG-23, 2026-10-13):** No. The pool is split into two components, each with its own denominator:

- **Subscription component** = 52% × net subscription revenue, distributed by valid streams from **paid plans** (individual, family, student).
- **Advertising component** = 45% × advertising revenue, distributed by valid streams from the **Free plan**.

Royalty per rights holder and country = (subscription component × paid share + advertising component × free share) × contractual % (RN-06, RN-07). Example (EG-23 criterion 1): Colombia with 100,000 USD subscription and 20,000 USD advertising, a holder with a 5 % paid share, a 10 % free share and an 80 % contract receives **2,800.00 USD**; with 5 % in both components the result is 2,440.00, the same as the single pool. RNF-02 still holds: the sum per country never exceeds the pool (± 0.01 USD; rounding rule in ADR-0007).

**Note:** this is a deviation from the literal single-pool formula in RN-05/RN-06. It is the decision with the biggest money impact and the first one to confirm with the instructor; if the instructor asks for a single pool, ADR-0008 is superseded and only the denominator in `liquidar_pais` changes.

**Impact:** implemented in EG-23 (`calcular_bolsa` and `liquidar_pais`, fractions in `ReglasLiquidacionConfig`); reused by EG-37; ADR-0008.

### Q9 — F1 duplicate tracks

**Question:** When F1 contains duplicate records, are they unified by `track_id`?

**Assumption:** Yes. The clean catalog has one canonical row per `track_id`; the different genres of the same track are kept as a list (or a bridge table), not as separate tracks, so plays are not split or double-counted. The detailed strategy and the number of removed/merged rows go in ADR-0003.

**Impact:** EG-12; ADR-0003.

### Q10 — AWS demo volume

**Question:** Must the final AWS demo process the full simulated volume of ~900,000 users, or may it use a representative subset?

**Assumption:** Development, testing and the AWS demo use a configurable subset (`--modo dev|completo`, 10,000 or 900,000 users). The seed must still be able to generate the full 900k volume locally. A full run on AWS depends on the budget and is decided in the cost analysis.

**Impact:** EG-28 (seed on RDS), EG-45 (full month on AWS), EG-32 (costs), E-14 demo.

## How this document is maintained

1. The 10 questions were sent to the instructor on 2026-09-30; no answer yet.
2. When an answer arrives, update its row: answer type changes from **Assumption** (or **Team decision**, when an ADR already records it) to **Instructor**, with date and name.
3. If the answer changes an assumption, update the affected story, tests, `config.py` value and ADR in the same PR, and comment on the Jira story.
4. Related ADRs: ADR-0002 (Q4, Accepted), ADR-0003 (Q9), ADR-0005 (Q2, Q3), ADR-0007 (Q3), ADR-0008 (Q6, Q8).


---

## Español — Guía de lectura y estado de las decisiones

Este documento registra **diez preguntas (Q1–Q10)** de interpretación de reglas de negocio. La tabla anterior es la fuente detallada de cada pregunta, su supuesto, impacto, historia y ADR asociado. **El estado «Assumption» significa supuesto de trabajo del equipo, no aprobación del docente.** No debe convertirse una hipótesis en requisito confirmado por el simple hecho de traducirla o publicarla en Docusaurus.

| Pregunta | Tema que debe verificarse |
|---|---|
| Q1 | Continuidad de los 30 segundos de reproducción (RN-01) |
| Q2 | Ventana para contar oyentes únicos de un artista (RN-03) |
| Q3 | Alcance temporal de la exclusión de cuentas sospechosas (RN-03) |
| Q4 | Zona horaria para el día y el mes (RN-02 / RN-04) |
| Q5 | Definición de ingreso neto de suscripciones (RN-05) |
| Q6 | País de facturación de cuentas familiares (RN-10) |
| Q7 | Porcentaje contractual por territorio (RN-06) |
| Q8 | Tratamiento del plan gratuito en el denominador |
| Q9 | Pistas duplicadas en el catálogo F1 |
| Q10 | Volumen de demostración en AWS |

**Control de cambios:** cuando el docente responda, actualizar en el mismo PR la respuesta, fecha, persona que respondió, historia afectada, pruebas, valores de `config.py` y ADR relacionados. Hasta entonces, las decisiones que dependan de Q1–Q10 deben etiquetarse como supuestos.
