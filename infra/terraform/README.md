# Infraestructura en AWS con Terraform (EG-26)

Base de la plataforma en AWS (HU 17, E-06, temas 5–7):

- IAM de mínimo privilegio;
- VPC en 2 AZ con subredes públicas y privadas e instancia NAT;
- Data Lake en S3 por capas (Bronze, Silver, Gold);
- RDS PostgreSQL privado con backups (7 días en el diseño, 1 en el plan gratuito) y credenciales en SSM Parameter Store.

Decisiones: [ADR-0009](../../docs/adr/0009-region-aws.md) (región), [ADR-0010](../../docs/adr/0010-instancia-nat.md) (instancia NAT), [ADR-0011](../../docs/adr/0011-terraform.md) (Terraform) y [ADR-0020](../../docs/adr/0020-ventanas-encendido-aws.md) (entorno apagado por defecto).

> **Cuesta dinero.** `terraform apply` crea recursos que se cobran por hora: RDS ≈ 0,02 USD/h y la NAT ≈ 0,01 USD/h. Cada ventana de prueba es `apply` → prueba → `destroy` **el mismo día** (ADR-0020).

## Qué crea

| Archivo | Recursos | Criterio |
|---|---|---|
| `red.tf` | VPC `10.0.0.0/16`, 2 subredes públicas y 2 privadas en 2 AZ, Internet Gateway, tablas de rutas, endpoint gateway de S3, instancia NAT `t4g.micro` (`nat_instance_type`) con alarma de recuperación, SG por defecto sin reglas | 2 |
| `security_groups.tf` | Los 10 SG de la arquitectura v1 (sección 3); cada uno solo acepta tráfico de otro SG, salvo el ALB y la NAT | 2 |
| `s3.tf` | Buckets `sonoraplay-<cuenta>-bronze`, `-silver` y `-gold`: SSE-S3, Block Public Access, sin ACL, solo TLS | 4 |
| `rds.tf` | PostgreSQL 16 `db.t4g.micro`, Single-AZ, 20 GB gp3 cifrados, `publicly_accessible = false`, backups de `rds_backup_retention_days` días (7 en el diseño, 1 mientras dure el plan gratuito: [ADR-0022](../../docs/adr/0022-excepcion-plan-gratuito-rds-nat.md)), TLS obligatorio; parámetros `/sonoraplay/rds/*` en SSM | 5 |
| `iam.tf` | Por servicio de ECS (api-titulares, api-contratos, simulador, consumidor, spark): rol de ejecución y rol de tarea. Por EC2 (nat, rabbitmq, airflow): rol y perfil de instancia | 3 |
| `bootstrap/` | Bucket del estado de Terraform (persistente, se crea una sola vez) | — |
| `ecs.tf` (EG-27) | Clúster `sonoraplay-dev` con FARGATE y FARGATE_SPOT, grupos de logs `/ecs/sonoraplay/<servicio>` (7 días), secreto JWT en SSM y, con `api_titulares_imagen_tag`, la definición de tarea ARM64 y el servicio de la API de titulares en subredes privadas | EG-27: 2, 4, 5 |
| `alb.tf` (EG-27) | ALB público en 2 AZ, target group con health check en `/health`, listener 80 (y 443 si hay `certificado_acm_arn`). Solo existe con `api_titulares_imagen_tag` | EG-27: 3 |
| `ecr/` (EG-27) | Repositorios `sonoraplay/<servicio>` con etiquetas inmutables, escaneo y ciclo de vida. **Persistente**, con su propio estado (`sonoraplay/ecr.tfstate`) | EG-27: 1 |

Todo lleva `Project=sonoraplay`, `Environment=dev` y `ManagedBy=terraform` (`default_tags`).

**Fuera de esta historia:**
- el ALB y ECS: HU 18 (EG-27, ver abajo);
- las EC2 de RabbitMQ y Airflow: HU 20 y 25;
- ECR: persistente;
- CloudTrail: HU 31;
- OIDC para GitHub Actions: EG-40 / ADR-0017.

Los roles de IAM y los SG de esos servicios ya existen aquí. Sus historias deben usar los nombres por convención que esperan las políticas:

| Recurso | Nombre esperado |
|---|---|
| Repositorio de ECR | `sonoraplay/<servicio>` |
| Grupo de logs | `/ecs/sonoraplay/<servicio>` |
| Clúster de ECS | `sonoraplay-dev` |
| Definición de tarea de Spark | `sonoraplay-dev-spark` |
| Prefijos de F6 y F7 en Bronze | `f6/` y `f7/` |

## Permisos de cada rol

