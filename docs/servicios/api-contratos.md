# API de contratos F4 (EG-20)

API **interna**, hecha con FastAPI y SQLModel, que expone las condiciones contractuales de F4. Su consumidor principal es Spark: al liquidar cada reproducción (capa Gold, EG-23/EG-37) pregunta qué % le corresponde al titular en la fecha y el país de esa reproducción.

- **Código:** `src/sonoraplay/api_contratos/`
- **Pruebas:** `tests/api_contratos/`
- **Esquema:** las tablas las define `db/ddl/002_f4_contratos.sql` (EG-14). La API solo las **mapea** con SQLModel: no crea ni modifica tablas.
- **Modelo y reglas:** [docs/datos/modelo-f4.md](../datos/modelo-f4.md).

## Despliegue y red

Según la [arquitectura v1](../arquitectura/arquitectura-v1.md):

- Corre en **ECS Fargate On-Demand** (ARM64, 0,25 vCPU / 0,5 GB) y escucha en el puerto **8000**.
- **No pasa por el ALB** y no se expone a internet. Spark la encuentra por DNS privado (AWS Cloud Map, espacio `sonoraplay.local`).
- Solo acepta tráfico de `sg-spark` en el puerto 8000 (`sg-api-contratos`). Lee F4 en RDS.
- No tiene autenticación propia: el aislamiento lo dan la red privada y los Security Groups. Si algún día se expone fuera de la VPC, hay que agregar autenticación antes.

## Capas

| Capa | Archivo | Responsabilidad |
|---|---|---|
| HTTP | `routers/contratos.py`, `routers/salud.py` | Validar la petición y traducir errores de dominio a 404 o 503. Sin lógica de negocio. |
| Reglas | `services.py` | Vigencia, Q7 y RN-08. `elegir_condicion` es pura y se prueba sin base de datos. |
| Datos | `repositories.py` | Consultas SQLModel, sin reglas. |
| Modelos | `models.py` | Tablas (espejo del DDL) y modelos de respuesta, por separado. |
| Conexión | `db.py` | Engine perezoso desde `DATABASE_URL` y la dependencia `get_session`. |
| App | `main.py` | `create_app()` y metadatos de OpenAPI. |

## Reglas

**Vigencia (RN-07).** Un período está vigente en `fecha` si `valido_desde <= fecha` y además `valido_hasta` es NULL o `fecha <= valido_hasta`. `valido_hasta` es **inclusivo**, igual que en el DDL (`daterange(valido_desde, valido_hasta + 1, '[)')`). Con 50 % hasta el 14 y 40 % desde el 15, el día 14 paga 50 y el 15 paga 40.

**Orden de decisión** para una pista, una fecha y un país opcional:

1. **RN-08:** si el país está excluido en la condición general vigente, la respuesta es `excluido: true` y `porcentaje: 0`, con status **200**: no es un error. La exclusión manda incluso si hay una condición territorial para ese país, porque la territorial no sustituye las exclusiones (modelo-f4).
2. **Q7:** si hay una condición territorial vigente para el país, se usa esa.
3. Si no, se usa la condición general (`territorio` NULL).
4. Si no hay ninguna condición aplicable, responde 404.

> Q7 sigue siendo un supuesto del equipo pendiente de validación (EG-11). Si cambia, se ajusta `services.elegir_condicion` y sus pruebas.

**Sin `track_id`.** Se usa la menor pista del titular (orden alfabético de `track_id`) que tenga una condición vigente en la fecha. En el seed F4 todas las pistas de un titular comparten condiciones (EG-14), así que el resultado es el mismo con cualquiera. Si en el futuro las condiciones varían por pista, Spark debe enviar `track_id` siempre.

**Porcentaje.** Es un número JSON de 0 a 100: `50.0` significa 50 %. En la base es `NUMERIC(5,2)`.

## Endpoints

La documentación interactiva está en `/docs` (Swagger UI) y el esquema en `/openapi.json`.

### `GET /health`

Hace un `SELECT 1` contra PostgreSQL. Lo usan el `HEALTHCHECK` del contenedor y el health check de ECS.

| Status | Cuerpo |
|---|---|
| 200 | `{"status": "ok"}` |
| 503 | `{"detail": "La base de datos no responde"}` |

### `GET /titulares/{titular_id}/porcentaje`

| Parámetro | Dónde | Tipo | Obligatorio | Validación |
|---|---|---|---|---|
| `titular_id` | ruta | UUID | sí | 422 si no es un UUID |
| `fecha` | query | `YYYY-MM-DD` | sí | 422 si falta o es inválida (por ejemplo `2026-02-30`) |
| `track_id` | query | texto (máximo 22) | no | |
| `pais` | query | ISO 3166-1 alfa-2 en mayúsculas | no | 422 si no cumple `^[A-Z]{2}$` |

Ejemplo:

```http
GET /titulares/11111111-1111-4111-8111-111111111111/porcentaje?fecha=2026-09-15&pais=CO
```

```json
{
  "titular_id": "11111111-1111-4111-8111-111111111111",
  "track_id": "AAAAAAAAAAAAAAAAAAAAAA",
  "fecha": "2026-09-15",
  "pais": "CO",
  "porcentaje": 40.0,
  "territorio_aplicado": null,
  "excluido": false,
  "contrato_id": "5f0c3c7e-1d2a-5b8e-9a51-3f6f2a7f1c11",
  "valido_desde": "2026-09-15",
  "valido_hasta": null
}
```

