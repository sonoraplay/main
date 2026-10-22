# SonoraPlay Regalías

Plataforma de datos que decide qué reproducciones de música son válidas y, con ellas, liquida las regalías de los titulares (sellos, distribuidoras y sociedades de gestión) de **SonoraPlay Media**, un servicio de streaming ficticio con 900 mil suscriptores en Latinoamérica.

Proyecto 08 del programa de ingeniería de datos de Riwi. Equipo: Joshua Quintero, María Clara Manjarrés y Andrea Zárate.

> **Estado:** Sprint 1 (descubrimiento y diseño) terminado. En `develop` están EG-10 a EG-18 con los ADR 0001–0005 y 0020:
>
> - EG-10: repositorio base, CI y detección de secretos.
> - EG-11: ambigüedades de las reglas de negocio y supuestos.
> - EG-12: catálogo F1 limpio y titulares.
> - EG-13: seed F3 de suscripciones.
> - EG-14: seed F4 de contratos.
> - EG-15: esquema JSON de eventos F2.
> - EG-16: arquitectura v1 y registro de ADR.
> - EG-17: RN-01 y RN-02 (validez y tope diario).
> - EG-18: RN-03 (detección de granjas).
>
> Falta fusionar `develop` en `main` con la etiqueta `v0.1.0-sprint1`.

---

## Todo con Docker Compose (EG-25)

La forma más rápida de tener todo funcionando: un solo comando levanta PostgreSQL, carga los datos de prueba, genera eventos y arranca las dos APIs. No hace falta instalar uv ni Python.

