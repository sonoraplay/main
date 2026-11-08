---
sidebar_position: 1
title: "EG-47 · Runbook de operación"
---

# Runbook de operación de SonoraPlay (EG-47)

Cómo levantar el entorno desde cero, comprobar que cada pieza está sana, resolver los fallos más probables, rotar secretos y **destruir todo** (evita la penalización del −10 % por infraestructura viva).

> **Estado de este documento.** Escrito desde el repositorio el 2026-11-03. Los comandos de AWS **no se han vuelto a ejecutar** para escribirlo: cada paso remite a la guía donde ya se probó. El criterio 5 de la EG-47 (que otra persona levante y destruya todo siguiendo solo esto) **sigue pendiente**; ver §10.

## 0 · Qué existe y qué no

| Pieza | Dónde se define | ¿En Terraform? |
|---|---|---|
| VPC, NAT (EC2 `t4g.micro`), SG, S3 Bronze/Silver/Gold, RDS, IAM | `infra/terraform/` | Sí (EG-26) |
| ECS Fargate, ALB y API de sellos | `infra/terraform/ecs.tf`, `alb.tf` | Sí (EG-27) |
| Repositorios de ECR | `infra/terraform/ecr/` | Sí, **persistente** |
| Presupuesto y SNS | `infra/terraform/presupuesto/` | Sí, **persistente** |
| Una EC2 privada de orquestación (RabbitMQ + Airflow) | `infra/terraform/orquestacion.tf`, `docker-compose.aws.yml` | **Sí, declarada en la rama D3; despliegue AWS pendiente** (ADR-0024) |
| Job de Spark (Silver, fraude, liquidación) | — | **No todavía** (EG-35, EG-36, EG-37) |
| EKS | — | **No todavía** (EG-41) |

Cuando una pieza pase a Terraform, añade su paso a §1 y su comprobación a §2; `destruir-todo.sh` ya busca EC2, EBS, RDS, balanceadores, EIP, NAT Gateway y EKS vivos, estén o no en Terraform.

## 1 · Levantar desde cero

Requisitos: Terraform ≥ 1.11, AWS CLI v2, Docker con buildx, sesión de AWS en la cuenta del proyecto (`aws sso login --profile sonoraplay`). Sin access keys en archivos.

1. **Estado de Terraform (una sola vez).** `terraform -chdir=infra/terraform/bootstrap init && … apply`; copia `backend.hcl.example` a `backend.hcl` con el bucket que imprime.
2. **Persistentes (una sola vez).** ECR (`infra/terraform/ecr`) y presupuesto (`infra/terraform/presupuesto`, ver [EG-32](../infraestructura/eg32-presupuesto-alarma.md)).
3. **Imágenes.** `infra/scripts/publicar-imagen.sh api-titulares` (repite para cada servicio). Imprime la etiqueta (SHA del commit).
4. **Entorno.** `terraform -chdir=infra/terraform init -backend-config=backend.hcl`, luego `plan -out=ventana.tfplan` y `apply ventana.tfplan` (añade `-var api_titulares_imagen_tag=<sha>` para la API). Detalle y variables: `infra/terraform/README.md`.
5. **Datos (seed).** RDS es privada: corre el seed desde CloudShell **dentro de la VPC**, según [eg28-seed-rds.md](../infraestructura/eg28-seed-rds.md).
6. **Mensajería y Airflow en AWS (D3).** La EC2 privada `aws_instance.orquestacion` se crea con el `apply` anterior. Para probar la rama antes del merge, usar `-var orquestacion_git_ref=feature/D3-ec2-orquestacion`; el valor por defecto `main` solo sirve después del merge. El `user_data` instala Docker Compose, lee SSM y arranca exclusivamente RabbitMQ, `airflow-db`, los servicios Airflow y el consumidor (no arranca `postgres` ni `seed`). Ver comandos y criterios en §1.1. En local, conservar el Compose existente y su `.env` de desarrollo.
7. **DAGs.** Interfaz en `http://localhost:8080` por túnel SSM. Activa `sonoraplay_ingesta_diaria` y `sonoraplay_liquidacion_mensual`; define `SILVER_JOB_COMMAND` y `LIQUIDACION_JOB_COMMAND` cuando EG-35 / EG-37 existan (contratos en `docs/orquestacion/airflow-dags.md`, PR de EG-38).


> **Bloqueo / Blocker:** el arranque presupone que el catálogo F1 ya está publicado en `s3://<bronze>/f1/catalogo.parquet`, que RDS tiene esquema/seed y que existe la definición ECS Spark. Sin esas precondiciones, la EC2 puede arrancar, pero Silver/Gold no están validados de punta a punta. / Startup assumes the F1 catalog is already uploaded to `s3://<bronze>/f1/catalogo.parquet`, RDS is seeded and the ECS Spark task definition exists. Without these prerequisites, EC2 startup does not prove end-to-end Silver/Gold.

### 1.1 · D3 AWS — verificación operativa / operational verification

