# ADR-0007 · Cierre de mes append-only, ajustes en la liquidación siguiente y redondeo por mayor residuo

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-13 |
| Historia que lo origina | HU 14 · EG-23 |
| Responsable | Andrea Zárate y María Clara Manjarrés |
| Revisó | Joshua — aprobado el 2026-10-13, validado en la práctica por el esqueleto de la EG-24 (PR #25) |
| Referencias | RF-09, CA-07, RNF-02, RN-04, RN-07, RN-08, EG-11 Q3, ADR-0002, ADR-0005, ADR-0006, ADR-0008 |

## 1. Contexto

La liquidación es mensual: cada mes UTC (ADR-0002) se reparte la bolsa de cada país entre los titulares y el resultado se publica en la API de sellos (EG-21). Hay tres hechos que obligan a decidir qué pasa **después** de publicar un mes y cómo se redondea:

1. **Datos que llegan tarde.** Una reproducción offline sincronizada después del corte (día 2 del mes siguiente, 23:59 UTC) ya no entra en su mes real: la EG-22 la marca como `TipoAtribucion.AJUSTE` y le asigna como mes de liquidación la **primera liquidación todavía abierta** cuando llega la sincronización: la del mes anterior a la sincronización si esta llega antes o durante su corte del día 2, o la del mes de la sincronización si no (`reglas/atribucion.py`, RN-04; detalle en [atribucion-offline.md](../datos/atribucion-offline.md)).
2. **Reproducciones liberadas tras una revisión de fraude.** Las cuentas sospechosas quedan `en_revision` todo el mes (ADR-0005, Q3). Si la revisión descarta el fraude, esas reproducciones deben pagarse, pero el mes en que ocurrieron ya está cerrado.
3. **Errores de cálculo.** Si se descubre un error (un contrato mal cargado, un pago omitido), hay que poder volver a liquidar un mes.

El modelo de lectura de la EG-21 (`db/ddl/003_reportes_regalias.sql`) ya es append-only: cada corrida crea una fila en `liquidaciones`, y la API muestra la de mayor `publicada_en` de cada mes. Este ADR formaliza esa decisión y define dónde entran los ajustes.

**Redondeo.** El contrato de la EG-21 decía «`ROUND_HALF_UP` por fila» y dejaba para este ADR el ajuste necesario para cumplir RNF-02: la suma de regalías de un país y componente no puede superar la bolsa (± 0,01 USD). El redondeo independiente por fila **no** lo garantiza. Con una bolsa de 100,005 USD y tres titulares al 100 % con un tercio cada uno, cada fila vale 33,335 → `ROUND_HALF_UP` da 33,34, y 3 × 33,34 = **100,02 USD**: supera la bolsa en 0,015 USD, por encima de la tolerancia. Con cientos de titulares por país, el error crece con el número de filas.

**Incidencias.** RN-08 exige registrar un incidente cuando una reproducción cae en un territorio excluido; además, una pista puede no tener un contrato vigente en la fecha de la reproducción. Las funciones de la EG-23 son puras (sin BD, archivos ni reloj), así que hay que decidir cómo salen esos incidentes.

## 2. Qué debe cumplir la decisión

- **Negocio:** RF-09 (la liquidación se persiste append-only con su ID, flujo ⑨ de la [arquitectura v1](../arquitectura/arquitectura-v1.md)); CA-07 (cierre y re-liquidación del mes): un sello que ya consultó o cobró un mes no ve cambiar ese mes sin que quede rastro.
- **Negocio:** RN-04 y Q3: las reproducciones tardías y las liberadas se pagan **como ajuste**, sin reabrir el mes cerrado.
- **Negocio:** RN-07: cada reproducción usa el % vigente en **su** fecha UTC, aunque se liquide en un mes posterior.
- **Requisito:** RNF-02: suma por país y componente ≤ bolsa + 0,01 USD; dinero siempre en `Decimal`, nunca `float`.
- **Requisito:** cada fila de `reporte_regalias` debe quedar cerca de su valor exacto (`bolsa × participación × % / 100`): un sello que recalcule su fila no debe encontrar más de 1 centavo de diferencia.
- **Requisito:** el resultado debe ser **determinista**: la misma entrada en otro orden produce las mismas filas (la EG-37 en Spark reparte los datos sin orden garantizado).
- **Costo:** append-only guarda una corrida completa por re-liquidación. Son pocas filas (titular × país × componente × %) frente a los 20 GB de RDS `db.t4g.micro` (arquitectura v1): costo adicional ≈ 0 USD/mes.
- **Equipo:** funciones puras (como `validez.py`, `fraude.py` y `atribucion.py`), reutilizables desde el esqueleto (EG-24) y desde Spark (EG-37).

## 3. Opciones consideradas

### 3.1 Qué pasa con un mes ya publicado

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · Reescribir el mes (`UPDATE` / `DELETE` + `INSERT`) | Una sola versión por mes; consultas simples | Se pierde lo que el sello ya vio o cobró (incumple RF-09 y CA-07); una corrida que falle a mitad deja el mes a medias y visible | 0 |
| B · **Append-only: re-liquidar crea una liquidación nueva; lo tardío entra como ajuste en la liquidación siguiente** | Historial completo y auditable; la API solo muestra liquidaciones publicadas (`publicada_en` no nulo), así que nunca se ve una a medias; coincide con la EG-22, que ya asigna el mes de liquidación del ajuste | Lo tardío se paga con la bolsa del mes en que se liquida, no con la de su mes real (ver sección 5) | ≈ 0 (filas extra en RDS) |
| C · Append-only, pero cada dato tardío dispara una re-liquidación de su mes original | Cada reproducción se paga con la bolsa de su mes real | Cambia lo que **todos** los titulares de ese país cobraron ese mes, por cada sincronización tardía; un mes nunca queda cerrado, en contra de RN-04 y Q3 | ≈ 0, pero una corrida extra por mes afectado |

### 3.2 Cómo se redondea cada fila

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · `ROUND_HALF_UP` por fila (contrato de la EG-21) | Cada fila es el redondeo «de libro» de su valor exacto | La suma puede superar la bolsa: 3 × 33,335 → 100,02 > 100,005 (incumple RNF-02); el exceso crece con el número de filas | 0 |
| B · Truncar cada fila (`ROUND_DOWN`) | La suma nunca supera la bolsa | Se pierde hasta 1 centavo por fila: con 7 titulares, 52 / 7 → 7 × 7,42 = 51,94 (6 centavos sin repartir); con miles de filas, decenas de dólares quedan fuera | 0 |
| C · **Mayor residuo** (truncar y repartir los centavos que faltan) | La suma por componente es exactamente `redondear_usd(suma exacta)`, que nunca supera la bolsa en más de 0,005 USD; cada fila queda a < 0,01 de su valor exacto; no se pierden ni se crean centavos | Una fila puede diferir en 0,01 del `ROUND_HALF_UP` individual; requiere un orden determinista para los empates | 0 |

## 4. Decisión

**Elegimos 3.1-B y 3.2-C**, implementadas en `src/sonoraplay/reglas/liquidacion.py`.

**Cierre append-only (3.1-B).** Un mes publicado nunca se modifica. Ese es el criterio de RF-09 y CA-07, y es lo que la EG-22 ya supone.

- **Re-liquidar** un mes (para corregir un error) inserta una fila nueva en `liquidaciones` con `publicada_en` NULL. Después escribe todas sus filas en `reporte_regalias` y al final pone `publicada_en`. La API muestra la de mayor `publicada_en` (DDL 003); las anteriores quedan como historial.
- **Datos tardíos y liberados.** Una reproducción `TipoAtribucion.AJUSTE` (EG-22) o liberada tras la revisión de fraude (ADR-0005) se incluye en la **siguiente** liquidación como cualquier otra reproducción válida. Cuenta en el denominador del mes en que se liquida y se paga con la bolsa de ese mes. `liquidar_pais` no exige que `inicio` caiga en el período, a propósito.
- **El % es el de su fecha.** `porcentaje_aplicable` elige la condición por la fecha UTC de la propia reproducción (RN-07): una reproducción del 20 de agosto liquidada en octubre usa el % vigente el 20 de agosto. Si el % cambió, sale una fila por cada % (la PK de `reporte_regalias` incluye `porcentaje_contractual`).

**Redondeo por mayor residuo (3.2-C).** Es el único punto de redondeo de la liquidación: `_repartir_centavos`, aplicado por país y componente.

1. Cada fila se calcula exacta en `Decimal`: `bolsa_componente × reproducciones × % / (100 × total del componente)`.
2. Cada fila se **trunca** al centavo.
3. El total objetivo es `redondear_usd(suma exacta)` (`ROUND_HALF_UP` de la suma, no de cada fila). Como los % son ≤ 100, la suma exacta es ≤ bolsa, y el objetivo nunca supera la bolsa en más de 0,005 USD.
4. Los centavos que faltan para llegar al objetivo se asignan de a uno a las filas con **mayor residuo** (valor exacto − truncado). Los empates se rompen por el orden (titular, % descendente), así que el resultado no depende del orden de entrada.
5. `verificar_invariantes` comprueba RNF-02 por componente y en total antes de devolver el resultado, y lanza `ValueError` si se viola.

Así cada fila queda a menos de 0,01 USD de su valor exacto (criterio de la sección 2) y la suma por componente cumple RNF-02 sin tolerancia en contra. Esta regla **reemplaza** el «`ROUND_HALF_UP` por fila» del contrato de la EG-21. `redondear_usd` sigue siendo la función de redondeo del contrato, pero se aplica a la suma.

**Incidencias como datos.** `liquidar_pais` devuelve `ResultadoLiquidacion` con `filas` e `incidentes`. Cada `Incidente` indica:
- el tipo: `territorio_excluido` (RN-08) o `sin_condicion_vigente`;
- la reproducción, el titular, la pista, la fecha, el país de reproducción y el contrato.

La función no escribe nada: quien orquesta (EG-24, EG-37) decide dónde guardarlos. Una reproducción con incidente **cuenta en el denominador** y queda en una fila al 0 %. Paga 0 y su parte de la bolsa no se reparte entre otros titulares. Una fila con valor exacto 0 nunca recibe un centavo del reparto.

## 5. Consecuencias

- **Positivas:**
  - Un sello puede reconstruir qué vio en cada corrida, porque nada se borra (RF-09, CA-07).
  - El mismo mecanismo cubre los datos tardíos de la EG-22, las liberaciones de fraude de ADR-0005 y las correcciones manuales.
  - RNF-02 se cumple por construcción, no por casualidad del redondeo.
  - La lógica es pura, así que la EG-37 puede reutilizarla tal cual por país y componente, y las incidencias se prueban sin base de datos.
- **Negativas / lo que aceptamos:**
  - **Un ajuste se paga con la bolsa del mes en que se liquida**, no con la de su mes real. Ese mes, la reproducción tardía diluye un poco la participación de los demás titulares, y en su mes real hubo una reproducción menos en el denominador. Lo aceptamos porque la alternativa (3.1-C) cambiaría lo que cobraron todos los titulares de un mes cerrado. Además, el volumen de ajustes es pequeño frente al del mes (solo lo offline sincronizado tarde y las cuentas liberadas).
  - Una fila puede diferir en 0,01 USD de su `ROUND_HALF_UP` individual. La suma por componente nunca supera la bolsa.
  - Re-liquidar un mes ya pagado cambia lo que muestra la API, pero no genera un «ajuste negativo». Conciliar pagos ya hechos queda fuera del alcance (no hay una tabla de pagos a titulares).
  - El comentario de `regalia_usd` en el DDL 003 y el docstring de `FilaReporte` todavía dicen «`ROUND_HALF_UP` por fila». Se actualizan cuando se toque ese contrato; la regla vigente es la de este ADR.
- **Riesgos y mitigación:**
  - *Spark (EG-37) redondea por su cuenta y diverge.* Mitigación: la EG-37 llama a la misma función por grupo (país, componente) en lugar de reimplementarla, y compara sus totales con los de la EG-24 sobre la misma muestra.
  - *Una corrida se publica a medias.* Mitigación: `publicada_en` NULL hasta terminar (DDL 003); la API nunca muestra una liquidación sin publicar.
  - *Los incidentes se pierden porque nadie los guarda.* Mitigación: la EG-24 define dónde se persisten. Mientras tanto, `ResultadoLiquidacion.incidentes` es parte del resultado y no se puede ignorar sin descartarlo explícitamente.
  - *Una reproducción de un mes anterior liquidada dentro de un mes posterior.* Cubierto: el % por fecha, por las pruebas del cambio de % a mitad de mes; el caso completo del ajuste (EG-22 + EG-23), por `tests/esqueleto/test_pipeline_puro.py::test_ajuste_offline_de_agosto_se_liquida_en_septiembre` (EG-24).

## 6. Cómo sabremos que funciona

En `tests/reglas/test_liquidacion.py` (58 pruebas, puras):

- **Redondeo (RNF-02):**
  - `test_residuos_redondeo_por_fila_se_pasaria_pero_el_reparto_no` comprueba que `ROUND_HALF_UP` por fila daría 100,02, mientras que el mayor residuo da 33,33 + 33,34 + 33,34 = **100,01** y la misma salida con la entrada invertida.
  - `test_siete_titulares_reparten_centavos_sin_perder_ni_crear` comprueba que 52 / 7 da 6 × 7,43 + 7,42 = 52,00.
  - `test_un_solo_titular_al_100_recibe_la_bolsa_redondeada`.
- **Invariantes:** `test_invariantes_con_muchos_casos_aleatorios` genera 300 casos con semilla fija, hasta 40 titulares, % arbitrarios y exclusiones. Comprueba que la suma por componente y la total no superan la bolsa en más de 0,01, que cada fila queda a < 0,01 de su valor exacto, que una fila al 0 % nunca recibe un centavo y que todas las reproducciones aparecen en alguna fila. `test_verificar_invariantes_detecta_una_suma_que_se_pasa` comprueba que la verificación detecta una suma excedida.
- **% por fecha (RN-07):**
  - `test_limite_del_cambio_de_porcentaje` cubre los límites inclusivos y la hora de Bogotá frente a UTC.
  - `test_cambio_a_mitad_de_mes_una_fila_por_porcentaje` comprueba que se generan dos filas, de 104,00 y 62,40.
- **Incidentes:**
  - `test_territorio_excluido_paga_cero_y_devuelve_incidente`: fila al 0 %, la reproducción cuenta en el denominador y se devuelve el incidente con su contrato.
  - `test_sin_condicion_vigente_paga_cero_y_devuelve_incidente`.
- **Append-only:** `tests/api_titulares/test_services.py` (EG-21) comprueba contra PostgreSQL que la API muestra solo la última liquidación publicada de cada mes.
- **De punta a punta (EG-24):** `tests/esqueleto/test_calculo_a_mano.py` liquida 100 eventos simulados, compara cada fila con el cálculo a mano (± 0,01) y comprueba que una segunda corrida crea otra liquidación sin tocar la primera.

## 7. Fuentes

- Enunciado del proyecto: RF-09, CA-07, RNF-02, RN-04, RN-07, RN-08.
- Supuestos de negocio: [ambiguedades-rn.md](../analisis/ambiguedades-rn.md) (Q3, Q4).
- [ADR-0002](0002-zona-horaria-dia-mes.md) (UTC), [ADR-0005](0005-umbrales-granjas.md) (exclusión y liberación), [ADR-0008](0008-pais-bolsa-dos-componentes.md) (país y componentes de la bolsa).
- Contrato del reporte: [api-titulares.md](../servicios/api-titulares.md#contrato-para-la-eg-23--eg-37) y `db/ddl/003_reportes_regalias.sql`.
- EG-22: [atribucion-offline.md](../datos/atribucion-offline.md).
- Python `decimal` (modos de redondeo y `quantize`): https://docs.python.org/3/library/decimal.html
- Método del mayor residuo (Hamilton): https://en.wikipedia.org/wiki/Largest_remainders_method


---

## English — Decision summary

**Accepted (October 13, 2026; EG-23).** Published monthly settlements are **append-only**: corrections create a new settlement version and retain prior published versions. The reports API selects the latest published version. Late offline plays and released fraud-review records are included as adjustments in the next eligible settlement, paid from that settlement month's pool, but contract percentage follows the **original playback date**. Monetary distribution uses exact Decimal calculations and **largest-remainder cent allocation** by country and component, preserving component totals.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
