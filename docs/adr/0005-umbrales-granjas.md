# ADR-0005 · Umbrales de las 3 señales de granja y exclusión por todo el mes

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-02 |
| Historia que lo origina | HU 09 · EG-18 |
| Responsable | María Clara |
| Revisó | Aprobado en el PR #8 (fusionado el 2026-10-05) |
| Referencias | RN-03, CA-03, CA-10, EG-11 Q2 / Q3 / Q4, ADR-0002, ADR-0007 |

## 1. Contexto

RN-03 marca una cuenta como sospechosa de granja de reproducciones si cumple **cualquiera** de tres señales:

1. Más de **20 h** de escucha en **24 h**.
2. Más del **70 %** de sus reproducciones a un solo artista que tiene **menos de 1.000 oyentes**.
3. Usa un **dispositivo** compartido por **más de 5 cuentas**.

Las reproducciones de una cuenta sospechosa se excluyen de la bolsa y "quedan en revisión". El enunciado no dice cómo se mide la ventana de 24 h, en qué periodo se cuentan los oyentes del artista (Q2) ni cuánto dura la exclusión (Q3). Estas decisiones mueven dinero: una granja no detectada se lleva regalías de artistas reales, y un falso positivo retrasa el pago de un oyente legítimo. CA-10 exige **≥ 95 %** de granjas detectadas con **< 2 %** de falsos positivos.

La implementación vive en `src/sonoraplay/reglas/fraude.py` como funciones puras, y los valores en `ReglasFraudeConfig` de `src/sonoraplay/config.py`.

## 2. Qué debe cumplir la decisión

- **Negocio:** RN-03 (las 3 señales, umbrales estrictos: "más de"); CA-03 (las reproducciones de la cuenta sospechosa se excluyen y quedan en revisión).
- **Negocio:** EG-11 Q2 (oyentes únicos del artista **por mes UTC**), Q3 (exclusión de **todo el mes de liquidación**), Q4 / ADR-0002 (todo en UTC).
- **Requisito:** CA-10 (≥ 95 % de detección, < 2 % de falsos positivos), medido en EG-43.
- **Requisito:** el informe de fraude (EG-43) necesita saber **qué señales** se cumplieron, no solo sí/no.
- **Costo:** ninguno adicional; son funciones puras que corren dentro del job de liquidación.
- **Equipo:** los umbrales deben poder recalibrarse sin tocar el código.

## 3. Opciones consideradas

### 3.1 Cómo medir "20 h en 24 h"

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · **Ventana móvil de 24 h** | Detecta una granja que reparte 21 h entre las 18:00 de un día y las 17:59 del siguiente; no depende de la zona horaria | Algo más costoso de calcular (dos punteros sobre reproducciones ordenadas, O(n · k)) | 0 |
| B · Día calendario UTC | Trivial de agrupar con `GROUP BY fecha` | La granja de arriba suma 6 h y 15 h en dos días y **no se marca**; basta con cambiar la hora de arranque para evadirla | 0 |

Una reproducción que cruza el borde de la ventana cuenta solo la parte que cae dentro; así una sesión larga no se cuenta dos veces ni infla la ventana.

### 3.2 Umbral del dispositivo compartido

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · **Marcar si > 5 cuentas** (literal de RN-03) | Una familia de hasta 5 cuentas en la tablet o el TV de la casa **no se marca** | El plan familiar admite **hasta 6 miembros**: una familia completa en un solo dispositivo sí se marca | 0 |
| B · Marcar si > 6 cuentas | Protege a la familia completa | Contradice RN-03 y deja pasar granjas pequeñas de 6 cuentas | 0 |
| C · Excluir del conteo a los miembros del mismo grupo familiar (F3) | Elimina ese falso positivo | Añade una dependencia de F3 a la regla y un vector de evasión (meter cuentas de la granja en una "familia") | 0 |

### 3.3 Periodo de exclusión

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · **Todo el mes de liquidación** (Q3) | No se paga fraude por error; coherente con una liquidación mensual y con señales que se evalúan al cierre (Q2) | Un falso positivo retrasa el pago de todo el mes del oyente | 0 |
| B · Solo el día de la señal | Penaliza menos a los falsos positivos | La señal 2 es mensual y no tiene "día"; la granja cobra el resto del mes | 0 |

## 4. Decisión

**Elegimos 3.1-A, 3.2-A y 3.3-A**, con los valores de `ReglasFraudeConfig`:

