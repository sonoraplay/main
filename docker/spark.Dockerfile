# Jobs de Spark (Bronze → Silver, EG-35, y liquidación Gold, EG-37) en Fargate ARM64.
# Build desde la raíz del repo: docker build -f docker/spark.Dockerfile .
# Cada ejecución sobrescribe el comando de la tarea, por ejemplo:
#   python -m sonoraplay.spark.silver --fecha 2026-09-20 --run-id ... --bronze s3a://...
#   python -m sonoraplay.spark.gold --periodo 2026-09 --silver-run-id ... --run-id ...
FROM python:3.12.15-slim-bookworm

COPY --from=ghcr.io/astral-sh/uv:0.12.17 /uv /usr/local/bin/uv

# Java 17 (Spark 4 lo exige) y curl para bajar los dos jars de S3A.
RUN apt-get update \
    && apt-get install -y --no-install-recommends openjdk-17-jre-headless curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    SPARK_CONF_DIR=/app/conf \
    HOME=/tmp \
    SPARK_LOCAL_DIRS=/tmp \
    JAVA_TOOL_OPTIONS="-Djava.io.tmpdir=/tmp"

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-project

COPY README.md LICENSE ./
COPY src ./src
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Misma versión que el CI (tests/spark). PySpark trae sus propios jars de Spark y Hadoop 3.4.1.
ARG PYSPARK_VERSION=4.0.1
RUN --mount=type=cache,target=/root/.cache/uv \
    uv pip install --python /opt/venv/bin/python "pyspark==${PYSPARK_VERSION}"

# S3A: hadoop-aws debe coincidir con el Hadoop de PySpark (3.4.1) y con su bundle del SDK v2.
# Los hashes SHA-256 se verificaron al fijarlos; si no coinciden, el build falla.
RUN set -eux; \
    jars=$(python -c "import pyspark, os; print(os.path.join(os.path.dirname(pyspark.__file__), 'jars'))"); \
    curl -fsSL -o "$jars/hadoop-aws-3.4.1.jar" https://repo1.maven.org/maven2/org/apache/hadoop/hadoop-aws/3.4.1/hadoop-aws-3.4.1.jar; \
    curl -fsSL -o "$jars/bundle-2.24.6.jar" https://repo1.maven.org/maven2/software/amazon/awssdk/bundle/2.24.6/bundle-2.24.6.jar; \
    echo "01334a07e179cae2b7e251f24857f11e3759108c9d6a79dcbe362a4295227da2  $jars/hadoop-aws-3.4.1.jar" | sha256sum -c -; \
    echo "890bf9f2a80488f7a8aa8277d64d13a9ea3a3cdff8607ef3b63a878d8b467b41  $jars/bundle-2.24.6.jar" | sha256sum -c -

COPY docker/spark/spark-defaults.conf /app/conf/spark-defaults.conf

RUN useradd --create-home --uid 10001 app
USER app

# Sin CMD útil: la tarea de ECS siempre trae el comando del job.
CMD ["python", "-c", "print('Indica el job: python -m sonoraplay.spark.silver | gold')"]
