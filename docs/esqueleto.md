# Esqueleto local de punta a punta (EG-24)

El esqueleto demuestra que las piezas del Sprint 2 encajan antes de llevarlas a Spark y AWS. Con un solo comando, 100 eventos simulados pasan por las reglas de validez y por la liquidación de un país, y quedan en `reporte_regalias`. Un sello consulta su regalía en la API con su token y recibe el ID de la liquidación y las reproducciones que la respaldan (RNF-03).

No reimplementa ninguna regla: solo une las que ya existen.

- Código: `src/sonoraplay/esqueleto/` (`pipeline.py` y `__main__.py`).
- Pruebas: `tests/esqueleto/`.
- Docker: servicio `esqueleto` con el perfil `esqueleto` (`docker/esqueleto.Dockerfile`).

## Qué demuestra

| Criterio de la EG-24 | Cómo se cumple |
|---|---|
| 1 · Un solo comando lleva 100 eventos por la validez y la liquidación y los carga en la base | `docker compose --profile esqueleto up --build` levanta postgres → seed → simulador → esqueleto y las APIs |
| 2 · Un sello consulta su regalía con su token | `GET /me/reportes` de la API de sellos (EG-21) lee la liquidación recién publicada |
| 3 · La regalía coincide con un cálculo a mano (± 0,01 USD) | `tests/esqueleto/test_calculo_a_mano.py` recalcula la bolsa, el % y la fórmula sin llamar a `liquidar_pais` |
| 4 · La regalía trae el ID de liquidación y las reproducciones (RNF-03) | `liquidacion_id` y `reproducciones_validas` en cada fila y en los totales de la respuesta |
| 5 · Corre en otra máquina siguiendo solo el README | Sección «Esqueleto de punta a punta (EG-24)» del README |

## Flujo

```
eventos_f2.jsonl ─► esquema F2 ─► reconstruir() ─► atribuir_reproduccion() ─► aplicar_tope_diario()
  (simulador)        (EG-15)      reloj corregido   RN-04: mes de liquidación    RN-01 y RN-02
                                  (EG-19, EG-22)    = período
                                                                                      │ pagables
F1 catalogo_f1.parquet ── pista → titular ────────────────────────────────────────────┤
F3 PostgreSQL ─────────── país de facturación (Q6, RN-10), plan vigente → componente (Q8)
F4 PostgreSQL ─────────── condiciones de las pistas (RN-07, RN-08, Q7) ─────────────────┤
F3 pagos del mes ─────── suscripción neta (Q5) ─┐                                       │
--publicidad-usd ─────── publicidad (sin F5) ───┴► calcular_bolsa() ─► liquidar_pais() ─► verificar_invariantes()
                                                                               │
                         liquidaciones + reporte_regalias (una transacción, ADR-0007) ◄─┘
                                                                               │
                                              API de sellos: GET /me/reportes ◄┘
```

1. **Eventos.** Lee el JSON Lines del simulador (`/datos/procesados/eventos_f2.jsonl` en Docker, `data/processed/eventos_f2.jsonl` en local) y valida cada evento contra `schemas/f2_evento.schema.json`. Un evento inválido detiene la corrida e indica la línea.
2. **Reproducciones.**
   - `reconstruir()` deduplica, agrupa por sesión, corrige el reloj (EG-22) y arma los tramos.
   - `atribuir_reproduccion()` (RN-04) da el mes de liquidación. Solo siguen las de **2026-09** (`--periodo`), que es el mes de `SimuladorConfig.fecha_base`, incluidos los ajustes offline de meses anteriores.
3. **Validez.** `aplicar_tope_diario()` con `ReglasValidezConfig` aplica RN-01 (30 s continuos) y RN-02 (10 por pista, usuario y día UTC). Del simulador:
   - el escenario A (29 s) y el C (pausa) quedan fuera;
   - de las 11 del escenario D, la 11.ª queda fuera por el tope.
