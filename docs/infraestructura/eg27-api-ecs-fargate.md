---
sidebar_position: 2
title: "EG-27 · API en ECS Fargate con ALB / API on ECS Fargate with ALB"
---

# EG-27 · API de titulares en ECS Fargate detrás de un ALB / Rights holder API on ECS Fargate behind an ALB

## Español

**Sprint 3 · HU 18 · temas 8–9.** La API de sellos (EG-21) corre como tarea de ECS Fargate ARM64 en subredes privadas, detrás de un ALB público. Su imagen vive en ECR con el SHA del commit como etiqueta. Decisión de cómputo: [ADR-0012](../adr/0012-fargate-on-demand-spot-arm64.md).

**Estado (21 oct 2026): preparada para desplegar.** El Terraform valida y pasa Checkov, y la imagen y la configuración de la tarea se probaron en local. Falta correrla en la próxima ventana de AWS ([ADR-0020](../adr/0020-ventanas-encendido-aws.md)).

### Qué se crea y qué criterio cubre

| Criterio de la EG-27 | Cómo se cumple | Dónde |
|---|---|---|
| 1 · Imagen arm64 en ECR con el SHA del commit | Repositorios `sonoraplay/<servicio>` con etiquetas **inmutables** y escaneo al subir. `publicar-imagen.sh` construye `linux/arm64`, etiqueta con `git rev-parse --short HEAD` y se niega si hay cambios sin commit | `infra/terraform/ecr/`, `infra/scripts/publicar-imagen.sh` |
| 2 · Definición de tarea versionada en subredes privadas | `family = sonoraplay-dev-api-titulares`: cada imagen nueva crea `family:N+1`. Servicio en las 2 subredes privadas con `assign_public_ip = false` | `ecs.tf` |
| 3 · `/health` responde 200 por el ALB; el target group lo usa | Target group `ip` en el puerto 8000 con health check `GET /health` → 200 (cada 15 s, 3 fallos = enfermo) | `alb.tf` |
| 4 · ECS reemplaza una tarea enferma | Health check del contenedor (el mismo del Dockerfile) + target group. *Circuit breaker* con rollback si una versión nueva no queda sana. `wait_for_steady_state` hace fallar el `apply` si la API no arranca | `ecs.tf` |
| 5 · Logs en CloudWatch con 7 días | `awslogs` hacia `/ecs/sonoraplay/api-titulares`, `retention_in_days = 7` | `ecs.tf` |
| 6 · ADR-0012 | Fargate ARM64, On-Demand para las APIs, Spot para lo que tolera interrupciones | `docs/adr/0012-…` |

**Seguridad:**

- La tarea no recibe ningún secreto en texto. ECS lee de SSM al arrancar `/sonoraplay/rds/{host,port,dbname,username,password}` y `/sonoraplay/api-titulares/jwt_secret`.
- La clave JWT se genera como la contraseña de RDS: con un recurso efímero y un atributo write-only, así que nunca queda en el estado.
- `config.database_url()` arma la conexión con esas variables y codifica la contraseña para URL. `DB_SSLMODE=require`, porque RDS exige TLS.
- La raíz del contenedor es de solo lectura; solo `/tmp` es escribible.

### Dependencias de Terraform (coordinación con Julián)

