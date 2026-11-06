# Consumidor F2 (EG-52): RabbitMQ -> Bronze (archivo local o S3 por lotes, EG-33).
# Build desde la raíz del repo: docker build -f docker/consumidor.Dockerfile .
# Corre como servicio de larga duración (Fargate Spot): lee la cola eventos.f2 hasta que lo detienen.
# Variables: RABBITMQ_URL (con la contraseña desde SSM) y BRONZE_S3_BUCKET para escribir en S3.
FROM python:3.12.15-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Capa 1: solo dependencias, para que un cambio de código no las reinstale.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Capa 2: el paquete sonoraplay y el esquema F2, que el consumidor usa para validar cada evento.
COPY README.md LICENSE ./
COPY src ./src
COPY schemas/f2_evento.schema.json ./schemas/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

RUN useradd --create-home --uid 10001 app
USER app

# Sin HEALTHCHECK de red: el consumidor no expone puertos. Si el proceso muere, ECS reinicia la
# tarea y RabbitMQ re-entrega lo que no se confirmó.
CMD ["python", "-m", "sonoraplay.streaming.consumidor"]