| Servicio | Rol de ejecución (agente de ECS) | Rol de tarea o de la EC2 (código) |
|---|---|---|
| api-titulares | Su imagen de ECR, su grupo de logs, `/sonoraplay/rds/*` y `/sonoraplay/api-titulares/*` | Ninguno |
| api-contratos | Su imagen, sus logs, `/sonoraplay/rds/*` | Ninguno |
| simulador | Su imagen, sus logs, `/sonoraplay/rabbitmq/*` | Ninguno |
| consumidor | Su imagen, sus logs, `/sonoraplay/rabbitmq/*` | `s3:PutObject` en Bronze (no lee ni borra) |
| spark | Su imagen, sus logs, `/sonoraplay/rds/*` | Lee Bronze, Silver y Gold; escribe y borra solo en Silver y Gold |
| nat (EC2) | — | Session Manager |
| rabbitmq (EC2) | — | Session Manager y `/sonoraplay/rabbitmq/*` |
| airflow (EC2) | — | Session Manager, `/sonoraplay/{airflow,rds,rabbitmq}/*`, `ecs:RunTask` solo de la tarea de Spark en el clúster `sonoraplay-dev`, `iam:PassRole` solo de los roles de Spark, y `s3:PutObject` en `bronze/f6/` y `bronze/f7/` |

No hay usuarios IAM ni access keys. Los roles de ECS solo los puede asumir ECS desde esta cuenta y región (`aws:SourceAccount` y `aws:SourceArn`).

## API de titulares en ECS Fargate (EG-27)

Decisión: [ADR-0012](../../docs/adr/0012-fargate-on-demand-spot-arm64.md). Guía y evidencia: [docs/infraestructura/eg27-api-ecs-fargate.md](../../docs/infraestructura/eg27-api-ecs-fargate.md).

```bash
# Una sola vez (persistente): repositorios de ECR.
terraform -chdir=infra/terraform/ecr init -backend-config=../backend.hcl
terraform -chdir=infra/terraform/ecr apply

# En cada versión: imagen arm64 etiquetada con el SHA del commit (criterio 1).
infra/scripts/publicar-imagen.sh api-titulares          # imprime la etiqueta, p. ej. a1b2c3d

# En la ventana: el entorno de la EG-26 + la API (ALB, tarea versionada y servicio).
terraform -chdir=infra/terraform apply -var api_titulares_imagen_tag=a1b2c3d
infra/scripts/verificar-eg27.sh                          # criterios 2 a 5

# Para cargar datos, RDS debe tener el esquema y el seed (ver el demo de la EG-26).
```

Sin `api_titulares_imagen_tag`, `apply` crea solo el clúster vacío y los grupos de logs: una ventana de la EG-26 no paga el ALB (≈ 0,02 USD/h).


La cuenta del proyecto está en el **plan gratuito**. Ese plan rechaza dos valores del diseño original:

| Diseño (arquitectura v1) | Plan gratuito | Variable | Con plan pago |
|---|---|---|---|
| Backups de RDS de 7 días | Máximo 1 día (`FreeTierRestrictionError`) | `rds_backup_retention_days = 1` | `7` |
| NAT `t4g.nano` | Solo tipos elegibles para la capa gratuita | `nat_instance_type = "t4g.micro"` | `"t4g.nano"` |