**Español.** No ejecutar `terraform apply` ni `destroy` fuera de una ventana autorizada. La EC2 no tiene IP pública ni SSH. Después de un `plan` revisado, recuperar el ID con `terraform -chdir=infra/terraform output -raw orquestacion_instance_id`. Iniciar sesión con `aws ssm start-session --target <instance-id> --region us-east-1`. El túnel de Airflow se obtiene con `terraform -chdir=infra/terraform output -raw orquestacion_ssm_airflow` y responde en `http://localhost:8080/api/v2/version`. Dentro de la EC2, comprobar `sudo docker compose -f docker-compose.yml -f docker-compose.airflow.yml -f docker-compose.aws.yml ps`, `sudo docker compose -f docker-compose.yml -f docker-compose.airflow.yml -f docker-compose.aws.yml logs --tail 100 airflow-dag-processor` y `sudo docker compose -f docker-compose.yml -f docker-compose.airflow.yml -f docker-compose.aws.yml exec airflow-scheduler airflow dags list`. Comprobar que hay dos workers. El productor es un servicio **a demanda**: preparar un archivo de 100 eventos F2 válidos en `data/processed/eventos_f2.jsonl` y ejecutar `sudo docker compose -f docker-compose.yml -f docker-compose.airflow.yml -f docker-compose.aws.yml run --rm --no-deps productor`; verificar objetos bajo `s3://<bronze>/f2/`. Guardar salidas y no afirmar éxito sin pruebas reales. `infra/scripts/destruir-todo.sh --dry-run` ya incluye la EC2 en el stack principal y la búsqueda de huérfanos.

**English.** Never run `terraform apply` or `destroy` outside an authorized window. This EC2 has neither a public IP nor SSH. After reviewing the plan, retrieve its ID with `terraform -chdir=infra/terraform output -raw orquestacion_instance_id`. Enter via `aws ssm start-session --target <instance-id> --region us-east-1`. Obtain the Airflow tunnel command from `terraform -chdir=infra/terraform output -raw orquestacion_ssm_airflow` and check `http://localhost:8080/api/v2/version`. On the EC2, inspect Compose status, Airflow DAG processor logs and `airflow dags list` using the three Compose files above; verify two workers. The producer is **on demand**: stage 100 valid F2 events in `data/processed/eventos_f2.jsonl`, run `docker compose ... run --rm --no-deps productor`, then check `s3://<bronze>/f2/`. Preserve actual outputs; do not claim success before execution. `infra/scripts/destruir-todo.sh --dry-run` already covers the EC2 through the main Terraform stack and orphan checks.

## 2 · Comprobar que cada componente está sano

| Componente | Comprobación | Esperado |
|---|---|---|
| Estado de Terraform | `terraform -chdir=infra/terraform plan` | «No changes» |
| RDS | `aws rds describe-db-instances --db-instance-identifier sonoraplay-dev --query 'DBInstances[0].[DBInstanceStatus,PubliclyAccessible]'` | `["available", false]` |
| Esquema y seed | `docker compose ps -a` (local) o `eg28-seed-rds.md` (AWS) | `seed` en `Exited (0)` |
| API de sellos | `infra/scripts/verificar-eg27.sh` | criterios 2 a 5 en verde; `GET /health` → 200 |
| API de contratos | `curl -fsS http://localhost:8000/health` | 200 |
| RabbitMQ | `docker compose ps rabbitmq` y consola `:15672` | `healthy`; vhost `airflow` existe |
| Airflow | `curl -fsS http://localhost:8080/api/v2/version`; `docker compose … ps airflow-worker` | 200; **2** workers `Up` |
| DAG diario | Interfaz → `sonoraplay_ingesta_diaria` → última corrida | tareas verdes; `spark_bronze_a_silver` «skipped» solo mientras falte EG-35 |
| Presupuesto | Consola de Budgets → `sonoraplay-mensual` | activo |
| Sin huérfanos | `infra/terraform/verificar-huerfanos.sh` | `OK` |

## 3 · Fallos más probables

| # | Síntoma | Causa | Solución |
|---|---|---|---|
| 1 | `apply` falla con `FreeTierRestrictionError` | Cuenta en plan gratuito: no admite 7 días de backups de RDS ni NAT `t4g.nano` | `-var rds_backup_retention_days=1 -var nat_instance_type=t4g.micro` (ADR-0022) |
| 2 | `destroy` se queda en la VPC / subred | Un entorno de CloudShell dentro de la VPC mantiene una interfaz de red | Elimina ese entorno de CloudShell (Actions → Delete) y repite `destroy` |
| 3 | `api-titulares` no arranca | `API_TITULARES_JWT_SECRET` conserva el valor falso del `.env.example` (ADR-0006) | Genera uno real (§4) y `docker compose up -d api-titulares` |
| 4 | `publicar-imagen.sh` rechaza la etiqueta | ECR es de etiquetas inmutables y el árbol tiene cambios | Haz commit; la etiqueta es el SHA del commit |
| 5 | La NAT no da salida a internet | Instancia NAT sin reglas aplicadas | `terraform apply -replace=aws_instance.nat` |
| 6 | `apply` interrumpido entre RDS y el parámetro SSM | Contraseña de RDS y SSM desfasadas | `-var rds_password_version=<n+1>` y `apply` |
| 7 | `cargar_tasas_f6` falla con «sin cobertura» o «más de 5 días» | Frankfurter sin cotización reciente (ADR-0021) | Reintenta; si persiste es la fuente: no se inventan tasas |
| 8 | El DAG mensual no sale de `esperar_ingesta_diaria` | Faltan días en `ingesta_diaria_estado` (p. ej. Silver omitido) | `SELECT d FROM generate_series(…) d LEFT JOIN ingesta_diaria_estado …` o revisa el DAG diario; no marques días a mano |
| 9 | `liquidar_mes` falla con `VersionNoCreada` | El job terminó sin publicar exactamente una liquidación nueva | Revisa el job de liquidación; la corrida queda en `corridas_liquidacion` con el detalle |
| 10 | `airflow-init` queda reiniciando | `AIRFLOW_FERNET_KEY` / `AIRFLOW_DB_PASSWORD` sin definir o vhost de RabbitMQ no creado | Completa `.env`; mira `docker compose logs airflow-rabbit-vhost` |

