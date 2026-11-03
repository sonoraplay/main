# EG-34 · Airflow 3.1 con CeleryExecutor y el paquete sonoraplay (las tareas importan de él).
# Build desde la raíz: docker build -f docker/airflow/Dockerfile .
FROM apache/airflow:3.1.3-python3.12

USER root
RUN apt-get update && apt-get install -y --no-install-recommends gcc libpq-dev \
    && rm -rf /var/lib/apt/lists/*
USER airflow

# Las versiones salen de las restricciones oficiales de Airflow: no se mezclan con uv.lock.
ARG AIRFLOW_VERSION=3.1.3
RUN pip install --no-cache-dir \
    --constraint "https://raw.githubusercontent.com/apache/airflow/constraints-${AIRFLOW_VERSION}/constraints-3.12.txt" \
    "apache-airflow-providers-celery" "psycopg[binary]>=3.1" "pandas>=2.2,<3" "pyarrow>=17,<25"

COPY --chown=airflow:root pyproject.toml README.md LICENSE /opt/sonoraplay/
COPY --chown=airflow:root src /opt/sonoraplay/src
ENV PYTHONPATH=/opt/sonoraplay/src
