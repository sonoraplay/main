---
title: "ADR-0024 · Shared private orchestration EC2 / EC2 privada compartida"
---

# ADR-0024 — Single orchestration EC2 / Una EC2 de orquestación

## English — decision

**Status:** proposed, awaiting Terraform CI and real AWS acceptance. **Date:** 2026-11-08.

**Context.** Architecture v1 envisioned separate EC2 hosts for RabbitMQ and Airflow. The delivery window and cost budget favor a single private ARM64 `t4g.large` EC2 with Docker Compose: RabbitMQ 4.1, Airflow 3 CeleryExecutor with two workers, local Airflow metadata PostgreSQL, and F2 producer/consumer. Platform PostgreSQL stays in private RDS. Silver and Gold execute as ECS Fargate Spark tasks, not on the EC2.

**Decision.** Provision `aws_instance.orquestacion` in a private subnet with existing `airflow` security group and IAM instance profile, encrypted EBS and required IMDSv2. No public IP, inbound SSH, Airflow or RabbitMQ port. Airflow API binds to host loopback only and is accessed through SSM port forwarding. Existing `rabbitmq` SG and role remain declared but unused by this instance. Do not modify existing architecture-v1 resources.

**Secrets.** Four new values are generated ephemerally by Terraform and written to SSM SecureString using write-only attributes: RabbitMQ password, Fernet key, Airflow JWT secret and metadata PostgreSQL password. RDS credentials are read from existing SSM paths. Bootstrapping retrieves them on the instance and writes a root-owned mode-0600 `.env`. Neither plaintext secret nor generated value is placed in the repository or user_data. Be aware the instance-local `.env` holds secrets; delete it on teardown.

**Trade-offs.** One EC2 is a single point of failure; the two Celery workers are not host-independent. RabbitMQ and Airflow compete for CPU/RAM, and RabbitMQ queues plus metadata are lost on stack destruction unless backed up. NAT and EC2 costs apply while running. Container IMDSv2 access uses a hop limit of two. The private instance must reach SSM, GitHub, ECR/registries and S3 through the existing NAT/endpoints.

**Acceptance gate.** Terraform formatting, validation, Checkov, additive plan, SSM connection, Compose health, DAG import, 100-event S3 batch, and full destroy/orphan checks require recorded evidence. No AWS deployment is claimed by this ADR. Use the PR branch as `orquestacion_git_ref` during testing; switch to `main` only after merging the deployment code.

## Español — decisión

**Estado:** propuesto, pendiente de CI Terraform y aceptación en AWS real. **Fecha:** 2026-11-08.

**Contexto.** La arquitectura v1 contemplaba dos EC2 separadas para RabbitMQ y Airflow. Por plazo de entrega y costo se adopta una única EC2 privada ARM64 `t4g.large` con Docker Compose: RabbitMQ 4.1, Airflow 3 con CeleryExecutor y dos workers, PostgreSQL local exclusivamente para metadatos de Airflow, productor y consumidor F2. PostgreSQL de la plataforma permanece en RDS privado. Silver y Gold se ejecutan como tareas Spark en ECS Fargate.

**Decisión.** `aws_instance.orquestacion` se crea en subred privada, con SG y perfil IAM `airflow` existentes, EBS cifrado e IMDSv2 obligatorio. Sin IP pública, SSH ni puertos públicos de RabbitMQ o Airflow. La API Airflow solo escucha en loopback del host y se consulta mediante túnel SSM. El SG y rol `rabbitmq` existentes permanecen definidos pero no se asignan a esta EC2. No se modifican recursos existentes de la arquitectura v1.

**Secretos.** Terraform genera cuatro valores efímeros y los guarda como SecureString de SSM con atributos write-only: contraseña RabbitMQ, clave Fernet, JWT Airflow y contraseña PostgreSQL de metadatos. La contraseña RDS se lee de los parámetros SSM ya existentes. El arranque escribe `.env` local con permisos 0600. Ningún secreto en texto claro entra al repositorio ni a user_data. El archivo local contiene secretos y se elimina al destruir la instancia.

**Consecuencias.** La EC2 es un punto único de fallo: los dos workers no aportan alta disponibilidad de host. RabbitMQ y Airflow comparten CPU/RAM y los datos de colas/metadatos se pierden con la destrucción si no se respaldan. NAT y EC2 generan costo durante la ventana. IMDSv2 requiere hop limit 2 para contenedores. La subred privada necesita salida por NAT/endpoints hacia SSM, GitHub, registros de imágenes y S3.

**Aceptación.** Se debe conservar evidencia de formato, validación, Checkov, plan solo aditivo, acceso SSM, salud Compose, importación de DAG, lote de 100 eventos en S3 y destrucción sin huérfanos. Este ADR no afirma despliegue AWS. Para probar antes del merge, usar la rama del PR como `orquestacion_git_ref`; cambiar a `main` después de integrar.