| Parámetro | Valor | Se marca si |
|---|---|---|
| `horas_max_24h` | 20 | horas escuchadas en cualquier ventana móvil de 24 h **> 20** |
| `porcentaje_max_artista` | 0,70 | reproducciones al artista más escuchado / reproducciones del mes **> 70 %** … |
| `oyentes_min_artista` | 1.000 | … **y** ese artista tiene **< 1.000** oyentes únicos en el mes UTC |
| `cuentas_max_dispositivo` | 5 | la cuenta usó algún dispositivo con **> 5** cuentas en el mes |
| `periodo_exclusion` | `"mes"` | todas las reproducciones del mes de la cuenta sospechosa → `en_revision` |

Los casos en el límite (exactamente 20 h, 70 %, 1.000 oyentes, 5 cuentas) **no** se marcan, porque RN-03 dice "más de" / "menos de". La señal 2 cuenta **reproducciones**, no milisegundos. La ventana móvil es la única forma de cumplir RN-03 sin que la granja la evada eligiendo la hora de arranque (criterio de negocio de la sección 2), y la exclusión mensual sigue a Q3: es más barato para los sellos retrasar un pago legítimo que pagar fraude.

**Exclusión y liberación.** `marcar_exclusion` no borra nada: devuelve cada reproducción con su estado (`en_revision` o `valida_para_fraude`). Si la revisión manual descarta el fraude, las reproducciones se liberan y se pagan como **ajuste** en la liquidación siguiente, sin reabrir el mes cerrado (append-only); el mecanismo se define en [ADR-0007](README.md) (pendiente, EG-23).

## 5. Consecuencias

- **Positivas:** cada señal es una función pura con pruebas de límite; el resultado incluye `senales` para el informe de EG-43; recalibrar es cambiar `config.py`.
- **Negativas / lo que aceptamos:**
  - Una familia de 6 miembros que use **un solo** dispositivo se marca (3.2). Es poco frecuente (cada miembro suele usar su propio teléfono) y se resuelve en la revisión.
  - Un oyente legítimo que pase más de 20 h escuchando en 24 h (p. ej. música ambiente en un local) se marca; RN-03 no distingue ese caso.
  - Las señales se evalúan por mes UTC: una ventana de 24 h que cruza el cambio de mes se parte en dos evaluaciones.
- **Riesgos y mitigación:**
  - *Falsos positivos por encima del 2 %* → se miden en EG-43 y se recalibra `ReglasFraudeConfig` (y este ADR pasa a *Reemplazado*).
  - *Granjas adaptadas a los umbrales* (19 h, 69 %, 5 cuentas) → RN-03 no las cubre por diseño; EG-43 reporta cuentas cercanas a los umbrales para vigilarlas.
  - *El esquema de `Reproduccion` difiere de F2* → la correspondencia quedó documentada en EG-15 ([`docs/datos/eventos-f2.md`](../datos/eventos-f2.md), [ADR-0004](0004-esquema-eventos-f2.md)), y Silver (EG-35) arma el registro.

## 6. Cómo sabremos que funciona

- **Pruebas unitarias (EG-18):** `tests/reglas/test_fraude.py` cubre, por señal, un caso positivo, uno legítimo y los límites exactos; la ventana móvil entre dos días; reproducciones que cruzan el borde; una cuenta con dos señales; la exclusión de todo el mes; y el rechazo de datetimes naive. Cobertura de `sonoraplay.reglas`: 100 %.
- **CA-10 (EG-43):** el simulador F2 (EG-19) etiqueta qué cuentas son granjas. Sobre esas etiquetas se construye la **matriz de confusión** (VP, FP, FN, VN) de `evaluar_cuentas`:
  - detección = VP / (VP + FN) **≥ 95 %**;
  - tasa de falsos positivos = FP / (FP + VN) **< 2 %**.
  Si no se cumple, se ajustan los umbrales en `config.py` y se vuelve a medir; el informe desglosa por señal (`senales`) para saber cuál recalibrar.

## 7. Fuentes

- Enunciado del proyecto: RN-03, CA-03, CA-10.
- Supuestos de negocio: [ambiguedades-rn.md](../analisis/ambiguedades-rn.md) (Q2, Q3, Q4).
- [ADR-0002](0002-zona-horaria-dia-mes.md) — UTC para el día y el mes.
- Python `datetime` — objetos *aware* y `datetime.UTC`: https://docs.python.org/3/library/datetime.html
- Matriz de confusión, sensibilidad y tasa de falsos positivos: https://en.wikipedia.org/wiki/Confusion_matrix


---

## English — Decision summary

**Accepted (October 2, 2026; EG-18).** Flag suspected streaming farms when listening exceeds **20 hours in any rolling 24-hour window**, or more than **70%** of a month's plays target an artist with **fewer than 1,000 monthly unique listeners**, or a device is used by **more than five accounts** in the month. Boundary values alone do not trigger flags. A flagged account's entire month enters `en_revision`; records are retained, not deleted. Cleared cases are paid later as append-only adjustments under ADR-0007.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
