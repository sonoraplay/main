# Job de Spark (EG-35 Silver / EG-37 Gold) como definición de tarea de ECS Fargate.
#
# Solo la definición: no hay servicio. Airflow lanza la tarea con `ecs:RunTask` (iam.tf, política
# "LanzaSpark" sobre `${local.nombre}-spark:*`) y le pasa el comando y los parámetros de la
# corrida (período, run_id) como sobrescritura de `command`. Sin var.spark_imagen_tag no se crea.
# Los roles de ejecución y de tarea, el grupo de logs y el grupo de seguridad ya existen (iam.tf,
# ecs.tf, security_groups.tf); aquí solo se arma la tarea.

locals {
  spark_activa = var.spark_imagen_tag != ""
}

data "aws_ecr_repository" "spark" {
  count = local.spark_activa ? 1 : 0
  name  = "${var.ecr_repositorio_prefijo}/spark"
}

resource "aws_ecs_task_definition" "spark" {
  count = local.spark_activa ? 1 : 0

  family                   = "${local.nombre}-spark"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.spark_cpu
  memory                   = var.spark_memoria
  execution_role_arn       = aws_iam_role.ecs_ejecucion["spark"].arn
  task_role_arn            = aws_iam_role.ecs_tarea["spark"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64" # ADR-0012; la imagen se construye arm64 (publicar-imagen.sh)
  }

  # Raíz de solo lectura; Spark escribe sus temporales en /tmp (SPARK_LOCAL_DIRS).
  volume {
    name = "tmp"
  }

  container_definitions = jsonencode([
    {
      name                   = "spark"
      image                  = "${data.aws_ecr_repository.spark[0].repository_url}:${var.spark_imagen_tag}"
      essential              = true
      readonlyRootFilesystem = true
      mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]

      environment = concat(
        [
          { name = "DB_SSLMODE", value = "require" }, # RDS tiene rds.force_ssl = 1
          { name = "SONORAPLAY_BRONZE_PATH", value = "s3a://${aws_s3_bucket.capa["bronze"].bucket}/f2" },
          { name = "SONORAPLAY_SILVER_PATH", value = "s3a://${aws_s3_bucket.capa["silver"].bucket}/silver" },
          { name = "SONORAPLAY_QUARANTINE_PATH", value = "s3a://${aws_s3_bucket.capa["silver"].bucket}/quarantine" },
          { name = "SONORAPLAY_GOLD_PATH", value = "s3a://${aws_s3_bucket.capa["gold"].bucket}" },
        ],
        var.spark_catalogo_ruta == "" ? [] : [
          { name = "SONORAPLAY_CATALOG_PATH", value = var.spark_catalogo_ruta },
        ],
      )

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