4. **F1, F3 y F4.**
   - Pista → titular, desde `catalogo_f1.parquet`.
   - País de facturación con `paises_facturacion()`: un miembro de familia usa el país del titular de su familia (Q6, RN-10).
   - Plan vigente en la fecha UTC de la reproducción: el plan gratuito va al componente de **publicidad**; cualquier plan pago, al de **suscripción** (Q8). Un miembro de familia no tiene suscripción propia y usa la de su titular. La vigencia es `[fecha_inicio, fecha_fin)`: el día de un cambio de plan ya cuenta el plan nuevo.
   - Condiciones F4 de las pistas involucradas: se leen **directamente de PostgreSQL** (`contratos` + `exclusiones_territoriales`), no por la API HTTP de contratos (seguimiento de rendimiento de la EG-20).
5. **Bolsa.**
   - Suscripción: 52 % de los pagos **aprobados** del mes del país (Q5). Cada pago familiar cuenta una vez, en el país del titular.
   - Publicidad: 45 % de `--publicidad-usd` (valor provisional, ver abajo).
6. **País.** `--pais`. Si no se indica, el país con más reproducciones pagables; un empate lo gana el primero en orden alfabético.
7. **Liquidación.** `calcular_bolsa()` → `liquidar_pais()` → `verificar_invariantes()`. Esto incluye el % vigente por fecha (RN-07), la condición territorial (Q7), la exclusión con incidente (RN-08), denominadores separados por componente y el reparto al centavo por mayor residuo (RNF-02, ADR-0007).
8. **Carga append-only (ADR-0007), en una transacción.**
   1. Inserta una fila en `liquidaciones` con `publicada_en` NULL.
   2. Inserta las `FilaReporte` en `reporte_regalias`.
   3. Pone `publicada_en`.

   Volver a correr el esqueleto crea una liquidación **nueva**. La API muestra la última publicada del mes y la anterior nunca se modifica. Si algo falla, no queda nada a medias.
9. **Resumen en consola.** Imprime:
   - el ID de la liquidación, el país y la bolsa por componente;
   - las reproducciones descartadas por motivo y las pagables por país;
   - las filas por titular y los incidentes;
   - el titular con mayor regalía, con el comando para emitir su token y el `curl` de la consulta.

## Reglas que aplica

| Regla | Dónde |
|---|---|
| RN-01 · 30 s continuos | `reglas/validez.py` (EG-17) |
| RN-02 · tope de 10 por pista, usuario y día UTC | `reglas/validez.py` (EG-17) |
| RN-04 · atribución offline y mes de liquidación | `reglas/atribucion.py` (EG-22) |
| RN-05 / RN-06 · bolsa por país y % contractual | `reglas/liquidacion.py` (EG-23) |
| RN-07 · % vigente en la fecha UTC | `porcentaje_aplicable` (EG-23) |
| RN-08 · territorio excluido → 0 % e incidente | `porcentaje_aplicable` (EG-23) |
| RN-10 · un pago por familia | `paises_facturacion` y `suscripcion_neta_por_pais` (EG-23) |
| Q6 · país de la bolsa = país de facturación | `paises_facturacion` (ADR-0008) |
| Q8 · bolsa de dos componentes | `componente_de_plan` y `calcular_bolsa` (ADR-0008) |
| RNF-02 · suma ≤ bolsa ± 0,01 USD | `_repartir_centavos` y `verificar_invariantes` (ADR-0007) |

## Valores provisionales y lo que queda fuera