## 4 · Secretos: dónde viven y cómo rotarlos

| Secreto | Dónde | Cómo rotarlo |
|---|---|---|
| Contraseña de RDS | SSM `/sonoraplay/rds/password` (SecureString); no está en el estado de Terraform | `apply -var rds_password_version=<n+1>`: RDS y SSM cambian juntos |
| Firma JWT de la API de sellos | SSM `/sonoraplay/api-titulares/*` en AWS; `.env` en local | `-var jwt_secret_version=<n+1>`; en local, nuevo valor y reinicio. Invalida los tokens vigentes |
| RabbitMQ | SSM `/sonoraplay/rabbitmq/*` en AWS; `.env` local (`RABBITMQ_USER/PASSWORD`) | Cambia en SSM/`.env` y recrea los contenedores que lo usan |
| Airflow (Fernet, JWT, BD) | `.env` local (`AIRFLOW_*`); SSM `/sonoraplay/airflow/*` en la EC2 | Rotar `AIRFLOW_FERNET_KEY` exige re-cifrar conexiones: recrea el entorno si no hay datos que conservar |

Nunca se suben al repositorio: el job `secretos` del CI (gitleaks) revisa todo el historial. Genera valores con `python -c "import secrets; print(secrets.token_urlsafe(48))"`.

## 5 · Ventanas de encendido

Apagado por defecto ([ADR-0020](../adr/0020-ventanas-encendido-aws.md)): cada ventana es `apply` → prueba → `destroy` **el mismo día**. El presupuesto avisa, no bloquea.

## 6 · Destruir todo (script)

```bash
infra/scripts/destruir-todo.sh --dry-run            # ver qué haría, sin tocar AWS
infra/scripts/destruir-todo.sh                      # entorno de la ventana (pide confirmación)
infra/scripts/destruir-todo.sh --yes --persistentes # entrega: también ECR y presupuesto
```

Destruye (EKS si existe, entorno principal y, con `--persistentes`, ECR y presupuesto), corre `verificar-huerfanos.sh` y revisa EC2, EBS, EIP, NAT Gateways, RDS, balanceadores y EKS vivos. Sale con error si queda algo facturable.

## 7 · Comprobación final con Tag Editor o Cost Explorer

1. **Tag Editor** (Resource Groups → Tag Editor): región `us-east-1`, etiqueta `Project = sonoraplay`. Debe mostrar solo el bucket del estado (y, si no usaste `--persistentes`, ECR y presupuesto).
2. **Cost Explorer**: vista diaria, agrupada por servicio, del día siguiente: EC2, RDS, ELB y VPC deben estar en 0 USD. Los datos tardan hasta 24 h.
3. Guarda las capturas y la salida del script como evidencia de la EG-47.

## 8 · Datos que se pierden con `destroy`

RDS se recrea y se re-siembra (datos sintéticos, `SEED=42`); los metadatos de Airflow viven en un contenedor y se pierden; S3 se vacía salvo `-var destruccion_limpia=false`. Lo que no se puede regenerar (código, documentación, evidencias) está en el repositorio.

## 9 · Último paso: el bucket del estado

El bucket de `infra/terraform/bootstrap` es persistente. Solo después de entregar y de destruir todo lo demás: vacía el bucket (incluidas versiones) y `terraform -chdir=infra/terraform/bootstrap destroy`.

## 10 · Pendiente de comprobar (EG-47)

- [ ] Que otra persona levante y destruya todo siguiendo solo este documento (criterio 5).
- [ ] Ejecutar `destruir-todo.sh` de verdad en una ventana y guardar su salida y la comprobación de Tag Editor / Cost Explorer (criterio 2). Hoy se probó el modo `--dry-run`, la sintaxis y, con `aws` y `terraform` simulados (`tests/test_destruir_todo.py`, 18 pruebas), el orden, las comprobaciones de recursos facturables y los códigos de salida; contra AWS real, no.
- [ ] Validar y desplegar en AWS la EC2 de orquestación D3 (declarada en Terraform); verificar SSM, Compose, DAG y lote de 100 eventos. EKS (EG-41) sigue sujeto a ADR-0018.