`territorio_aplicado` es `null` cuando se usó la condición general. Ejemplo con un país excluido (RN-08):

```json
{ "...": "...", "pais": "MX", "porcentaje": 0.0, "excluido": true, "territorio_aplicado": null }
```

Errores:

| Status | `detail` | Cuándo |
|---|---|---|
| 404 | `Titular no encontrado` | El titular no existe en `titulares_derechos`. |
| 404 | `El titular no tiene una condición vigente en esa fecha` | El titular existe, pero no hay período vigente (o la pista no es suya). |
| 422 | Detalle de validación de Pydantic | UUID, fecha o país inválidos. |

### `GET /titulares/{titular_id}/condiciones`

Lista todos los períodos de vigencia del titular, con sus exclusiones territoriales (RN-08). Es paginado porque un titular puede tener muchas pistas.

| Parámetro | Tipo | Por defecto | Rango |
|---|---|---|---|
| `limit` | entero | 100 | 1 a 1000 |
| `offset` | entero | 0 | 0 o más |

El orden es estable: `track_id`, luego la condición general antes que las territoriales, luego `valido_desde`.

```http
GET /titulares/33333333-3333-4333-8333-333333333333/condiciones?limit=2&offset=0
```

```json
{
  "titular_id": "33333333-3333-4333-8333-333333333333",
  "total": 1,
  "limit": 2,
  "offset": 0,
  "condiciones": [
    {
      "contrato_id": "8b0d9a40-6a2b-5f4e-8c0e-0b6f6f0d2e33",
      "track_id": "CCCCCCCCCCCCCCCCCCCCCC",
      "territorio": null,
      "porcentaje": 35.0,
      "valido_desde": "2026-09-01",
      "valido_hasta": null,
      "exclusiones": ["MX"]
    }
  ]
}
```

Si el titular no existe, responde 404 `Titular no encontrado`.

## Cómo correrla

### En local (Windows)

Se necesita PostgreSQL con F4 cargado (ver la sección del seed F4 en el README):

```bash
docker compose up -d --wait postgres
uv run --env-file .env python -m uvicorn sonoraplay.api_contratos.main:app --port 8000
```

Luego se abre [http://localhost:8000/docs](http://localhost:8000/docs). Para obtener un titular real:

```bash
docker exec sonoraplay-postgres psql -U sonora -d sonoraplay -c "SELECT titular_id FROM contratos LIMIT 1"
```

### En Docker

```bash
docker compose up -d --build api-contratos
curl http://localhost:8000/health
```

- **Imagen:** `docker/api-contratos.Dockerfile`, basada en `python:3.12-slim` con uv 0.12.17. Instala con `uv sync --frozen --no-dev`, corre con un usuario no root y trae un `HEALTHCHECK` contra `/health`.
- **Conexión en Compose:** el servicio arma `DATABASE_URL` con `POSTGRES_USER`, `POSTGRES_PASSWORD` y `POSTGRES_DB` de `.env`, y apunta al host `postgres`. El puerto publicado se cambia con `API_CONTRATOS_PORT`.
- **Secretos:** `.dockerignore` excluye `.env`, así que ninguna credencial entra a la imagen.

### Pruebas

```bash
uv run --env-file .env python -m pytest tests/api_contratos -v
```

- `test_services.py` prueba las reglas puras, sin base de datos.
- `test_repositories.py` prueba la vigencia contra PostgreSQL.
- `test_http.py` prueba los endpoints con `TestClient`, con la sesión apuntada a la base de prueba (`TEST_DATABASE_URL`).


---

## English — F4 contracts API: technical summary

**Story:** EG-20. **Implementation:** FastAPI + SQLModel under `src/sonoraplay/api_contratos/`; tests under `tests/api_contratos/`. The schema is defined by `db/ddl/002_f4_contratos.sql`; the API maps existing tables and does not create them.

This is an **internal** API intended for Spark's royalty settlement processing. The proposed AWS design places it on private ECS Fargate behind private DNS, not the public ALB. This describes the target architecture, **not a verified live deployment**.

- `GET /health` performs a database `SELECT 1` and returns 200 when healthy or 503 when PostgreSQL is unavailable.
- `GET /titulares/{titular_id}/porcentaje` accepts a UUID rights holder, mandatory `fecha` (`YYYY-MM-DD`), and optional `track_id` and ISO-2 `pais`. The response describes the selected contract, percentage, territory, validity, and exclusion flag.
- **RN-07:** `valido_desde` and `valido_hasta` are inclusive; a condition ending on the 14th is followed by the new one starting on the 15th.
- **RN-08:** a country excluded by the general condition yields `excluido: true` and `porcentaje: 0` with HTTP 200, even if a territorial condition exists.
- **Q7 (pending instructor validation):** country-specific terms take precedence over general terms unless the country is excluded. Without an applicable condition, the endpoint returns 404.
- Without `track_id`, the service selects the alphabetically first eligible track; this relies on the seed's shared conditions per rights holder and must be revisited if contracts become track-specific.

The full request/response tables, examples, error mapping, and development commands are specified in the Spanish technical section above. They must be kept aligned when the API contract changes.
