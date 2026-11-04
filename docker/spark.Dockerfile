# Job de Spark (EG-35 Silver / EG-37 Gold) para ECS Fargate. Corre y termina: no es un servicio.
# Build desde la raíz del repo: docker build -f docker/spark.Dockerfile .
# Comando por defecto: la liquidación mensual (Gold). Silver se lanza con otro `command`
# (python -m sonoraplay.spark.silver ...) sobre la misma imagen.
FROM python:3.12.15-slim-bookworm

# Spark 4 necesita Java 17. Solo el JRE headless.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    # Raíz de solo lectura en ECS: todo lo temporal de Spark va a /tmp (volumen escribible).
    SPARK_LOCAL_DIRS=/tmp \
    HOME=/tmp

WORKDIR /app

# Capa 1: solo dependencias, para que un cambio de código no las reinstale.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

# Capa 2: el paquete sonoraplay.
COPY README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev


# Va después del último `uv sync`, que borra lo que no está en uv.lock. PySpark no está ahí (el CI lo agrega con `--with pyspark==4.0.1`); aquí va con la misma
# versión fija. Trae Hadoop 3.4.1, así que los JAR de S3A deben ser de esa misma versión.
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python "pyspark==4.0.1"

# S3A: hadoop-aws y el SDK v2 que le corresponde (hadoop-project 3.4.1 → AWS SDK 2.24.6), con SHA-1
# fijado. Las credenciales salen del rol de la tarea de ECS (cadena por defecto de Hadoop).
RUN python - <<'PY'
import hashlib, pathlib, urllib.request, pyspark
destino = pathlib.Path(pyspark.__file__).parent / "jars"
base = "https://repo1.maven.org/maven2"
jars = {
    "org/apache/hadoop/hadoop-aws/3.4.1/hadoop-aws-3.4.1.jar": "641d8fe1d7683cdcc05cc3a794c0374553f6bd6a",
    "software/amazon/awssdk/bundle/2.24.6/bundle-2.24.6.jar": "242317b028d951dbbf6a142241e041b684696a3b",
}
for ruta, sha1 in jars.items():
    datos = urllib.request.urlopen(f"{base}/{ruta}", timeout=120).read()
    if hashlib.sha1(datos).hexdigest() != sha1:
        raise SystemExit(f"SHA-1 distinto en {ruta}")
    (destino / ruta.rsplit("/", 1)[1]).write_bytes(datos)
PY

RUN useradd --create-home --uid 10001 app
USER app

CMD ["python", "-m", "sonoraplay.spark.gold"]
