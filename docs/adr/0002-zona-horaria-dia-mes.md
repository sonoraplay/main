# ADR-0002 · Usar UTC para definir el "día" y el "mes" de las reglas de negocio

| Campo | Valor |
|---|---|
| Estado | Aceptado (supuesto de EG-11; se revisa si el docente responde distinto) |
| Fecha | 2026-10-02 |
| Historia que lo origina | HU 02 · EG-11 |
| Responsable | María Clara |
| Revisó | María Clara — aprobado el 2026-10-02 |
| Referencias | RN-02, RN-04, RN-05, RN-07, CA-02, CA-04, F2, F6 |

## 1. Contexto

Varias reglas dependen de en qué día o mes cae una reproducción:

- **RN-02:** máximo 10 reproducciones válidas por pista, usuario y **día**.
- **RN-04:** una reproducción offline se atribuye a su **mes** real si sincroniza antes del día 2 a las 23:59 **UTC**.
- **RN-05:** la bolsa es **mensual** y usa la tasa de cambio del último día del mes.
- **RN-07:** el % contractual vigente depende de la **fecha** de la reproducción.

SonoraPlay opera en varios países de Latinoamérica con zonas horarias distintas (de UTC-3 a UTC-6). Una escucha a las 22:00 en Bogotá el 31 de enero ya es 1 de febrero en UTC. Si cada regla usa una zona distinta, la misma reproducción puede caer en meses diferentes según qué cálculo se mire. El enunciado no dice qué zona manda (pregunta Q4 de EG-11).

## 2. Qué debe cumplir la decisión

- **Negocio:** RN-04 ya fija su corte en UTC; las demás reglas deben ser coherentes con ese corte para que la atribución offline y la liquidación usen el mismo calendario.
- **Requisito:** RNF-03 (trazabilidad): una reproducción debe pertenecer a un solo mes de liquidación, sin ambigüedad.
- **Requisito:** RNF-01 (liquidación < 1 h): particionar el Data Lake por año/mes sin tener que convertir por país.
- **Costo:** ninguno adicional; la decisión solo afecta código y datos.
- **Equipo:** las funciones puras de EG-17 ya se escribieron asumiendo UTC.

## 3. Opciones consideradas

| Opción | A favor | En contra | Costo aprox. USD/mes |
|---|---|---|---|
| A · UTC para todo | Coherente con RN-04; un único calendario; particiones simples; sin problemas de horario de verano | El "día" del usuario no coincide con su día local (una escucha a las 20:00 en Colombia cuenta para el día siguiente) | 0 |
| B · Zona horaria del país de reproducción | Refleja el día real del oyente | Contradice el corte UTC de RN-04; una misma liquidación mezcla calendarios; requiere tabla de zonas por país y manejo de cambios de horario | 0 |
| C · Zona horaria del país de facturación | Alinea con la bolsa por país | Mismas desventajas que B; un usuario que viaja tiene días "desplazados" | 0 |

## 4. Decisión

**Elegimos la opción A (UTC)** porque RN-04 ya define su corte en UTC, garantiza que cada reproducción pertenezca a un solo día y un solo mes (RNF-03) y simplifica el particionamiento del Data Lake (RNF-01).

Reglas de implementación:

1. Todos los timestamps de F2 se envían y almacenan en UTC (ISO 8601 con `Z`).
2. El timestamp corregido del dispositivo (RN-04, relojes desfasados) también se expresa en UTC.
3. `día = fecha UTC` y `mes = año-mes UTC` en RN-02, RN-04, RN-05 y RN-07.
4. La tasa de cambio de F6 se toma del último día del mes UTC.
5. La zona horaria se configura en `config.py` (`ZONA_HORARIA_REGLAS = "UTC"`) para poder cambiarla si el docente responde distinto.

## 5. Consecuencias

- **Positivas:** un solo calendario para todas las reglas; pruebas más simples; sin errores de horario de verano.
- **Negativas / lo que aceptamos:** para un oyente en Colombia (UTC-5) el "día" de RN-02 va de 19:00 a 18:59 hora local. No afecta el dinero porque el límite es el mismo para todos.
- **Riesgos y mitigación:** si el docente pide hora local, se cambia el valor en `config.py`, se ajustan las pruebas de EG-17 y EG-22 y este ADR pasa a *Reemplazado*.

## 6. Cómo sabremos que funciona

- Prueba de EG-17: 11 reproducciones entre 23:50 y 23:59 UTC → solo 10 válidas; 6 a las 23:59 UTC y 5 a las 00:01 UTC del día siguiente → las 11 válidas.
- Prueba de EG-22 (CA-04): escucha el 28, sincroniza el día 2 a las 23:59 UTC → mes correcto; a las 00:00 UTC del día 3 → ajuste del mes siguiente.

## 7. Fuentes

- Python `datetime` — objetos *aware* y `timezone.utc`: https://docs.python.org/3/library/datetime.html
- PostgreSQL — `timestamp with time zone`: https://www.postgresql.org/docs/16/datatype-datetime.html
- Spark SQL — `spark.sql.session.timeZone`: https://spark.apache.org/docs/latest/configuration.html
- ISO 8601 / RFC 3339 para timestamps: https://www.rfc-editor.org/rfc/rfc3339


---

## English — Decision summary

**Accepted working assumption (October 2, 2026; EG-11).** UTC defines the day and month for RN-02, RN-04, RN-05, and RN-07. F2 timestamps use ISO 8601 ending in `Z`; corrected device timestamps also remain UTC. The configuration key is `ZONA_HORARIA_REGLAS = "UTC"`. A local day may begin at a different wall-clock time; instructor clarification could require a replacement ADR. Month-end exchange-rate selection is subject to the separate F6 closing-date policy (ADR-0021).

**Traceability:** The original Spanish sections above remain the full decision record, including context, options, consequences, and acceptance criteria. This English summary does not change the ADR status or introduce a new decision.