Julián aprobó la excepción del criterio 5 (backups de 1 día) mientras la cuenta siga en el plan gratuito (PR #4).

## Desde AWS CloudShell

CloudShell sirve para las ventanas de prueba sin instalar nada en el PC, pero su `$HOME` solo tiene 1 GB y el proveedor de AWS pesa varios cientos de MB. Clona el repo y guarda los proveedores en `/tmp`:

```bash
export TF_PLUGIN_CACHE_DIR=/tmp/tf-plugin-cache && mkdir -p "$TF_PLUGIN_CACHE_DIR"
git clone https://github.com/sonoraplay/main.git /tmp/sonoraplay && cd /tmp/sonoraplay
```

`/tmp` se borra al cerrar la sesión, pero el estado vive en S3: basta volver a hacer `terraform init -backend-config=backend.hcl`. Un entorno de CloudShell **dentro de la VPC** (para llegar a RDS) no permite subir archivos, y su interfaz de red impide el `destroy` de la VPC: hay que borrar ese entorno antes del paso 3.

## Requisitos

- Terraform ≥ 1.11 (el CI usa 1.16.6) y AWS CLI v2.
- Una sesión de AWS con permisos de administración en la cuenta del proyecto, por ejemplo `aws sso login --profile sonoraplay`. **No uses access keys guardadas en archivos del repo.**

## Una ventana de prueba, paso a paso

```bash
export AWS_PROFILE=sonoraplay

# 0. Solo la primera vez: bucket del estado (persistente).
terraform -chdir=infra/terraform/bootstrap init
terraform -chdir=infra/terraform/bootstrap apply
cp infra/terraform/backend.hcl.example infra/terraform/backend.hcl
# ...y pon en backend.hcl el bucket que imprime:
terraform -chdir=infra/terraform/bootstrap output -raw bucket_estado

# 1. Crear el entorno.
terraform -chdir=infra/terraform init -backend-config=backend.hcl
terraform -chdir=infra/terraform plan -out=ventana.tfplan
terraform -chdir=infra/terraform apply ventana.tfplan

# 2. Probar (ver "Cómo se verifica cada criterio").

# 3. Destruir el mismo día y comprobar que no quedan huérfanos.
terraform -chdir=infra/terraform destroy
./infra/terraform/verificar-huerfanos.sh
```

Guarda en la HU 17 la salida de `apply`, la de `destroy` y la del script como evidencia.

## Cómo se verifica cada criterio

1. **`apply` y `destroy` sin huérfanos.** `destroy` termina sin errores y `verificar-huerfanos.sh` imprime `OK`.
   - El script busca recursos con `Project=sonoraplay` usando la API de etiquetas, y roles y perfiles de IAM que empiecen por `sonoraplay-`.
   - Solo ignora el bucket del estado.
2. **VPC.**
   - `aws ec2 describe-subnets --filters Name=tag:Project,Values=sonoraplay` muestra 4 subredes en 2 AZ.
   - `aws ec2 describe-instances` muestra que solo la NAT está en una subred `Tier=publica`.
3. **IAM.**
   - `terraform output roles_ecs` lista un rol de ejecución y uno de tarea por servicio.
   - `aws iam list-users` no muestra usuarios del proyecto.
   - El job `secretos` del CI (gitleaks) no encuentra llaves en el historial.
4. **S3.** En cada bucket de `terraform output buckets`, `aws s3api get-public-access-block --bucket <b>` muestra los cuatro valores en `true` y `aws s3api get-bucket-encryption --bucket <b>` muestra `AES256`.
5. **RDS.**
   - `aws rds describe-db-instances --db-instance-identifier sonoraplay-dev --query 'DBInstances[0].[PubliclyAccessible,BackupRetentionPeriod,StorageEncrypted]'` devuelve `[false, 7, true]` (`[false, 1, true]` mientras dure el plan gratuito, ADR-0022).
   - `aws ssm get-parameter --name /sonoraplay/rds/password --with-decryption` devuelve la contraseña.
   - `terraform state pull | grep -c "<contraseña>"` devuelve `0`: la contraseña no está en el estado.
6. **NAT** (ADR-0010). Desde una instancia privada, `curl -s https://checkip.amazonaws.com` devuelve la IP pública de la NAT.

## Conectarse a RDS

RDS no tiene IP pública. Desde la EC2 de Airflow (HU 25), que es el host del túnel (flujo ⑫):

```bash
aws ssm start-session --target <id-de-la-ec2-airflow> \
  --document-name AWS-StartPortForwardingSessionToRemoteHost \
  --parameters host=<rds_endpoint>,portNumber=5432,localPortNumber=5433
```

Mientras la EC2 de Airflow no exista, RDS solo es alcanzable desde dentro de la VPC.

## Operación

- **Rotar la contraseña de RDS:** sube `rds_password_version` (por ejemplo, `-var rds_password_version=2`) y aplica. RDS y SSM reciben la nueva contraseña en el mismo `apply`. Esto también arregla un `apply` que se interrumpió entre la creación de RDS y la del parámetro.
- **Conservar datos entre ventanas:** `-var destruccion_limpia=false` deja la protección contra borrado y un snapshot final en RDS, y no vacía los buckets. En ese caso `destroy` **no** deja la cuenta limpia y hay que borrar esos recursos a mano antes de la entrega.
- **La NAT no da salida:** `terraform apply -replace=aws_instance.nat`.

## Validación sin AWS (lo que corre el CI)

```bash
terraform fmt -check -recursive infra/terraform
terraform -chdir=infra/terraform init -backend=false && terraform -chdir=infra/terraform validate
terraform -chdir=infra/terraform/bootstrap init -backend=false && terraform -chdir=infra/terraform/bootstrap validate
uvx checkov==3.3.29 -d infra/terraform --config-file infra/terraform/.checkov.yaml
```

Las excepciones de Checkov y su motivo están en `.checkov.yaml`.