**Requisitos:** Git y [Docker Desktop](https://docs.docker.com/desktop/) (o Docker Engine con Compose v2.20 o superior) encendido.

**1. Clona y prepara `.env`**

```bash
git clone https://github.com/JoshuaQ-rJ/sonoraplay-proyect.git
cd sonoraplay-proyect
git checkout develop
cp .env.example .env
```

En `.env`:

- Cambia `POSTGRES_PASSWORD` (y la misma contraseña en `DATABASE_URL` y `TEST_DATABASE_URL`, que solo se usan fuera de Docker).
- Cambia `API_TITULARES_JWT_SECRET` por un secreto aleatorio **antes** de levantar el stack. El valor de `.env.example` es falso a propósito y la API de sellos no arranca con él. Para generarlo solo con Docker:

```bash
docker run --rm python:3.12.15-slim-bookworm python -c "import secrets; print(secrets.token_urlsafe(48))"
```

**2. Levanta todo**

```bash
docker compose up -d --build
docker compose ps -a
```

La primera vez tarda unos minutos porque construye las imágenes. Cuando termina, `postgres` y las dos APIs están `healthy`, y `seed` y `simulador` están `Exited (0)`.

| Servicio | Qué hace | Arranca cuando | Puerto |
|---|---|---|---|
| `postgres` | PostgreSQL 16 con el DDL de `db/ddl/` | Primero | `PG_PORT` (5432) |
| `seed` | Catálogo F1 → seed F3 (modo `dev`) → seed F4, y termina | `postgres` está *healthy* | — |
| `simulador` | 100 eventos F2 con semilla 42, y termina | `seed` terminó con código 0 | — |
| `api-contratos` | API de contratos F4 (EG-20) | `postgres` *healthy* y `seed` terminado con 0 | `API_CONTRATOS_PORT` (8000) |
| `api-titulares` | API de sellos (EG-21) | `postgres` *healthy* y `seed` terminado con 0 | `API_TITULARES_PORT` (8001) |
| `esqueleto` | Solo con `--profile esqueleto`: liquida un país con los eventos y lo publica (EG-24), y termina | `postgres` *healthy* y `simulador` terminado con 0 | — |

```bash
curl http://localhost:8000/health     # {"status":"ok"}
curl http://localhost:8001/health
```

Documentación interactiva: <http://localhost:8000/docs> y <http://localhost:8001/docs>.

**Health checks.** `postgres` y las APIs tienen un health check propio. `seed` y `simulador` son trabajos de una sola ejecución, así que no tiene sentido un health check periódico: su salud es el código de salida. Compose la exige con `depends_on: condition: service_completed_successfully`, y si el seed falla, ni el simulador ni las APIs arrancan.

**Idempotencia.** Puedes repetir `docker compose up -d` o `docker compose restart seed` sin que crezcan los conteos, porque los seeds usan IDs `uuid5` deterministas y `ON CONFLICT DO NOTHING`.

**Datos generados.** El catálogo (`catalogo_f1.parquet`, `track_generos.parquet` y `titulares.parquet`) y los eventos (`eventos_f2.jsonl`) quedan en el volumen `datos-procesados`, no en tu carpeta `data/`. Para verlos:

```bash
docker compose run --rm --no-deps --entrypoint sh simulador -c "ls -la /datos/procesados; wc -l /datos/procesados/eventos_f2.jsonl"
```

**Catálogo completo de Kaggle.** Por defecto, el seed usa la muestra versionada `data/samples/f1_muestra.csv`: 200 filas y 170 artistas, por eso con 50 titulares. Para usar el CSV completo:

1. Descárgalo como `data/raw/dataset.csv` (ver [Catálogo F1](#catálogo-f1-eg-12)). La carpeta `data/` se monta en el seed en solo lectura.
2. Agrega a `.env`:

   ```bash
   F1_ENTRADA=/datos/entrada/raw/dataset.csv
   F1_TITULARES=1500
   ```

3. Vuelve a empezar con la base vacía. Otro catálogo genera otros titulares, que se sumarían a los anteriores.

   ```bash
   docker compose down -v
   docker compose up -d --build
   ```

`F3_MODO=completo` carga 900.000 usuarios en lugar de 10.000.

**Logs**

```bash
docker compose logs seed simulador          # salida de los trabajos
docker compose logs -f api-titulares        # seguir una API
```

**Apagar y limpiar**

```bash
docker compose down        # detiene y conserva los datos
docker compose down -v     # borra también los volúmenes pgdata y datos-procesados
```

Las imágenes usan `python:3.12.15-slim-bookworm` y `postgres:16.15-bookworm`, con uv `0.12.17` fijado. Corren con un usuario sin privilegios (uid 10001) y no contienen `.env`: toda la configuración entra por variables de entorno.

## Esqueleto de punta a punta (EG-24)

Un solo comando hace que los 100 eventos del simulador pasen por las reglas de validez (RN-01, RN-02), la atribución al mes (RN-04) y la liquidación de un país (RN-05 a RN-10), y deja el resultado en `reporte_regalias`. Después, un sello consulta su regalía en la API con su token. Detalle del flujo, reglas y valores provisionales: [docs/esqueleto.md](docs/esqueleto.md).

**1. Prepara `.env`** como en el paso 1 de [Todo con Docker Compose](#todo-con-docker-compose-eg-25): copia `.env.example`, cambia `POSTGRES_PASSWORD` y pon un `API_TITULARES_JWT_SECRET` aleatorio.

**2. Corre el esqueleto (un solo comando)**

```bash
docker compose --profile esqueleto up --build
```

Compose levanta `postgres`, corre `seed` y `simulador`, y cuando el simulador termina corre `esqueleto`. Las APIs quedan en pie. Busca en el log el bloque de `sonoraplay-esqueleto`, que termina con `exited with code 0`:

```text
== Esqueleto EG-24 · liquidación publicada
ID de liquidación: a9e9d2b3-7aff-4bbb-b458-cfa033f21267
Período: 2026-09   País de facturación: CO
Eventos F2: 100   Reproducciones: 38   Ajustes de meses anteriores: 0
Descartadas: duracion_insuficiente=4, tope_diario=1
Pagables por país: AR=6, CL=4, CO=13, MX=2, PE=8
...
Titular con mayor regalía: fb950a36-dd51-59f6-af5f-200916631894 (2340.00 USD)
```

El ID de la liquidación cambia en cada corrida. Los datos son deterministas (semilla 42), así que el país, los conteos y las regalías se repiten. Si prefieres no dejar la terminal ocupada, usa `up --build -d` y luego `docker compose logs esqueleto`. Con `Ctrl+C` se detienen las APIs.

**3. Consulta la API como el sello**

Copia el UUID del titular con mayor regalía que imprimió el resumen y, en otra terminal:

```bash
TOKEN=$(docker compose exec -T api-titulares python -m sonoraplay.api_titulares.tokens --titular <uuid>)
curl -H "Authorization: Bearer $TOKEN" "http://localhost:8001/me/reportes?periodo=2026-09"
```

En PowerShell, la primera línea es `$TOKEN = docker compose exec -T api-titulares python -m sonoraplay.api_titulares.tokens --titular <uuid>`, y luego `curl.exe -H "Authorization: Bearer $TOKEN" "http://localhost:8001/me/reportes?periodo=2026-09"`.

Resultado esperado: un JSON con tus filas y totales. Cada uno trae `regalia_usd` (string con 2 decimales), `reproducciones_validas` y el mismo `liquidacion_id` del resumen (RNF-03):

```json
{"titular_id": "fb950a36-…", "filas": [{"periodo": "2026-09", "pais": "CO", "componente": "publicidad",
  "reproducciones_validas": 1, "participacion": "0.500000", "porcentaje_contractual": "52.00",
  "regalia_usd": "2340.00", "liquidacion_id": "a9e9d2b3-…"}], "totales": [...]}
```

Comprobación a mano: bolsa de publicidad de CO 9.000 USD (45 % de 20.000) × 1/2 reproducciones del plan gratuito × 52 % = 2.340,00 USD.

**Volver a liquidar.** Cada corrida crea una liquidación nueva y la API muestra la última; la anterior queda intacta (append-only, ADR-0007):

```bash
docker compose --profile esqueleto run --rm esqueleto --pais CO --publicidad-usd 15000
```

**Valores provisionales.** La publicidad todavía no tiene fuente (F5 llega con la EG-30). Se usan **20.000 USD** de ingresos publicitarios por país, que se cambian con `--publicidad-usd` o con `ESQUELETO_PUBLICIDAD_USD` en `.env`. RN-03 (fraude) no se aplica porque el simulador mínimo no genera granjas.

**Sin Docker.** Con el catálogo, F3, F4 y el simulador ya corridos (ver [Simulador F2 mínimo](#simulador-f2-mínimo-eg-19)):

```bash
uv run --env-file .env python -m sonoraplay.esqueleto
uv run --env-file .env python -m sonoraplay.api_titulares.tokens --titular <uuid>
uv run --env-file .env python -m pytest tests/esqueleto -v
```

## Requisitos

| Herramienta | Versión | Para qué |
|---|---|---|
| [Git](https://git-scm.com/) | 2.40 o superior | Control de versiones |
| [uv](https://docs.astral.sh/uv/getting-started/installation/) | 0.8 o superior | Instala Python 3.12 y las dependencias |
| [Docker Desktop](https://docs.docker.com/desktop/) | Reciente | PostgreSQL local (a partir de la EG-13) y Gitleaks en pre-commit |

No hace falta instalar Python a mano: uv descarga la versión fijada en `.python-version`.

## Instalación

```bash
git clone https://github.com/JoshuaQ-rJ/sonoraplay-proyect.git
cd sonoraplay-proyect
git checkout develop
uv sync
uv run python -m pre_commit install
```

- `uv sync` crea el entorno `.venv` e instala exactamente las versiones de `uv.lock`.
- `pre_commit install` activa las revisiones automáticas (Ruff y Gitleaks) antes de cada commit. Gitleaks corre en Docker, así que Docker Desktop debe estar encendido al hacer commit.

Copia las variables de entorno y completa los valores. El archivo `.env` **nunca** se sube al repositorio:

```bash
cp .env.example .env
```

> **Windows:** clona el proyecto fuera de OneDrive (por ejemplo, en `C:\dev`). OneDrive bloquea archivos de `.venv` mientras sincroniza y provoca errores de `Acceso denegado`.

## Pruebas y calidad de código

| Qué | Windows | macOS / Linux |
|---|---|---|
| Pruebas | `uv run python -m pytest` | `uv run pytest` |
| Pruebas con cobertura | `uv run python -m pytest --cov=sonoraplay` | `uv run pytest --cov=sonoraplay` |
| Lint | `uv run python -m ruff check .` | `uv run ruff check .` |
| Formato (revisar) | `uv run python -m ruff format --check .` | `uv run ruff format --check .` |
| Formato (corregir) | `uv run python -m ruff format .` | `uv run ruff format .` |

> En Windows se usa `python -m` porque el Control de aplicaciones puede bloquear los ejecutables que uv crea en `.venv\Scripts\`.

## Seed F3 de suscripciones (EG-13)

Seed reproducible e idempotente de la base F3 de suscripciones (PostgreSQL 16).

```bash
cp .env.example .env            # y cambia POSTGRES_PASSWORD
uv sync
docker compose up -d --wait postgres     # solo la base; aplica db/ddl/ al crear el volumen
uv run --env-file .env python -m sonoraplay.seed --modo dev        # 10.000 usuarios
uv run --env-file .env python -m sonoraplay.seed --modo completo   # 900.000 usuarios
uv run --env-file .env python -m pytest tests/seed -v
```

Opciones: `--semilla N` (por defecto `SEED`=42), `--usuarios N`, `--tasa-defectos 0.02`.

Si el puerto 5432 está ocupado, cambia `PG_PORT` y el puerto de las dos URLs en `.env`. Para RDS (Sprint 3, EG-28) solo cambia `DATABASE_URL`.

Comportamientos a conocer:

1. El volumen es un objetivo: la última familia puede sumar hasta 5 usuarios extra; dev es prefijo exacto de completo.
2. Otra semilla sobre una base cargada agrega un segundo conjunto de datos aparte.
3. Cambiar la tasa de defectos exige base vacía (`docker compose down -v`): las filas existentes no se actualizan.
4. Si cambias el DDL, corre `docker compose down -v` (el entrypoint solo aplica scripts con el volumen vacío).

Modelo y decisiones: `docs/datos/modelo-f3.md`.

## Catálogo F1 (EG-12)

Limpia el catálogo de pistas (F1): una fila por `track_id`, género principal, tabla puente de géneros y un titular de derechos por artista. Decisión y cifras en [ADR-0003](docs/adr/0003-duplicados-f1.md); exploración en `notebooks/01_exploracion_f1.ipynb`.

1. Descarga el CSV del [Spotify Tracks Dataset](https://www.kaggle.com/datasets/maharshipandya/-spotify-tracks-dataset) (Kaggle, 114.000 filas) y guárdalo como `data/raw/dataset.csv`. `data/raw/` y `data/processed/` no se suben al repositorio.
2. Corre el pipeline:

```bash
uv run python -m sonoraplay.catalogo     # Windows y macOS / Linux
```

Escribe en `data/processed/`:

| Archivo | Contenido |
|---|---|
| `catalogo_f1.parquet` | Una fila por `track_id`, con `genero_principal`, `artista_principal` y `titular_id` |
| `track_generos.parquet` | Tabla puente (`track_id`, `genero`) con todos los géneros de cada pista |
| `titulares.parquet` | 1.500 titulares (sello, distribuidora o sociedad de gestión) con UUID determinista |

Opciones: `--entrada`, `--salida`, `--titulares N` (por defecto 1.500) y `--semilla N` (por defecto 42). La misma semilla produce exactamente los mismos archivos.

Las pruebas (`tests/catalogo`) usan solo la muestra versionada `data/samples/f1_muestra.csv` (200 filas con los casos difíciles). Para regenerarla: `uv run python -m sonoraplay.catalogo.muestra`.

## Seed F4 de contratos (EG-14)

Carga en PostgreSQL los titulares de derechos y sus contratos: el % de cada pista con su vigencia (RN-07, con cambios a mitad de mes), una condición territorial opcional que se suma a la general (Q7) y las exclusiones por país (RN-08). Lee los titulares y las pistas del catálogo F1, así que **primero hay que correr el catálogo**:

```bash
uv run python -m sonoraplay.catalogo
uv run --env-file .env python -m sonoraplay.seed.f4_contratos
uv run --env-file .env python -m pytest tests/seed/test_seed_f4.py -v
```

Opciones: `--datos-f1` (carpeta con `titulares.parquet` y `catalogo_f1.parquet`; por defecto `data/processed`) y `--semilla N` (por defecto 42). Es idempotente: reejecutarlo no duplica filas.

Modelo y reglas: [docs/datos/modelo-f4.md](docs/datos/modelo-f4.md).

## API de contratos F4 (EG-20)

API interna con FastAPI y SQLModel. Spark la consulta para obtener el % vigente de un titular en una fecha (RN-07), con su condición territorial (Q7) y sus exclusiones (RN-08). Mapea las tablas F4 de la EG-14 sin modificar el DDL. No pasa por el ALB: en AWS se llama por DNS privado.

| Endpoint | Para qué |
|---|---|
| `GET /health` | Estado de la API y de PostgreSQL (503 si la base no responde) |
| `GET /titulares/{titular_id}/porcentaje?fecha=YYYY-MM-DD&track_id=&pais=` | % vigente en la fecha |
| `GET /titulares/{titular_id}/condiciones?limit=&offset=` | Períodos de vigencia y exclusiones, paginados |

```bash
# Local (requiere PostgreSQL con el seed F4 cargado)
uv run --env-file .env python -m uvicorn sonoraplay.api_contratos.main:app --port 8000
# Abrir http://localhost:8000/docs

# En Docker
docker compose up -d --build api-contratos
curl http://localhost:8000/health

# Pruebas
uv run --env-file .env python -m pytest tests/api_contratos -v
```

Reglas, ejemplos de request y response y despliegue: [docs/servicios/api-contratos.md](docs/servicios/api-contratos.md).

## API de sellos (EG-21)

API **pública** (en AWS, detrás del ALB con HTTPS) con la que cada sello consulta solo su reporte de regalías: reproducciones válidas, participación en la bolsa, % contractual, regalía en USD e ID de liquidación, por mes y país (RF-05). Se autentica con un JWT HS256 cuyo `sub` es el titular; pedir datos de otro titular da 403, exista o no (RN-11, CA-08, [ADR-0006](docs/adr/0006-autenticacion-aislamiento-sellos.md)). Lee las tablas de `db/ddl/003_reportes_regalias.sql`, que son el contrato que llenan la EG-23 y la EG-37.

| Endpoint | Para qué |
|---|---|
| `GET /health` | Estado de la API y de PostgreSQL (sin token) |
| `GET /me/reportes?periodo=YYYY-MM&pais=XX` | Reporte del titular del token (recomendado) |
| `GET /titulares/{titular_id}/reportes?periodo=&pais=` | Lo mismo con el titular en el path; otro titular → 403 |

```bash
# Una vez: secreto aleatorio en .env (API_TITULARES_JWT_SECRET); nunca el de .env.example
uv run python -c "import secrets; print(secrets.token_urlsafe(48))"

# Token de desarrollo para un titular (solo se imprime)
uv run --env-file .env python -m sonoraplay.api_titulares.tokens --titular <uuid> --horas 8

# Local: abrir http://localhost:8001/docs y usar Authorize
uv run --env-file .env python -m uvicorn sonoraplay.api_titulares.main:app --port 8001

# En Docker
docker compose up -d --build api-titulares
curl http://localhost:8001/health

# Pruebas (incluye la de aislamiento CA-08)
uv run --env-file .env python -m pytest tests/api_titulares -v
```

Autenticación, ejemplos 200/401/403, modelo de lectura y contrato para la EG-23 / EG-37: [docs/servicios/api-titulares.md](docs/servicios/api-titulares.md).

## Eventos F2 (EG-15)

Esquema JSON (draft 2020-12) de los eventos de reproducción: `schemas/f2_evento.schema.json`. Campos, defectos inyectados y cómo se reconstruye una reproducción a partir de los eventos: `docs/datos/eventos-f2.md`. Deduplicación por `event_id`: [ADR-0004](docs/adr/0004-esquema-eventos-f2.md).

```bash
uv run pytest tests/schemas -v     # ejemplos válidos, inválidos y con defectos
```

## Simulador F2 mínimo (EG-19)

Genera eventos de reproducción F2 en un archivo JSON Lines que lee el esqueleto (EG-24). Es determinista: la misma semilla produce el mismo archivo byte por byte. Cada archivo incluye los escenarios que ejercitan RN-01 (reproducciones de 29 s y de 30 s, y una pausa que reinicia el conteo) y RN-02 (11 reproducciones válidas de la misma pista por el mismo usuario el mismo día UTC). Necesita el catálogo F1, F3 y F4 cargados, en ese orden:

```bash
docker compose up -d --wait postgres
uv run python -m sonoraplay.catalogo
uv run --env-file .env python -m sonoraplay.seed --modo dev
uv run --env-file .env python -m sonoraplay.seed.f4_contratos
uv run --env-file .env python -m sonoraplay.simulador --eventos 100 --semilla 42
uv run --env-file .env python -m pytest tests/simulador tests/reglas/test_sesiones.py -v
```

Opciones: `--eventos N` (por defecto 100, mínimo 30), `--semilla N` (por defecto 42), `--salida` (por defecto `data/processed/eventos_f2.jsonl`) y `--datos-f1` (por defecto `data/processed`). F4 debe estar cargado sobre el mismo catálogo que se pasa en `--datos-f1`.

Escenarios, reglas de cada sesión y reconstrucción de reproducciones (`reglas/sesiones.py`): [docs/datos/simulador-f2.md](docs/datos/simulador-f2.md). Granjas, eventos offline, los 5 defectos y la carga pico llegan con la EG-51.

## Reglas de negocio (EG-17, EG-18)

RN-01 (reproducción válida: 30 s continuos), RN-02 (tope diario por pista y usuario) y RN-03 (señales de granja) son funciones puras en `src/sonoraplay/reglas/` (`validez.py` y `fraude.py`), sin base de datos ni Spark, para probarlas en aislamiento y reutilizarlas en la capa Silver. Los umbrales están en `src/sonoraplay/config.py` y se justifican en [ADR-0002](docs/adr/0002-zona-horaria-dia-mes.md) (día y mes en UTC) y [ADR-0005](docs/adr/0005-umbrales-granjas.md) (umbrales de granja).

La liquidación de regalías (RN-05 a RN-10, RNF-02, EG-23) está en `src/sonoraplay/reglas/liquidacion.py`: bolsa por país de facturación con dos componentes (suscripción y publicidad), % vigente por fecha, exclusiones territoriales devueltas como incidentes y reparto al centavo por mayor residuo. Devuelve las filas `FilaReporte` que lee la API de sellos. Decisiones en [ADR-0007](docs/adr/0007-cierre-mes-ajustes-reliquidacion.md) (cierre append-only, ajustes y redondeo) y [ADR-0008](docs/adr/0008-pais-bolsa-dos-componentes.md) (país de la bolsa y dos componentes).

```bash
uv run python -m pytest tests/reglas -v
```

## Infraestructura en AWS (EG-26)

Terraform en `infra/terraform/` crea la base del entorno en AWS (HU 17, E-06):
- IAM de mínimo privilegio, con un rol por servicio y sin access keys;
- una VPC en 2 AZ con subredes públicas y privadas y una instancia NAT;
- el Data Lake en S3 por capas (Bronze, Silver, Gold), cifrado y con Block Public Access;
- RDS PostgreSQL privado con backups de 7 días y credenciales en SSM Parameter Store.

Todo lleva `Project=sonoraplay`, y `terraform destroy` lo borra sin huérfanos. El entorno está apagado por defecto: se prende solo en ventanas de prueba ([ADR-0020](docs/adr/0020-ventanas-encendido-aws.md)).

Guía paso a paso y cómo verificar cada criterio: [infra/terraform/README.md](infra/terraform/README.md). Decisiones: [ADR-0009](docs/adr/0009-region-aws.md) (región), [ADR-0010](docs/adr/0010-instancia-nat.md) (instancia NAT) y [ADR-0011](docs/adr/0011-terraform.md) (Terraform).

## Integración continua

Cada push a `main` o `develop`, y cada Pull Request, ejecuta cuatro revisiones en GitHub Actions (`.github/workflows/ci.yml`):

| Job | Qué revisa |
|---|---|
| `lint` | Estilo y errores comunes con Ruff (PEP 8) |
| `test` | Pruebas automatizadas con pytest y cobertura |
| `terraform` | `fmt`, `validate` y Checkov sobre `infra/terraform` (sin credenciales ni `apply`) |
| `secretos` | Credenciales expuestas con [Gitleaks](https://github.com/gitleaks/gitleaks) |

`main` y `develop` están protegidas: solo reciben cambios por Pull Request, con **1 aprobación** y los **3 jobs en verde**.

## Flujo de trabajo

### Ramas

| Rama | Uso |
|---|---|
| `main` | Lo entregado al final de cada sprint |
| `develop` | Integración diaria (rama por defecto) |
| `feature/EG-XX-descripcion-corta` | Una por historia de Jira; sale de `develop` actualizado |

Para empezar una historia:

```bash
git checkout develop
git pull
git checkout -b feature/EG-17-rn01-rn02
```

### Commits

Formato [Conventional Commits](https://www.conventionalcommits.org/es/v1.0.0/) con la clave de Jira al final:

```text
feat(reglas): RN-01 validez de 30 segundos [EG-17]
fix(seed): evita duplicados al reejecutar [EG-13]
docs(adr): ADR-0003 duplicados de F1 [EG-12]
```

Tipos: `feat`, `fix`, `test`, `docs`, `chore`, `ci`, `style`, `refactor`.

### Definition of Done

Un ítem se cierra en Jira solo si:

- [ ] El código está en `develop` y lo revisó otra persona del equipo.
- [ ] Tiene pruebas automatizadas que pasan, incluida la de su RN o CA.
- [ ] El CI está en verde y no expone secretos.
- [ ] Si implicó una decisión técnica, su ADR está escrito en la misma historia.
- [ ] La documentación que toca está actualizada.
- [ ] La rama, los commits y el PR citan la clave de Jira.

## Secretos

- Las credenciales **nunca** van en el código ni en commits.
- En local van en `.env` (ignorado por Git); en el repositorio solo existe `.env.example`, con los nombres de las variables.
- En AWS (desde el Sprint 3) van en SSM Parameter Store.
- Si Gitleaks detecta un secreto en un PR, el merge queda bloqueado. Una credencial real expuesta se revoca de inmediato, aunque luego se borre del código.

## Estructura del repositorio

```text
.github/
  workflows/ci.yml             CI: lint, pruebas, Terraform y secretos
  pull_request_template.md     Checklist de la Definition of Done
db/ddl/                        DDL de PostgreSQL: F3, F4 y reporte de regalías (se aplica al crear el volumen)
docs/analisis/                 Ambigüedades de las reglas de negocio y supuestos (EG-11)
docs/arquitectura/             Arquitectura v1 y diagrama (EG-16)
docs/adr/                      Registro de decisiones de arquitectura (ADR)
docs/datos/                    Modelos de datos y decisiones
docs/servicios/                Documentación de los servicios (API de contratos F4 y API de sellos)
infra/terraform/               Terraform de AWS: VPC, NAT, S3 por capas, RDS e IAM (EG-26)
docker/                        Dockerfiles por componente (api-contratos, api-titulares, seed, simulador, esqueleto) y seed.sh
schemas/                       Esquema JSON de eventos F2 y ejemplos
src/sonoraplay/                Código del paquete (src layout)
src/sonoraplay/config.py       Parámetros de negocio y umbrales centralizados
src/sonoraplay/reglas/         RN-01, RN-02, RN-03, reconstrucción de sesiones F2 y liquidación (funciones puras)
src/sonoraplay/simulador/      Simulador F2 mínimo (EG-19)
src/sonoraplay/esqueleto/      Esqueleto de punta a punta: eventos → reglas → liquidación → reporte (EG-24)
src/sonoraplay/seed/           Seeds F3 (suscripciones) y F4 (contratos)
src/sonoraplay/api_contratos/  API de contratos F4 (FastAPI + SQLModel)
src/sonoraplay/api_titulares/  API pública de sellos con JWT y aislamiento por titular (EG-21)
src/sonoraplay/reporte_regalias.py  Contrato del reporte de regalías (FilaReporte) para EG-23 / EG-37
src/sonoraplay/catalogo/       Limpieza del catálogo F1 y titulares
data/samples/                  Muestras pequeñas versionadas para pruebas
notebooks/                     Exploración de datos
tests/                         Pruebas con pytest
docker-compose.yml             Stack completo: PostgreSQL 16, seed, simulador F2, API de contratos F4, API de sellos (EG-25) y esqueleto con perfil (EG-24)
.dockerignore                  Lo que nunca entra a una imagen (.env, .venv, datos)
.gitattributes                 Fin de línea LF para los scripts de shell
.env.example                   Variables de entorno sin valores reales
.pre-commit-config.yaml        Revisiones antes de cada commit (Ruff y Gitleaks)
LICENSE                        Licencia MIT
pyproject.toml                 Proyecto, dependencias y configuración de Ruff y pytest
uv.lock                        Versiones exactas de las dependencias
```

Se irán agregando con sus historias desde el Sprint 2: los servicios, `spark/`, `dags/` e `infra/terraform/`.

## Documentación

- Arquitectura: [docs/arquitectura/arquitectura-v1.md](docs/arquitectura/arquitectura-v1.md) (EG-16).
- Decisiones de arquitectura: [registro de ADR](docs/adr/README.md). El entorno AWS está apagado por defecto y solo se prende en ventanas de prueba y la semana de la demo ([ADR-0020](docs/adr/0020-ventanas-encendido-aws.md)).
- Esqueleto de punta a punta: [docs/esqueleto.md](docs/esqueleto.md) (EG-24).
- Supuestos de las reglas de negocio: [docs/analisis/ambiguedades-rn.md](docs/analisis/ambiguedades-rn.md) (EG-11).
- Tablero del proyecto: Jira, proyecto **EG**.
