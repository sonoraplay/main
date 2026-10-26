# ECS Fargate (EG-27, temas 8–9, ADR-0012): clúster, logs y la API de titulares (RF-05).
#
# - Clúster y grupos de logs: siempre (no cuestan nada vacíos).
# - Definición de tarea, servicio y ALB (alb.tf): solo con var.api_titulares_imagen_tag, para
#   que una ventana que no prueba la API no pague el ALB.
# - La tarea corre en subredes privadas sin IP pública; baja la imagen de ECR y manda logs a
#   CloudWatch por la instancia NAT (red.tf).

locals {
  api_activa = var.api_titulares_imagen_tag != ""
  api_https  = var.certificado_acm_arn != ""
  api_puerto = 8000
}

# --- Secreto JWT de la API de sellos (ADR-0006) ------------------------------------------------
# Igual que la contraseña de RDS: se genera en cada apply, viaja a SSM por un atributo
# write-only y no queda en el estado. Para rotarlo se sube jwt_secret_version.

ephemeral "random_password" "jwt" {
  length  = 64
  special = false # va en un encabezado HTTP firmado; basta la longitud
}

resource "aws_ssm_parameter" "jwt_secret" {
  name             = "${local.ssm_prefijo}/api-titulares/jwt_secret"
  description      = "Clave HS256 de los tokens de sellos (ADR-0006, EG-27)"
  type             = "SecureString"
  value_wo         = ephemeral.random_password.jwt.result
  value_wo_version = var.jwt_secret_version
}

# --- Clúster y logs -------------------------------------------------------------------------

resource "aws_ecs_cluster" "principal" {
  name = local.ecs_cluster # sonoraplay-dev, el nombre que ya esperan las políticas de iam.tf

  setting {
    name  = "containerInsights"
    value = "disabled" # costo extra sin requisito; los logs y las métricas básicas bastan
  }
}

resource "aws_ecs_cluster_capacity_providers" "principal" {
  cluster_name       = aws_ecs_cluster.principal.name
  capacity_providers = ["FARGATE", "FARGATE_SPOT"] # Spot para simulador, consumidor y Spark

  default_capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }
}

# Un grupo por servicio de ECS, con el nombre que espera su rol de ejecución (iam.tf).
resource "aws_cloudwatch_log_group" "ecs" {
  for_each = local.servicios_ecs

  name              = "/ecs/${var.proyecto}/${each.key}"
  retention_in_days = var.logs_retencion_dias # criterio 5: 7 días
}

# --- API de titulares -----------------------------------------------------------------------

data "aws_ecr_repository" "api_titulares" {
  count = local.api_activa ? 1 : 0
  name  = "${var.ecr_repositorio_prefijo}/api-titulares"
}

resource "aws_ecs_task_definition" "api_titulares" {
  count = local.api_activa ? 1 : 0

  # Criterio 2: cada apply con otra imagen crea una revisión nueva (family:N); las anteriores
  # quedan para volver atrás.
  family                   = "${local.nombre}-api-titulares"
  requires_compatibilities = ["FARGATE"]
  network_mode             = "awsvpc"
  cpu                      = var.api_titulares_cpu
  memory                   = var.api_titulares_memoria
  execution_role_arn       = aws_iam_role.ecs_ejecucion["api-titulares"].arn
  task_role_arn            = aws_iam_role.ecs_tarea["api-titulares"].arn

  runtime_platform {
    operating_system_family = "LINUX"
    cpu_architecture        = "ARM64" # ADR-0012: Graviton, ≈ 20 % más barato que x86
  }

  # Raíz de solo lectura; /tmp es el único lugar escribible.
  volume {
    name = "tmp"
  }

  container_definitions = jsonencode([
    {
      name                   = "api-titulares"
      image                  = "${data.aws_ecr_repository.api_titulares[0].repository_url}:${var.api_titulares_imagen_tag}"
      essential              = true
      readonlyRootFilesystem = true
      portMappings           = [{ containerPort = local.api_puerto, protocol = "tcp" }]
      mountPoints            = [{ sourceVolume = "tmp", containerPath = "/tmp", readOnly = false }]

      environment = [
        { name = "DB_SSLMODE", value = "require" }, # RDS tiene rds.force_ssl = 1
      ]

      # Los valores salen de SSM en el arranque; ni Terraform ni el repo los ven.
      secrets = [
        { name = "DB_HOST", valueFrom = aws_ssm_parameter.rds_conexion["host"].arn },
        { name = "DB_PORT", valueFrom = aws_ssm_parameter.rds_conexion["port"].arn },
        { name = "DB_NAME", valueFrom = aws_ssm_parameter.rds_conexion["dbname"].arn },
        { name = "DB_USER", valueFrom = aws_ssm_parameter.rds_conexion["username"].arn },
        { name = "DB_PASSWORD", valueFrom = aws_ssm_parameter.rds_password.arn },
        { name = "API_TITULARES_JWT_SECRET", valueFrom = aws_ssm_parameter.jwt_secret.arn },
      ]

      # El mismo chequeo que el Dockerfile: si falla 3 veces, ECS reemplaza la tarea (criterio 4).
      healthCheck = {
        command = [
          "CMD", "python", "-c",
          "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:${local.api_puerto}/health', timeout=2).status != 200)",
        ]
        interval    = 15
        timeout     = 3
        retries     = 3
        startPeriod = 15
      }

      logConfiguration = {
        logDriver = "awslogs"
        options = {
          awslogs-group         = aws_cloudwatch_log_group.ecs["api-titulares"].name
          awslogs-region        = var.region
          awslogs-stream-prefix = "api"
        }
      }
    }
  ])
}

resource "aws_ecs_service" "api_titulares" {
  count = local.api_activa ? 1 : 0

  name            = "api-titulares"
  cluster         = aws_ecs_cluster.principal.id
  task_definition = aws_ecs_task_definition.api_titulares[0].arn
  desired_count   = var.api_titulares_tareas

  # ADR-0012: On-Demand. La API atiende a los sellos; una interrupción de Spot la dejaría caída.
  capacity_provider_strategy {
    capacity_provider = "FARGATE"
    weight            = 1
  }

  network_configuration {
    subnets          = [for s in aws_subnet.privada : s.id] # criterio 2
    security_groups  = [local.sg["api-titulares"]]
    assign_public_ip = false
  }

  load_balancer {
    target_group_arn = aws_lb_target_group.api_titulares[0].arn
    container_name   = "api-titulares"
    container_port   = local.api_puerto
  }

  health_check_grace_period_seconds  = 30
  deployment_minimum_healthy_percent = 100
  deployment_maximum_percent         = 200

  # Una versión que no pasa el health check se revierte sola a la anterior.
  deployment_circuit_breaker {
    enable   = true
    rollback = true
  }

  propagate_tags        = "SERVICE"
  wait_for_steady_state = true # el apply falla si la API no queda sana

  # Con certificado, el target group cuelga del listener 443 (el 80 solo redirige): sin esta
  # dependencia, ECS puede crear el servicio antes y fallar con "el target group no tiene un
  # balanceador asociado". Con count = 0 (sin certificado) la dependencia no hace nada.
  depends_on = [aws_lb_listener.http, aws_lb_listener.https, aws_cloudwatch_log_group.ecs]
}