- **Publicidad sin F5.** Los ingresos publicitarios llegan con la EG-30 (Sprint 3). Mientras tanto se pasan con `--publicidad-usd`, que vale **20.000 USD** por defecto (en Docker, `ESQUELETO_PUBLICIDAD_USD` en `.env`). Ya están en USD, como F3, así que no hay conversión de moneda. La cifra **no es real**: solo sirve para ejercitar el componente de publicidad.
- **Sin fraude (RN-03).** El simulador mínimo no genera granjas (llegan con la EG-51), así que el esqueleto no aplica `reglas/fraude.py`.
- **Incidentes sin tabla.** Los incidentes de RN-08 se imprimen en el resumen, pero todavía no hay tabla donde guardarlos.
- **País de facturación nulo.** Es un defecto que inyecta el seed F3 y que depura Silver (EG-35). El esqueleto no inventa un país: deja fuera esas reproducciones y esos pagos y los cuenta en el resumen (`sin_pais_facturacion`, «Pagos fuera de la bolsa»).
- **Sin plan vigente.** Una reproducción de un usuario sin suscripción vigente, ni propia ni de su familia, queda fuera y se cuenta (`sin_plan_vigente`). Desde que el seed F3 da de baja a los miembros junto con su familia, todo usuario activo tiene plan, y con los datos del simulador este conteo es 0.
- **Un país por mes.** `liquidaciones` no tiene columna `pais`, y la API muestra la última liquidación publicada **del mes**. Si se liquidan dos países del mismo mes en corridas separadas, solo se ve el último. El esqueleto liquida un solo país; la EG-37 escribirá todos los países en una sola liquidación.

## Cómo correrlo

**Con Docker (un solo comando).** Con `.env` preparado como indica el README:

```bash
docker compose --profile esqueleto up --build
```

El resumen sale en el log de `sonoraplay-esqueleto`, que termina con código 0. `postgres` y las APIs siguen en pie para consultar. Para correrlo otra vez, o con otro país o monto de publicidad:

```bash
docker compose --profile esqueleto run --rm esqueleto --pais CO --publicidad-usd 15000
```

**En local** (con PostgreSQL arriba y el catálogo, F3, F4 y el simulador ya corridos; ver la sección del simulador en el README):

```bash
uv run --env-file .env python -m sonoraplay.esqueleto
uv run --env-file .env python -m sonoraplay.esqueleto --periodo 2026-09 --pais CO --publicidad-usd 20000
```

**Pruebas:**

```bash
uv run --env-file .env python -m pytest tests/esqueleto -v
```

## Evidencia: corrida desde cero (20 oct 2026) / Run from scratch (Oct 20, 2026)

### Español

Corrida en una Mac (Apple Silicon, Docker 29.6.1) con un clon nuevo de `develop` (`cf39c43`), sin imágenes ni volúmenes previos del proyecto. El `.env` salió de `.env.example`; las contraseñas y la clave JWT se generaron en la máquina y no aparecen aquí. `PG_PORT=5433` porque la máquina ya tenía un PostgreSQL en el 5432.

```bash
git clone https://github.com/sonoraplay/main.git && cd main && git checkout develop
cp .env.example .env            # y cambiar POSTGRES_PASSWORD, DATABASE_URL y API_TITULARES_JWT_SECRET
docker compose --profile esqueleto up --build -d
docker compose --profile esqueleto logs esqueleto
```

**Estado final** (`docker compose ps -a`): `seed`, `simulador` y `esqueleto` terminan con `Exited (0)`; `postgres`, `api-contratos` y `api-titulares` quedan `healthy`.

**Resumen del esqueleto** (extracto del log):

```text
== Esqueleto EG-24 · liquidación publicada
ID de liquidación: e0b3730f-72d2-46d8-8cd1-e70be9037ba7
Período: 2026-09   País de facturación: CO
Eventos F2: 100   Reproducciones: 38   Ajustes de meses anteriores: 0
Descartadas: duracion_insuficiente=4, tope_diario=1
Pagables por país: AR=6, CL=4, CO=13, MX=2, PE=8
Bolsa (USD): suscripción 1819.96 · publicidad 9000.00 (PROVISIONAL) · repartido 4926.88
Filas por titular (4 titulares, 4 filas)
Titular con mayor regalía: fb950a36-dd51-59f6-af5f-200916631894 (2340.00 USD)
```

**Consulta del sello** con su token (`docker compose exec api-titulares python -m sonoraplay.api_titulares.tokens --titular fb950a36-…`; el token no se publica):

