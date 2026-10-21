# ADR-0008 · La bolsa la define el país de facturación y se divide en dos componentes con denominadores separados

| Campo | Valor |
|---|---|
| Estado | Aceptado |
| Fecha | 2026-10-13 |
| Historia que lo origina | HU 14 · EG-23 |
| Responsable | Andrea Zárate y María Clara Manjarrés |
| Revisó | Joshua — aprobado el 2026-10-13, validado en la práctica por el esqueleto de la EG-24 (PR #25) |
| Referencias | RN-05, RN-06, RN-08, RN-10, RNF-02, EG-11 Q5 / Q6 / Q7 / Q8, ADR-0002, ADR-0007 |

## 1. Contexto

RN-05 define una **bolsa por país** con el 52 % de la suscripción neta y el 45 % de los ingresos publicitarios. RN-06 reparte esa bolsa entre los titulares según su participación en las reproducciones válidas del país, multiplicada por su % contractual. El enunciado deja dos preguntas abiertas, que mueven directamente el dinero de cada sello:

1. **¿De qué país es una reproducción?** F3 guarda el país de facturación de cada cuenta, y F2 trae el país desde el que se reproduce. No siempre coinciden: alguien que viaja o un miembro de una familia que vive en otro país. RN-10 agrega el plan familiar: **un solo pago** del titular de la familia cubre a todos los miembros (EG-11 Q6).
2. **¿Las reproducciones del plan gratuito entran al denominador de la suscripción?** Si la bolsa es única, un titular con mucha audiencia gratuita se lleva dinero que pagaron los usuarios de planes pagos, y al revés (EG-11 Q8).

La implementación vive en `src/sonoraplay/reglas/liquidacion.py`, y las fracciones de la bolsa en `ReglasLiquidacionConfig` (`config.py`): `fraccion_suscripcion = 0.52` y `fraccion_publicidad = 0.45`, en `Decimal`. El contrato de salida (EG-21, DDL 003) ya tiene las columnas `pais` (país de facturación) y `componente` (`suscripcion` | `publicidad`).

## 2. Qué debe cumplir la decisión

- **Negocio:** RN-05 (bolsa por país: 52 % de la suscripción neta, 45 % de la publicidad). Q5: la suscripción neta es la suma de `pagos.monto_usd` con `estado = 'aprobado'`.
- **Negocio:** RN-06 (regalía = bolsa × participación × % contractual) y Q7 (condición territorial solo si el contrato la define).
- **Negocio:** RN-10 (el pago familiar entra **una sola vez**) y Q6 (país de facturación de la familia).
- **Negocio:** RN-08: la exclusión territorial depende del país **desde donde se escucha**, así que ese dato no se puede perder.
- **Requisito:** RNF-02: la suma por país no supera la bolsa (± 0,01 USD). Para eso, los ingresos y las reproducciones de cada bolsa deben pertenecer al mismo país, porque si no, el reparto no es una fracción de esa bolsa.
- **Requisito:** RF-05 y el contrato de la EG-21: el reporte se publica por país y componente.
- **Costo:** ninguno adicional: son funciones puras dentro del job de liquidación (EG-24, EG-37).
- **Equipo:** si el docente contesta distinto Q6 o Q8, el cambio debe quedar en un solo módulo y en `config.py`.

## 3. Opciones consideradas

### 3.1 País que define la bolsa

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · **País de facturación** (Q6) | El ingreso se cobra en ese país: numerador y denominador quedan en la misma bolsa (RNF-02). El pago familiar va completo a un solo país (RN-10). Es estable durante el mes y no depende de VPN ni de viajes | Las reproducciones de una cuenta colombiana escuchadas en México pagan con la bolsa de Colombia. La analítica de consumo por país (F2) difiere del reporte de regalías | 0 |
| B · País de reproducción | Refleja dónde se escucha la música | Hay reproducciones en un país sin ingreso correspondiente: un viajero diluye la bolsa del país visitado, que no recibió su pago. El pago familiar tendría que partirse entre países con una regla inventada. El país de reproducción puede venir nulo en F2 | 0 |

### 3.2 Forma de la bolsa

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · Bolsa única (fórmula literal de RN-05 / RN-06) | Una sola participación por titular y país; es la lectura literal del enunciado | El dinero de los planes pagos se reparte también por reproducciones gratuitas, y el de la publicidad por reproducciones pagas. El resultado depende de la mezcla de audiencias, no de quién generó cada ingreso | 0 |
| B · **Dos componentes con denominadores separados** (Q8) | Cada ingreso se reparte entre las reproducciones que lo generaron: la suscripción entre las de planes pagos y la publicidad entre las del plan gratuito. Cuando la participación es igual en los dos componentes, da lo mismo que A | Se aparta de la fórmula literal; hay que confirmarlo con el docente. El reporte tiene dos filas por titular y país | 0 |

**Ejemplo (criterio 1 de la EG-23).** En Colombia, en septiembre de 2026, hay 100.000 USD de suscripción neta y 20.000 USD de publicidad. La bolsa queda en **52.000 USD** de suscripción y **9.000 USD** de publicidad (61.000 en total). Un titular tiene el 5 % de las reproducciones pagas, el 10 % de las gratuitas y un contrato del 80 %:

| Fórmula | Cálculo | Regalía |
|---|---|---|
| B · dos componentes | 52.000 × 5 % × 80 % + 9.000 × 10 % × 80 % = 2.080 + 720 | **2.800,00 USD** |
| B con 5 % en los dos componentes (cruce) | (52.000 + 9.000) × 5 % × 80 % | **2.440,00 USD** |
| A · bolsa única con los volúmenes de la prueba (100 pagas y 100 gratuitas: 15 de 200 = 7,5 %) | 61.000 × 7,5 % × 80 % | 3.660,00 USD |

El cruce muestra que B es una generalización de A: si el titular tiene la misma participación en las dos audiencias, las dos fórmulas coinciden (2.440). La diferencia aparece solo cuando sus audiencias pagas y gratuitas pesan distinto. En ese caso, con A, sus 10 reproducciones gratuitas le harían cobrar parte de los 52.000 USD que pagaron los suscriptores.

## 4. Decisión

**Elegimos 3.1-A y 3.2-B.**

**País de la bolsa = país de facturación (Q6, RN-10).**

- `paises_facturacion` asigna a cada usuario su país de bolsa. Un **miembro de familia hereda el país del titular de la familia**, aunque el suyo sea otro.
- Un país de facturación nulo es un defecto de F3 que se depura en Silver. Aquí lanza `ValueError` en vez de inventar un país.
- `suscripcion_neta_por_pais` suma una sola vez cada pago aprobado (Q5). El pago familiar lo hace solo el titular, así que entra **una vez** en la bolsa de su país y se reparte entre las reproducciones de todos los miembros.
- `liquidar_pais` solo cuenta las reproducciones cuyo `pais_facturacion` es el de la bolsa.
- El **país de reproducción** se conserva solo para RN-08 (exclusión territorial) y Q7 (condición territorial). La precedencia es exclusión > condición territorial > general, igual que en `api_contratos.services.elegir_condicion`.

**Bolsa de dos componentes (Q8).**

- `calcular_bolsa`:
  - suscripción = 52 % × suscripción neta;
  - publicidad = 45 % × ingresos publicitarios.
- La publicidad se convierte a USD con `convertir_a_usd`, que exige la tasa del **último día del mes** y no redondea.
- Cada componente se reparte por sus propias reproducciones válidas:
  - suscripción, por las de planes pagos (individual, familiar, estudiante);
  - publicidad, por las del plan gratuito.
- Regalía del titular en el país = (componente de suscripción × participación paga + componente de publicidad × participación gratuita) × % del contrato. Se publica una fila por (titular, componente, %) y el redondeo sigue [ADR-0007](0007-cierre-mes-ajustes-reliquidacion.md).

Es la única combinación en la que cada ingreso se reparte entre las reproducciones que lo generaron y en el país donde se cobró (criterios RN-05, RN-10 y RNF-02 de la sección 2).

> **Pendiente de confirmar con el docente.** Q8 se aparta de la fórmula literal de RN-05 / RN-06 (bolsa única). Es el supuesto con mayor impacto en dinero de EG-11 y el primero que hay que validar. Si el docente pide la bolsa única, se cambia `liquidar_pais` para usar un solo denominador con las reproducciones de los dos componentes, y este ADR pasa a *Reemplazado*. El cálculo de la bolsa, el país de facturación y el redondeo no cambian.

## 5. Consecuencias

- **Positivas:**
  - Los ingresos y las reproducciones de cada bolsa son del mismo país, así que RNF-02 se puede verificar por país.
  - El pago familiar nunca se cuenta dos veces.
  - Un titular cobra de cada ingreso según la audiencia que lo generó.
  - El reporte de la EG-21 ya tiene `pais` y `componente`, así que no hay cambios en el DDL.
- **Negativas / lo que aceptamos:**
  - El reporte de regalías por país no coincide con la analítica de consumo por país. Una cuenta colombiana que escucha en México aparece en la bolsa de Colombia.
  - Un miembro de familia que vive en otro país se paga con la bolsa del país del titular de la familia (Q6).
  - Una reproducción de un territorio excluido **cuenta en el denominador** de la bolsa del país de facturación y paga 0 (ADR-0007). Su parte de la bolsa no se reparte a otros titulares.
  - Si un componente no tiene reproducciones en un país, ese componente no se reparte. Por ejemplo, no se paga publicidad si nadie del plan gratuito escuchó.
- **Riesgos y mitigación:**
  - *El docente responde distinto a Q8.* Mitigación: el cambio queda en `liquidar_pais` y las pruebas de `_caso_colombia` muestran las dos cifras. La nota de la sección 4 dice qué cambiar.
  - *País de facturación nulo o mal escrito en F3.* Mitigación: `paises_facturacion` falla en lugar de adivinar, y Silver (EG-35) depura el dato antes de liquidar.
  - *Spark (EG-37) aplica otra regla de país.* Mitigación: la EG-37 reutiliza `paises_facturacion` y `liquidar_pais`. El contrato `FilaReporte` documenta que `pais` es el de facturación.

## 6. Cómo sabremos que funciona

En `tests/reglas/test_liquidacion.py`:

- **Dos componentes (Q8):**
  - `test_bolsa_colombia_dos_componentes`: 52.000 + 9.000 = 61.000.
  - `test_criterio_1_colombia_2800`: 2.080 + 720 = **2.800,00**, sin incidentes.
  - `test_cruce_bolsa_unica_2440`: **2.440,00**.
  - `test_denominadores_separados`: 990 reproducciones gratuitas no cambian la regalía de suscripción.
- **Familias y país (Q5, Q6, RN-10):**
  - `test_familia_un_pago_repartido_entre_todos_los_miembros`:
    - los miembros heredan el país del titular, también el miembro con país nulo;
    - un pago rechazado no entra;
    - el pago familiar se cuenta una sola vez (30,00 USD → 15,60 USD de componente);
    - las 6 reproducciones de la familia van a Colombia, incluidas las escuchadas en México.
  - `test_familia_con_titular_sin_pais_lanza_error`.
  - `test_solo_cuenta_las_reproducciones_del_pais_de_la_bolsa`.
- **Moneda:**
  - `test_conversion_con_tasa_de_cierre_de_mes`;
  - `test_conversion_no_redondea_antes_de_tiempo`;
  - `test_conversion_rechaza_tasa_de_otra_fecha_o_moneda`;
  - `test_ultimo_dia_del_mes`, con un año bisiesto.
- **Precedencia (RN-08, Q7):** `test_paridad_con_elegir_condicion` (20 combinaciones de país y día) comprueba que la liquidación elige la misma condición que la API de contratos (EG-20).
- **De punta a punta (EG-24):** `tests/esqueleto/test_calculo_a_mano.py::test_regalia_coincide_con_el_calculo_a_mano` liquida 100 eventos simulados contra PostgreSQL y recalcula a mano la bolsa del país de facturación (52 % de los pagos aprobados + 45 % de la publicidad), con un denominador por componente (± 0,01).
- **Cuando el docente responda Q8:** se actualiza [ambiguedades-rn.md](../analisis/ambiguedades-rn.md) y, si cambia, este ADR.

## 7. Fuentes

- Enunciado del proyecto: RN-05, RN-06, RN-08, RN-10, RNF-02.
- Supuestos de negocio: [ambiguedades-rn.md](../analisis/ambiguedades-rn.md) (Q5, Q6, Q7, Q8).
- Contrato del reporte: [api-titulares.md](../servicios/api-titulares.md#contrato-para-la-eg-23--eg-37) y `db/ddl/003_reportes_regalias.sql`.
- [ADR-0002](0002-zona-horaria-dia-mes.md) (UTC), [ADR-0007](0007-cierre-mes-ajustes-reliquidacion.md) (cierre, ajustes y redondeo).
- ISO 3166-1 alfa-2 (códigos de país): https://www.iso.org/iso-3166-country-codes.html
- Python `decimal`: https://docs.python.org/3/library/decimal.html


---

## English — Decision summary

**Accepted (October 13, 2026; EG-23).** The revenue pool country is the **F3 billing country**, not playback country; family members inherit the family account holder's billing country. A missing billing country is a data-quality error, not a reason to invent a country. Each approved subscription payment counts once. The pool has **two components**: 52% of net subscription revenue and 45% of advertising revenue, with separate eligible-play denominators (paid-plan plays versus free-plan plays). Advertising revenue is converted to USD using the monthly closing exchange rate; territorial exclusions still use playback country.

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
