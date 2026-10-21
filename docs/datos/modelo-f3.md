# Modelo F3 · Suscripciones (HU 04 · EG-13)

Fuente F3 de SonoraPlay: base PostgreSQL con usuarios, planes, cuentas familiares, períodos de suscripción y pagos. La leen RN-05 (bolsa por país), RN-09 (churn) y RN-10 (cuenta familiar = un solo ingreso).

## Diagrama ER

```mermaid
erDiagram
    planes ||--o{ suscripciones : "define"
    usuarios ||--o{ suscripciones : "tiene"
    suscripciones ||--o{ pagos : "genera"
    usuarios ||--o| grupos_familiares : "es titular de"
    grupos_familiares ||--|{ miembros_familia : "tiene 2..6"
    usuarios ||--o| miembros_familia : "pertenece a"
    grupos_familiares |o--o{ suscripciones : "cubierto por"

    planes { smallint plan_id PK  text codigo  numeric precio_usd  smallint max_miembros }
    usuarios { uuid usuario_id PK  text email  char pais_facturacion  timestamptz fecha_alta  timestamptz fecha_baja }
    grupos_familiares { uuid grupo_id PK  uuid titular_id FK }
    miembros_familia { uuid grupo_id PK  uuid usuario_id PK  text rol }
    suscripciones { uuid suscripcion_id PK  uuid usuario_id FK  smallint plan_id FK  uuid grupo_id FK  date fecha_inicio  date fecha_fin  text motivo_fin }
    pagos { uuid pago_id PK  uuid suscripcion_id FK  date fecha_pago  numeric monto_usd  text estado }
```

## Cómo leerlo

- Cada usuario tiene uno o más **períodos** de suscripción; solo el último puede estar abierto (`fecha_fin IS NULL`, índice único parcial `ux_suscripcion_activa`).
- Un plan familiar es **una sola suscripción** del titular ligada al grupo → un solo pago por familia (RN-10). Los miembros tienen fila en `usuarios` y en `miembros_familia`, pero no suscripción propia.
- Cuando la familia se da de baja (`cancelacion` o `no_renovacion`), los miembros también: su `fecha_baja` es la del titular, o su `fecha_alta` si se unieron después. Así, todo usuario sin `fecha_baja` tiene una suscripción abierta, propia o de su familia.
- Un cambio de plan cierra el período anterior con `motivo_fin = 'cambio_plan'` (no es churn, RN-09). `cancelacion` y `no_renovacion` sí son churn.
- `seed_defectos` registra cada defecto inyectado para medir después cuántos detecta la calidad de datos.

## Planes (supuestos)

| Plan | plan_id | Precio USD/mes | Máx. miembros | % de slots |
|---|---|---|---|---|
| free | 1 | 0.00 | 1 | 45 % |
| individual | 2 | 5.99 | 1 | 30 % |
| familiar | 3 | 9.99 | 6 | 10 % |
| estudiante | 4 | 2.99 | 1 | 15 % |

## Decisiones de diseño

| Decisión | Elección | Por qué |
|---|---|---|
| Llaves primarias | `uuid5(NAMESPACE, "semilla:entidad:índice")` | Re-ejecutar choca con la misma PK y `ON CONFLICT DO NOTHING` la descarta (idempotencia). |
| Aleatoriedad | Un `random.Random(f"{semilla}:slot:{i}")` por slot | Cambiar volumen o tasa de defectos no desplaza los demás datos; dev es prefijo exacto de completo. |
| Fechas | Referencia fija `2026-09-30` | `now()` rompería el checksum de reproducibilidad. |
| Máx. 6 miembros | Trigger `trg_max_6_miembros` | Un `CHECK` no puede contar filas de la tabla. |
| Defectos | Tabla `seed_defectos` + RNG propio | Trazabilidad y tasa configurable sin alterar el resto. |

## Pregunta abierta para el equipo

¿Un downgrade de plan pago a *free* es churn? RN-09 solo dice que los cambios de plan no lo son. El seed evita la ambigüedad generando solo cambios pago→pago y free→individual.

## Comportamientos a conocer

1. El volumen es un objetivo: la última familia puede sumar hasta 5 usuarios extra.
2. Otra semilla sobre una base cargada agrega un segundo conjunto de datos aparte.
3. Cambiar la tasa de defectos exige base vacía (`docker compose down -v`), porque las filas existentes no se actualizan.


---

## English — F3 subscription model (HU 04 · EG-13)

F3 is a PostgreSQL source containing users, plans, family groups, subscription periods, and payments. It supports RN-05 (country revenue pool), RN-09 (churn), and RN-10 (one family account produces one payment). The ER diagram and table/column identifiers above are shared by both languages.

### Relationships and business rules

- A user can have several historical subscription periods, but only one active period; `ux_suscripcion_activa` enforces this with a partial unique index.
- A family plan belongs to its account holder and has a single subscription and payment. Other family members are users and group members, but do not hold separate subscriptions (RN-10).
- When the family is canceled or not renewed, member termination dates follow the holder's termination date, or the member's joining date if later.
- A plan change closes the previous period with `motivo_fin = 'cambio_plan'` and is **not churn**. Cancellation and non-renewal count as churn (RN-09).
- `seed_defectos` records deliberately injected data-quality defects.

### Assumed plans

| Plan | ID | USD/month | Maximum members | Share of slots |
|---|---:|---:|---:|---:|
| free | 1 | 0.00 | 1 | 45% |
| individual | 2 | 5.99 | 1 | 30% |
| familiar | 3 | 9.99 | 6 | 10% |
| estudiante | 4 | 2.99 | 1 | 15% |

These are **simulation assumptions**, not actual market prices.

### Reproducibility and constraints

- Primary keys use deterministic UUID5 values derived from the seed, entity, and index. `ON CONFLICT DO NOTHING` avoids duplicate inserts on a repeated seed run.
- A separate `random.Random(f"{semilla}:slot:{i}")` per slot prevents changes to other slots when volume or defect rate changes.
- The fixed reference date is `2026-09-30`; using the current time would break reproducibility.
- The `trg_max_6_miembros` trigger enforces the six-member maximum; a row-level `CHECK` cannot count related rows.
- Injected defects use a separate random generator and are recorded in `seed_defectos`.

### Open question and operational limitations

Whether downgrading a paid plan to `free` counts as churn remains unresolved; the seed avoids this case and only generates paid-to-paid and free-to-individual changes. The final family may add up to five extra users beyond the requested volume. A different seed adds another dataset. Changing the defect rate requires a fresh database (`docker compose down -v`) because existing rows are not rewritten.