```json
GET /me/reportes?periodo=2026-09  →  HTTP 200
{
  "titular_id": "fb950a36-dd51-59f6-af5f-200916631894",
  "filas": [{ "periodo": "2026-09", "pais": "CO", "componente": "publicidad",
              "reproducciones_validas": 1, "participacion": "0.500000",
              "porcentaje_contractual": "52.00", "regalia_usd": "2340.00",
              "liquidacion_id": "e0b3730f-72d2-46d8-8cd1-e70be9037ba7" }],
  "totales": [{ "periodo": "2026-09", "pais": "CO", "reproducciones_validas": 1,
                "regalia_usd": "2340.00",
                "liquidacion_id": "e0b3730f-72d2-46d8-8cd1-e70be9037ba7" }]
}
```

- Con el token de otro titular (`d3aee405-…`) la misma URL devuelve **solo su fila** (89.35 USD), no la del primero.
- Sin token: `HTTP 401 {"detail": "Falta el token de acceso"}`.

**Re-ejecución (21 oct).** `docker compose --profile esqueleto start` vuelve a correr el esqueleto, que publica una segunda liquidación del mismo período (`302bccfb-0ac3-4574-bf70-4c00eaedad78`). `reporte_regalias` queda con las dos (append-only, 4 filas cada una), y la API devuelve **solo la última**, con el mismo monto (2340.00 USD): la re-liquidación no duplica regalías (ADR-0007). Para reanudar sin publicar otra vez, usa `docker compose start postgres api-contratos api-titulares`.

**Pruebas:** `uv run --env-file .env python -m pytest tests/esqueleto -v` → **23 passed**, incluida `test_calculo_a_mano.py` (criterio 3).

| Criterio | Resultado |
|---|---|
| 1 · Un comando, 100 eventos hasta la base | ✅ 100 eventos, liquidación `e0b3730f…` publicada |
| 2 · El sello consulta con su token | ✅ HTTP 200 con su token; 401 sin token; aislamiento entre sellos |
| 3 · Cálculo a mano (± 0,01 USD) | ✅ `test_calculo_a_mano.py` |
| 4 · ID de liquidación y reproducciones (RNF-03) | ✅ `liquidacion_id` y `reproducciones_validas` en filas y totales |
| 5 · Corre en otra máquina con el README | ✅ clon nuevo, sin imágenes ni volúmenes previos, siguiendo solo el README y esta guía |

### English

Run on a Mac (Apple Silicon, Docker 29.6.1) from a fresh clone of `develop` (`cf39c43`), with no previous project images or volumes. `.env` came from `.env.example`; passwords and the JWT key were generated locally and are not shown. `PG_PORT=5433` because the machine already had PostgreSQL on 5432.

- `docker compose --profile esqueleto up --build -d`: `seed`, `simulador` and `esqueleto` exit 0; `postgres` and both APIs stay healthy.
- The skeleton read **100 F2 events**, built 38 plays (4 too short, 1 over the daily cap), and published settlement `e0b3730f-72d2-46d8-8cd1-e70be9037ba7` for CO, 2026-09, with 4 rows for 4 rights holders.
- `GET /me/reportes?periodo=2026-09` with the top rights holder's token returns HTTP 200 with `liquidacion_id`, `reproducciones_validas: 1` and `regalia_usd: 2340.00`. Another holder's token returns only its own row; no token returns 401.
- `pytest tests/esqueleto`: **23 passed**, including the hand-calculation test.
- Re-run (Oct 21): `docker compose --profile esqueleto start` runs the skeleton again and publishes a second settlement for the same period (`302bccfb…`). Both stay in `reporte_regalias` (append-only), and the API returns **only the latest**, with the same amount: re-settling does not duplicate royalties (ADR-0007). To resume without publishing again, start only `postgres api-contratos api-titulares`.

All five EG-24 acceptance criteria are met (see the table above).

## Seguimientos

- Tabla de incidentes (RN-08) y persistencia desde el esqueleto y la EG-37.
- F5 real (EG-30): reemplazar `--publicidad-usd` por los ingresos publicitarios por país, convertidos con `convertir_a_usd`.
- Fraude en el esqueleto (RN-03) cuando el simulador genere granjas (EG-51).
- País en `liquidaciones`, o una liquidación con todos los países, antes de liquidar más de un país por mes (EG-37, ADR-0007).
