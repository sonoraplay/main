# Jobs de Spark (EG-35 Silver y EG-37 Gold) como definición de tarea de ECS Fargate.
#
# Sin servicio ni ALB: Airflow lanza cada job con RunTask sobre esta definición y sobrescribe el
# comando (python -m sonoraplay.spark.silver | gold). Los permisos ya existen: el rol de tarea
# `spark` (S3 de las capas, iam.tf), el rol de ejecución (SSM de RDS, logs) y la regla del
# security group `spark` hacia RDS. Solo con var.spark_imagen_tag, igual que la API.

variable "spark_arquitectura" {
  description = "Arquitectura de la tarea de Spark. ARM64 (ADR-0012) es la oficial; X86_64 solo si no hay dónde construir arm64 (la imagen debe coincidir)."
  type        = string
  default     = "ARM64"

  validation {
    condition     = contains(["ARM64", "X86_64"], var.spark_arquitectura)
    error_message = "spark_arquitectura debe ser ARM64 o X86_64."
  }
}

locals {
  spark_activo = var.spark_imagen_tag != ""
}

data "aws_ecr_repository" "spark" {
  count = local.spark_activo ? 1 : 0
  name  = "${var.ecr_repositorio_prefijo}/spark"
}

resource "aws_ecs_task_definition" "spark" {
  count = local.spark_activo ? 1 : 0

  # Cada apply con otra imagen crea una revisión nueva (family:N); RunTask sin revisión usa la
  # última activa y las anteriores quedan para volver atrás.
  family                   = "${local.nombre}-spark"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.spark_cpu
  memory                   = var.spark_memoria
  execution_role_arn       = aws_iam_role.ecs_ejecucion["spark"].arn
  task_role_arn            = aws_iam_role.ecs_tarea["spark"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = var.spark_arquitectura # ADR-0012: ARM64 por defecto; la imagen debe coincidir
  }

  # Raíz ESCRIBIBLE a propósito. El primer intento (2026-11-08) usaba raíz de solo lectura y un
  # volumen en /tmp, y la tarea murió al arrancar Spark: "No usable temporary directory found".
  # En Fargate un volumen vacío montado en /tmp pertenece a root y el contenedor corre como
  # `app` (uid 10001), así que /tmp no era escribible y la raíz tampoco. Spark y Python escriben
  # en /tmp, en el directorio de usuario y en cachés; este job es de una sola ejecución, sin
  # puertos de entrada ni datos persistentes.
  # checkov:skip=CKV_AWS_336:job batch efímero; Spark necesita /tmp escribible (ver comentario)

  container_definitions = jsonencode([
    {
      name                   = "spark"
      image                  = "${data.aws_ecr_repository.spark[0].repository_url}:${var.spark_imagen_tag}"
      essential              = true
      readonlyRootFilesystem = false

      environment = [
        { name = "AWS_REGION", value = var.region },
        { name = "DB_SSLMODE", value = "require" }, # RDS tiene rds.force_ssl = 1
        { name = "SPARK_DRIVER_MEMORY", value = "${floor(var.spark_memoria * 0.75)}m" },
      ]

      # Los valores salen de SSM en el arranque; ni Terraform ni el repo los ven.
      secrets = [
        { name = "DB_HOST", valueFrom = aws_ssm_parameter.rds_conexion["host"].arn },
        { name = "DB_PORT", valueFrom = aws_ssm_parameter.rds_conexion["port"].arn },
        { name = "DB_NAME", valueFrom = aws_ssm_parameter.rds_conexion["dbname"].arn },
        { name = "DB_USER", valueFrom = aws_ssm_parameter.rds_conexion["username"].arn },
        { name = "DB_PASSWORD", valueFrom = aws_ssm_parameter.rds_password.arn },
      ]

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs["spark"].name
          awslogs-region        = var.region
          awslogs-stream-prefix = "spark"
        }
      }
    }
  ])
}