| Dependencia | Estado | Qué falta |
|---|---|---|
| VPC, subredes, NAT, SG `alb` y `api-titulares`, regla ALB → 8000, regla `api-titulares` → RDS 5432 | ✅ en `develop` (EG-26, PR #8) | — |
| Roles de ejecución y de tarea de `api-titulares` (ECR, logs y SSM propios) | ✅ en la EG-26 | — |
| Arreglos de la ventana del 19 oct: `depends_on` de la contraseña de SSM hacia RDS y `rds.force_ssl` con `pending-reboot` | ✅ en `develop` (commit `f9fd9f1`, PR #8) | — |
| RDS con esquema y datos (DDL + seed) para que `/me/reportes` devuelva algo | ⚠️ manual | En la ventana, correr el DDL y el seed desde el CloudShell dentro de la VPC (como en la prueba del 15 oct) o con una tarea de ECS del seed (historia aparte) |
| Dominio y certificado de ACM para HTTPS | ❌ no hay dominio | Sin certificado, el ALB sirve HTTP en el 80, solo para pruebas con datos sintéticos. Con `certificado_acm_arn`, el 80 redirige a 443 |
| Repositorios de ECR | Nuevo stack persistente `infra/terraform/ecr` | Aplicarlo una vez antes de la ventana |

### Evidencia local (21 oct 2026)

La imagen se construyó para `linux/arm64` y se corrió como la correría ECS:

- raíz de solo lectura y `/tmp` escribible;
- sin `DATABASE_URL`, solo con las variables `DB_*` y `API_TITULARES_JWT_SECRET`;
- contra el Postgres del esqueleto (EG-24).

```text
arquitectura=arm64 os=linux
ReadonlyRootfs=true Tmpfs=map[/tmp:] Health=healthy
GET /health -> {"status":"ok"} HTTP 200
GET /me/reportes?periodo=2026-09 (token del titular fb950a36…) -> HTTP 200
  regalia_usd 2340.00 · reproducciones_validas 1 · liquidacion_id 302bccfb-…
touch /app/x -> Read-only file system · /tmp escribible
```

Además:

- `terraform validate` pasa en `infra/terraform` y en `infra/terraform/ecr`.
- Checkov: 314 checks pasan, 0 fallan. Las excepciones nuevas están justificadas en `.checkov.yaml`.
- `tests/test_config_database_url.py`: 4 passed.

### Cómo desplegar en la próxima ventana

```bash
terraform -chdir=infra/terraform/ecr init -backend-config=../backend.hcl && terraform -chdir=infra/terraform/ecr apply
infra/scripts/publicar-imagen.sh api-titulares                # imprime la etiqueta (SHA)
terraform -chdir=infra/terraform apply -var api_titulares_imagen_tag=<SHA>
# Esquema y seed en RDS (desde la VPC), luego:
infra/scripts/verificar-eg27.sh                               # criterios 2 a 5
terraform -chdir=infra/terraform destroy                      # el mismo día (ADR-0020)
```

Costo de la ventana con la API: lo de la EG-26 (RDS ≈ 0,02 USD/h y NAT ≈ 0,01 USD/h) más el ALB (≈ 0,0225 USD/h + LCU) y una tarea de 0,25 vCPU / 0,5 GB ARM (≈ 0,01 USD/h). Son unos 0,07 USD por hora de ventana.

## English

**Sprint 3 · HU 18 · topics 8–9.** The labels API (EG-21) runs as an ARM64 ECS Fargate task in private subnets behind a public ALB. Its image is stored in ECR, tagged with the commit SHA. Compute decision: [ADR-0012](../adr/0012-fargate-on-demand-spot-arm64.md).

**Status (Oct 21, 2026): ready to deploy.** The Terraform validates and passes Checkov, and the image and task configuration were tested locally. It runs on AWS in the next test window (ADR-0020).

**How each criterion is met:**

- **1 · Image:** immutable ECR tags and a push script that builds `linux/arm64` and tags with the commit SHA.
- **2 · Task and network:** a versioned task definition (`family:N`) in private subnets without public IPs.
- **3 · Health check:** the target group checks `GET /health` → 200.
- **4 · Replacement:** a container health check plus a deployment circuit breaker with rollback.
- **5 · Logs:** `awslogs` to `/ecs/sonoraplay/api-titulares` with 7-day retention.

**Security:** secrets are read from SSM at task start. The JWT key is generated with an ephemeral resource and stored through a write-only attribute, so it never reaches the state. `config.database_url()` builds the connection from the injected `DB_*` variables. The root filesystem is read-only.

**Dependencies (coordinated with Julián):**

- EG-26 is already merged into `develop` (PR #8), including the RDS/SSM password and `rds.force_ssl` fixes (`f9fd9f1`).
- RDS needs schema and seed data loaded inside the VPC.
- HTTPS needs a domain and an ACM certificate. Until then, test windows serve HTTP on port 80 with synthetic data only.

**Local evidence:** the arm64 image ran with a read-only root and only `DB_*` variables against the skeleton's Postgres. `/health` → 200 and `/me/reportes` → 200 (2340.00 USD, settlement `302bccfb…`). Terraform validates, Checkov reports 0 failures, and the new config tests pass.
