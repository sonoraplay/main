# API de sellos (EG-21)

API **pública**, hecha con FastAPI y SQLModel, con la que cada sello, distribuidora o sociedad de gestión consulta **su propio** reporte de regalías (RF-05): reproducciones válidas, participación en la bolsa, % contractual, regalía en USD e ID de liquidación, por mes y país. Un titular nunca ve datos de otro (RN-11, CA-08).

- **Código:** `src/sonoraplay/api_titulares/`
- **Pruebas:** `tests/api_titulares/`
- **Esquema:** `db/ddl/003_reportes_regalias.sql`. La API solo **lee**; las tablas las llenan la EG-23 y la EG-37 (ver [Contrato para la EG-23 / EG-37](#contrato-para-la-eg-23--eg-37)).
- **Decisión de autenticación:** [ADR-0006](../adr/0006-autenticacion-aislamiento-sellos.md).

## Despliegue y red

Según la [arquitectura v1](../arquitectura/arquitectura-v1.md):

- Es la **única API pública**: el sello llama por **HTTPS** al **ALB**, y el ALB reenvía al servicio (flujo ①–③). El puerto 80 redirige al 443.
- Corre en **ECS Fargate On-Demand** (ARM64, 0,25 vCPU / 0,5 GB) y escucha en el puerto **8000**. Solo acepta tráfico de `sg-alb` (`sg-api-titulares`) y lee RDS.
- El secreto de firma vive en **SSM Parameter Store** (`/sonoraplay/api-titulares/jwt-secret`, SecureString) y ECS lo inyecta como `API_TITULARES_JWT_SECRET` (ADR-0017, EG-40). Nunca está en el repositorio ni en la imagen.
- En local, Docker Compose la publica en el puerto **8001** (`API_TITULARES_PORT`) para no chocar con la API de contratos (8000).

## Capas

| Capa | Archivo | Responsabilidad |
|---|---|---|
| HTTP | `routers/reportes.py`, `routers/salud.py` | Validar la petición y aplicar el aislamiento (403) antes de tocar la base. |
| Autenticación | `auth.py` | Cargar el secreto, emitir y validar el JWT; 401 con `WWW-Authenticate: Bearer`. |
| Reglas | `services.py` | Armar el reporte y los totales por mes y país. `construir_reporte` es pura. |
| Datos | `repositories.py` | Última liquidación publicada de cada mes, siempre filtrada por titular. |
| Modelos | `models.py` | Tablas (espejo del DDL 003) y modelos de respuesta, por separado. |
| Contrato | `src/sonoraplay/reporte_regalias.py` | `FilaReporte`, `Componente` y `redondear_usd`, sin FastAPI. Lo usan la EG-23 y la EG-37. |
| Conexión | `db.py` | Engine perezoso desde `DATABASE_URL` y la dependencia `get_session`. |
| App | `main.py` | `create_app()`; el *lifespan* carga el secreto y la app no arranca sin él. |
| Desarrollo | `tokens.py` | Script que emite un token para pruebas manuales. |

## Autenticación y aislamiento

Cada petición lleva `Authorization: Bearer <token>`. El token es un **JWT HS256** con:

| Claim | Valor |
|---|---|
| `sub` | `titular_id` (UUID) |
| `iss` | `sonoraplay` |
| `aud` | `api-titulares` |
| `iat`, `exp` | Emisión y vencimiento |

El orden de los controles es fijo:

1. **401** si falta el token, si venció, si la firma no coincide, si `iss` o `aud` no son los esperados, si falta un claim, si el algoritmo no es HS256 o si `sub` no es un UUID. Siempre con `WWW-Authenticate: Bearer`.
2. **403** si el `titular_id` del path no es el `sub` del token. El cuerpo es **siempre el mismo**, exista o no el titular pedido, y se decide **sin abrir una sesión de base de datos**: no sirve para averiguar qué titulares existen (CA-08).
3. La consulta filtra siempre por el `sub` del token.

`GET /me/reportes` es la **forma recomendada** para los sellos: el titular sale del token y no hay ningún identificador que manipular.

### Obtener un token en desarrollo

1. Una sola vez, pon un secreto aleatorio en tu `.env`, que no se versiona. Nunca uses el valor de `.env.example`: la app lo rechaza.

   ```bash
   uv run python -c "import secrets; print(secrets.token_urlsafe(48))"
   # en .env:  API_TITULARES_JWT_SECRET=<lo que imprimió>
   ```

2. Emite un token para un titular. El script solo lo imprime, no lo guarda.

   ```bash
   uv run --env-file .env python -m sonoraplay.api_titulares.tokens --titular <uuid> --horas 8
   ```

`--horas` va de 1 a 2160 (90 días). En producción, el token lo emite un integrante del equipo con acceso al parámetro de SSM y se lo entrega al sello por un canal privado (ADR-0006).

## Endpoints

La documentación interactiva está en `/docs`: usa el botón **Authorize** y pega solo el token. El esquema está en `/openapi.json`.

### `GET /health`

Sin autenticación. Hace un `SELECT 1` contra PostgreSQL. Lo usan el `HEALTHCHECK` del contenedor y el *target group* del ALB.

| Status | Cuerpo |
|---|---|
| 200 | `{"status": "ok"}` |
| 503 | `{"detail": "La base de datos no responde"}` |

### `GET /me/reportes` y `GET /titulares/{titular_id}/reportes`

Devuelven el mismo reporte. La segunda ruta exige que `titular_id` sea el del token.

| Parámetro | Dónde | Formato | Obligatorio | Validación |
|---|---|---|---|---|
| `titular_id` | ruta (solo la segunda) | UUID | sí | 422 si no es un UUID; 403 si no es el del token |
| `periodo` | query | `YYYY-MM` | no | 422 si no cumple el formato o el mes no existe |
| `pais` | query | ISO 3166-1 alfa-2 en mayúsculas | no | 422 si no cumple `^[A-Z]{2}$` |

Sin `periodo` se devuelven todos los meses liquidados. De cada mes se muestra solo la **última liquidación publicada**.

**200:**

```http
GET /me/reportes?periodo=2026-09&pais=CO
Authorization: Bearer eyJhbGciOiJIUzI1NiIs...
```

```json
{
  "titular_id": "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa",
  "filas": [
    {
      "periodo": "2026-09",
      "pais": "CO",
      "componente": "suscripcion",
      "reproducciones_validas": 1200,
      "participacion": "0.050000",
      "porcentaje_contractual": "80.00",
      "regalia_usd": "2080.00",
      "liquidacion_id": "09000000-0000-4000-8000-000000000002"
    },
    {
      "periodo": "2026-09",
      "pais": "CO",
      "componente": "publicidad",
      "reproducciones_validas": 900,
      "participacion": "0.100000",
      "porcentaje_contractual": "80.00",
      "regalia_usd": "720.00",
      "liquidacion_id": "09000000-0000-4000-8000-000000000002"
    }
  ],
  "totales": [
    {
      "periodo": "2026-09",
      "pais": "CO",
      "liquidacion_id": "09000000-0000-4000-8000-000000000002",
      "reproducciones_validas": 2100,
      "regalia_usd": "2800.00"
    }
  ]
}
```

- **Los decimales van como string** (`"2800.00"`), no como número JSON. Un número JSON se lee como float y puede perder centavos (RNF-02). `regalia_usd` y `porcentaje_contractual` llevan 2 decimales; `participacion`, 6. Para sumar, el cliente debe usar un tipo decimal, por ejemplo `Decimal` en Python o `decimal.js`.
- `totales` suma las filas de cada mes y país (todos los componentes y porcentajes).
- Un titular sin filas recibe `200` con `filas` y `totales` vacíos.

**401** (sin token, vencido o inválido):

```http
HTTP/1.1 401 Unauthorized
WWW-Authenticate: Bearer

{"detail": "Falta el token de acceso"}      // o "El token venció" / "Token inválido"
```

**403** (token de A, path de otro titular, exista o no):

```http
HTTP/1.1 403 Forbidden

{"detail": "No tiene permiso para consultar este titular"}
```

## Modelo de lectura

```mermaid
erDiagram
    titulares_derechos ||--o{ reporte_regalias : "titular_id"
    liquidaciones ||--o{ reporte_regalias : "liquidacion_id, periodo"
    liquidaciones {
        uuid liquidacion_id PK
        date periodo "primer día del mes"
        timestamptz creada_en
        timestamptz publicada_en "NULL = en proceso"
    }
    reporte_regalias {
        uuid liquidacion_id PK
        uuid titular_id PK
        char2 pais PK
        text componente PK "suscripcion | publicidad"
        numeric porcentaje_contractual PK "0..100"
        date periodo
        int reproducciones_validas
        numeric participacion "0..1"
        numeric regalia_usd
    }
```

- **Re-liquidación (ADR-0007):** liquidar otra vez un mes crea **otra** fila en `liquidaciones`; nada se sobrescribe. La API muestra la de mayor `publicada_en` del mes, para todos los titulares. Si la nueva liquidación ya no incluye a un titular, ese mes no le devuelve filas.
- **Publicación:** una liquidación con `publicada_en` NULL nunca se muestra. Así Spark puede escribir en lotes y publicar al final, sin que un sello vea un reporte a medias.

## Contrato para la EG-23 / EG-37

Esta API define **qué** deben producir las funciones de liquidación (EG-23) y el job de Spark (EG-37). Cambios a este contrato se coordinan con ADR-0007.

### Qué escribir

1. Insertar una fila en `liquidaciones` con `periodo` = primer día del mes (UTC, ADR-0002) y `publicada_en` NULL.
2. Insertar las filas de `reporte_regalias`. En Python, cada fila es un `FilaReporte` (`src/sonoraplay/reporte_regalias.py`), que valida unidades y escala al construirse; `ReporteRegalias.desde_fila(fila, liquidacion_id)` la convierte en la fila de la tabla.
3. Cuando estén todas, poner `publicada_en = now()`. Desde ese momento la API la muestra.

### Columnas

| Columna | Significado | Unidad |
|---|---|---|
| `liquidacion_id` | Corrida de liquidación del mes | UUID |
| `titular_id` | Titular de derechos (FK a `titulares_derechos`) | UUID |
| `periodo` | Mes liquidado: primer día del mes UTC. Debe coincidir con el de la liquidación (FK compuesta) | `date` |
| `pais` | **País de facturación** de la cuenta (Q6, ADR-0008), no el de la reproducción | ISO 3166-1 alfa-2 |
| `componente` | Componente de la bolsa (Q8): `suscripcion` reparte entre reproducciones de planes pagos; `publicidad`, entre las del plan gratuito | texto |
| `reproducciones_validas` | Reproducciones válidas del titular en ese país y componente, después de RN-01, RN-02 y RN-03 | entero ≥ 0 |
| `participacion` | Reproducciones del titular / total de reproducciones válidas del componente en ese país | **de 0 a 1**, 6 decimales |
| `porcentaje_contractual` | % del contrato aplicado (RN-06, RN-07, Q7). 0 si el país está excluido (RN-08) | **de 0 a 100**, 2 decimales (80.00 = 80 %) |
| `regalia_usd` | `bolsa_componente_país × participacion × porcentaje_contractual / 100` | USD, 2 decimales |

### Una fila por cada % del mes

La clave es `(liquidacion_id, titular_id, pais, componente, porcentaje_contractual)`. Si el % de un titular cambió a mitad de mes (RN-07), o si tiene pistas con % distintos, hay **una fila por cada %**. Hay que **agrupar por (titular, país, componente, %)** antes de calcular la participación y la regalía, para que cada fila cumpla la fórmula con un % que existe en el contrato. No se promedian porcentajes.

### Redondeo

- `regalia_usd` lleva 2 decimales y nunca pasa por `float`.
- RNF-02: la suma de `regalia_usd` de **todos** los titulares de un país y componente no puede superar la bolsa de ese componente en ese país ± 0,01 USD. Redondear cada fila por separado con `ROUND_HALF_UP` no lo garantiza: con 3 filas de 33,335 da 3 × 33,34 = 100,02, por encima de una bolsa de 100,005.
- Por eso la EG-23 aplica el **método del mayor residuo** por país y componente, en un solo sitio (`_repartir_centavos` en `src/sonoraplay/reglas/liquidacion.py`). Decisión en [ADR-0007](../adr/0007-cierre-mes-ajustes-reliquidacion.md):
  1. cada fila se trunca al centavo;
  2. los centavos que faltan para llegar a `redondear_usd(suma exacta)` se asignan, de a uno, a las filas con mayor residuo; los empates se rompen por titular;
  3. la suma por componente es exactamente `redondear_usd(suma exacta)`, así que **nunca supera la bolsa** en más de 0,005 USD.
- Consecuencia para quien recalcule: una fila puede diferir en **0,01 USD** de su `ROUND_HALF_UP` individual, pero siempre queda a menos de 0,01 de su valor exacto. Una fila al 0 % (territorio excluido, RN-08) nunca recibe un centavo.
- La participación se guarda con 6 decimales; la regalía se calcula con la participación **sin redondear** y solo se redondea el resultado.

### Ejemplo (criterio 1 de la EG-23)

Titular con contrato del 80 % en Colombia, septiembre de 2026:

| Componente | Bolsa CO (USD) | Participación | % | Cálculo | `regalia_usd` |
|---|---|---|---|---|---|
| suscripcion | 52.000 | 0.050000 | 80.00 | 52.000 × 0,05 × 80 / 100 | **2080.00** |
| publicidad | 9.000 | 0.100000 | 80.00 | 9.000 × 0,10 × 80 / 100 | **720.00** |
| **Total CO** | | | | | **2800.00** |

```python
from datetime import date
from decimal import Decimal
from sonoraplay.reporte_regalias import Componente, FilaReporte, redondear_usd

FilaReporte(
    titular_id=titular,
    periodo=date(2026, 9, 1),
    pais="CO",
    componente=Componente.SUSCRIPCION,
    reproducciones_validas=1200,
    participacion=Decimal("0.05"),
    porcentaje_contractual=Decimal("80"),
    regalia_usd=redondear_usd(Decimal("52000") * Decimal("0.05") * Decimal("80") / 100),
)
```

`tests/api_titulares/test_contrato_reporte.py` tiene este ejemplo como prueba, y `test_http.py` comprueba que la API devuelve el total `"2800.00"`.

## Cómo correrla

### En local (Windows)

Se necesita PostgreSQL con el DDL 003 aplicado y `API_TITULARES_JWT_SECRET` en `.env`:

```bash
docker compose up -d --wait postgres
uv run --env-file .env python -m uvicorn sonoraplay.api_titulares.main:app --port 8001
```

Luego se abre [http://localhost:8001/docs](http://localhost:8001/docs).

**Aplicar el DDL 003 a un volumen que ya existe.** Los scripts de `db/ddl/` solo corren cuando se crea el volumen. Si tu base ya tiene datos, aplícalo a mano; el script es idempotente:

```bash
docker exec -i sonoraplay-postgres psql -U sonora -d sonoraplay < db/ddl/003_reportes_regalias.sql
```

(`docker compose down -v` también lo aplica, pero **borra todos los datos cargados**.)

### En Docker

```bash
docker compose up -d --build api-titulares
curl http://localhost:8001/health
```

- **Imagen:** `docker/api-titulares.Dockerfile`, con la misma convención que la API de contratos: `python:3.12-slim` con uv 0.12.17, `uv sync --frozen --no-dev`, usuario no root y `HEALTHCHECK` contra `/health`.
- **Compose:** recibe `DATABASE_URL` (host `postgres`) y `API_TITULARES_JWT_SECRET` desde `.env`. Si el secreto falta, **solo este contenedor** falla al arrancar, con el motivo en `docker compose logs api-titulares`; PostgreSQL sigue funcionando.
- **Secretos:** `.dockerignore` excluye `.env`, así que el secreto no entra a la imagen.

### Pruebas

```bash
uv run --env-file .env python -m pytest tests/api_titulares -v
```

- `test_aislamiento_ca08.py`: CA-08. A pide B → 403; A pide un UUID inexistente → 403 con el mismo cuerpo exacto; ninguna respuesta filtra datos de B; el 403 se decide sin abrir una sesión de base de datos.
- `test_auth.py`: secreto, emisión y validación de tokens, y el script, sin HTTP.
- `test_services.py`: totales (puro) y última liquidación publicada (contra PostgreSQL).
- `test_contrato_reporte.py`: `FilaReporte`, redondeo y el ejemplo de 2.800 USD.
- `test_http.py`: criterios 1, 3 y 4, arranque sin secreto, `/health` y OpenAPI.

Las pruebas firman los tokens con un secreto **de prueba** puesto con `monkeypatch`; no leen el secreto de `.env`.


---

## English — Rights-holder reports API: technical summary

**Story:** EG-21. **Implementation:** FastAPI + SQLModel under `src/sonoraplay/api_titulares/`; tests under `tests/api_titulares/`; read-only reporting schema in `db/ddl/003_reportes_regalias.sql`. EG-23 and EG-37 are responsible for populating report data. The API must never claim settlement records exist before they are loaded.

The target architecture exposes this API through an HTTPS ALB, with ECS Fargate and RDS in private subnets. Local Docker Compose exposes it on port 8001. **This is not evidence of a public AWS endpoint.**

- Clients authenticate with a signed **HS256 JWT** containing `sub` (rights-holder UUID), `iss=sonoraplay`, `aud=api-titulares`, `iat`, and `exp`. The signing secret belongs in SSM Parameter Store for AWS and a non-versioned `.env` for local development.
- Missing, expired, malformed, or incorrectly signed tokens produce **401** with `WWW-Authenticate: Bearer`.
- Accessing another rights holder's path produces **403**, without first opening a database session; this prevents cross-holder data disclosure (RN-11, CA-08).
- `GET /me/reportes` is the preferred route: the holder identity comes from the token. `GET /titulares/{titular_id}/reportes` requires the path UUID to match the token subject.
- Optional `periodo` (`YYYY-MM`) and `pais` (uppercase ISO-2) filter reports. The repository always filters by the authenticated holder and selects the latest published settlement for each period.
- `GET /health` checks PostgreSQL connectivity without authentication.

The Spanish technical section above remains the detailed reference for all response fields, examples, error cases, development token generation, and tests. Tokens, secrets, and real personal information must not be placed in published screenshots.
