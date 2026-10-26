# IAM de mínimo privilegio (criterio 3 de la EG-26, tema 5).
#
# - Cada servicio tiene su propio rol; ninguno comparte permisos con otro.
# - No hay usuarios IAM ni access keys: las tareas de ECS y las EC2 usan roles, el equipo entra
#   con SSO/SSM y GitHub Actions con OIDC (ADR-0017, EG-40).
# - Los recursos que todavía no existen (repositorios de ECR, grupos de logs, clúster de ECS)
#   se nombran por convención; sus historias deben respetar estos nombres.
#
# Servicios en ECS Fargate: un rol de ejecución (lo usa el agente de ECS para bajar la imagen,
# escribir logs y leer secretos) y un rol de tarea (lo usa el código).

locals {
  ecs_cluster = local.nombre

  arn_s3   = { for c in local.capas : c => aws_s3_bucket.capa[c].arn }
  arn_ssm  = "arn:${local.particion}:ssm:${var.region}:${local.cuenta}:parameter${local.ssm_prefijo}"
  arn_ecr  = "arn:${local.particion}:ecr:${var.region}:${local.cuenta}:repository/${var.ecr_repositorio_prefijo}"
  arn_logs = "arn:${local.particion}:logs:${var.region}:${local.cuenta}:log-group:/ecs/${var.proyecto}"

  # ssm: carpetas de /sonoraplay que el servicio puede leer.
  servicios_ecs = {
    api-titulares = { ssm = ["rds", "api-titulares"] } # JWT (ADR-0006) y conexión a RDS
    api-contratos = { ssm = ["rds"] }
    simulador     = { ssm = ["rabbitmq"] }
    consumidor    = { ssm = ["rabbitmq"] }
    spark         = { ssm = ["rds"] }
  }

  servicios_ec2 = {
    nat      = { ssm = [] }
    rabbitmq = { ssm = ["rabbitmq"] }
    airflow  = { ssm = ["airflow", "rds", "rabbitmq"] }
  }
}

# --- Confianza ------------------------------------------------------------------------------

data "aws_iam_policy_document" "confianza_ecs" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ecs-tasks.amazonaws.com"]
    }

    # Evita el "confused deputy": solo tareas de ECS de esta cuenta y región.
    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.cuenta]
    }
    condition {
      test     = "ArnLike"
      variable = "aws:SourceArn"
      values   = ["arn:${local.particion}:ecs:${var.region}:${local.cuenta}:*"]
    }
  }
}

data "aws_iam_policy_document" "confianza_ec2" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

# --- ECS: roles de ejecución ----------------------------------------------------------------

resource "aws_iam_role" "ecs_ejecucion" {
  for_each = local.servicios_ecs

  name               = "${local.nombre}-${each.key}-ejecucion"
  description        = "Agente de ECS de ${each.key}: imagen, logs y secretos propios"
  assume_role_policy = data.aws_iam_policy_document.confianza_ecs.json
}

data "aws_iam_policy_document" "ecs_ejecucion" {
  for_each = local.servicios_ecs

  statement {
    sid       = "TokenECR"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # la acción no admite otro recurso
  }

  statement {
    sid = "ImagenPropia"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:GetDownloadUrlForLayer",
    ]
    resources = ["${local.arn_ecr}/${each.key}"]
  }

  statement {
    sid       = "LogsPropios"
    actions   = ["logs:CreateLogStream", "logs:PutLogEvents"]
    resources = ["${local.arn_logs}/${each.key}:*"]
  }

  statement {
    sid       = "SecretosPropios"
    actions   = ["ssm:GetParameters"]
    resources = [for carpeta in each.value.ssm : "${local.arn_ssm}/${carpeta}/*"]
  }
}

resource "aws_iam_role_policy" "ecs_ejecucion" {
  for_each = local.servicios_ecs

  name   = "minimo-privilegio"
  role   = aws_iam_role.ecs_ejecucion[each.key].id
  policy = data.aws_iam_policy_document.ecs_ejecucion[each.key].json
}

# --- ECS: roles de tarea --------------------------------------------------------------------
# Las APIs y el simulador no llaman a AWS: su rol de tarea existe, pero sin permisos.

resource "aws_iam_role" "ecs_tarea" {
  for_each = local.servicios_ecs

  name               = "${local.nombre}-${each.key}-tarea"
  description        = "Código de ${each.key}"
  assume_role_policy = data.aws_iam_policy_document.confianza_ecs.json
}

# Consumidor: solo escribe en Bronze (no lee ni borra), flujo ⑤–⑥.
data "aws_iam_policy_document" "consumidor" {
  statement {
    sid       = "EscribeBronze"
    actions   = ["s3:PutObject"]
    resources = ["${local.arn_s3["bronze"]}/*"]
  }
}

resource "aws_iam_role_policy" "consumidor" {
  name   = "s3-bronze-escritura"
  role   = aws_iam_role.ecs_tarea["consumidor"].id
  policy = data.aws_iam_policy_document.consumidor.json
}

# Spark: lee Bronze; lee y reescribe Silver y Gold (flujo ⑧). Nunca escribe en Bronze.
data "aws_iam_policy_document" "spark" {
  statement {
    sid       = "ListaCapas"
    actions   = ["s3:ListBucket"]
    resources = values(local.arn_s3)
  }

  statement {
    sid       = "LeeCapas"
    actions   = ["s3:GetObject"]
    resources = [for c in local.capas : "${local.arn_s3[c]}/*"]
  }

  statement {
    sid = "EscribeSilverGold"
    actions = [
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:AbortMultipartUpload",
      "s3:ListMultipartUploadParts",
    ]
    resources = ["${local.arn_s3["silver"]}/*", "${local.arn_s3["gold"]}/*"]
  }
}

resource "aws_iam_role_policy" "spark" {
  name   = "s3-capas"
  role   = aws_iam_role.ecs_tarea["spark"].id
  policy = data.aws_iam_policy_document.spark.json
}

# --- EC2: NAT, RabbitMQ y Airflow -----------------------------------------------------------

resource "aws_iam_role" "ec2" {
  for_each = local.servicios_ec2

  name               = "${local.nombre}-${each.key}-ec2"
  description        = "Instancia EC2 de ${each.key}"
  assume_role_policy = data.aws_iam_policy_document.confianza_ec2.json
}

# Session Manager en lugar de SSH: sin puertos abiertos ni llaves (principio 3 de la arquitectura).
resource "aws_iam_role_policy_attachment" "ec2_ssm" {
  for_each = local.servicios_ec2

  role       = aws_iam_role.ec2[each.key].name
  policy_arn = "arn:${local.particion}:iam::aws:policy/AmazonSSMManagedInstanceCore"
}

resource "aws_iam_instance_profile" "ec2" {
  for_each = local.servicios_ec2

  name = "${local.nombre}-${each.key}"
  role = aws_iam_role.ec2[each.key].name
}

data "aws_iam_policy_document" "ec2_secretos" {
  for_each = { for k, v in local.servicios_ec2 : k => v if length(v.ssm) > 0 }

  statement {
    sid       = "SecretosPropios"
    actions   = ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath"]
    resources = [for carpeta in each.value.ssm : "${local.arn_ssm}/${carpeta}/*"]
  }
}

resource "aws_iam_role_policy" "ec2_secretos" {
  for_each = data.aws_iam_policy_document.ec2_secretos

  name   = "ssm-secretos"
  role   = aws_iam_role.ec2[each.key].id
  policy = each.value.json
}

# Airflow lanza los jobs de Spark (flujo ⑦) y guarda F6/F7 en Bronze (flujo ⑩).
data "aws_iam_policy_document" "airflow" {
  statement {
    sid       = "LanzaSpark"
    actions   = ["ecs:RunTask"]
    resources = ["arn:${local.particion}:ecs:${var.region}:${local.cuenta}:task-definition/${local.nombre}-spark:*"]

    condition {
      test     = "ArnEquals"
      variable = "ecs:cluster"
      values   = ["arn:${local.particion}:ecs:${var.region}:${local.cuenta}:cluster/${local.ecs_cluster}"]
    }
  }

  statement {
    sid       = "SigueSpark"
    actions   = ["ecs:DescribeTasks", "ecs:StopTask"]
    resources = ["arn:${local.particion}:ecs:${var.region}:${local.cuenta}:task/${local.ecs_cluster}/*"]
  }

  statement {
    sid       = "LeeDefinicion"
    actions   = ["ecs:DescribeTaskDefinition"]
    resources = ["*"] # la acción no admite otro recurso
  }

  statement {
    sid       = "PasaRolesSpark"
    actions   = ["iam:PassRole"]
    resources = [aws_iam_role.ecs_ejecucion["spark"].arn, aws_iam_role.ecs_tarea["spark"].arn]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }

  statement {
    sid       = "LogsSpark"
    actions   = ["logs:GetLogEvents"]
    resources = ["${local.arn_logs}/spark:*"]
  }

  statement {
    sid       = "EscribeF6F7"
    actions   = ["s3:PutObject"]
    resources = ["${local.arn_s3["bronze"]}/f6/*", "${local.arn_s3["bronze"]}/f7/*"]
  }
}

resource "aws_iam_role_policy" "airflow" {
  name   = "orquestacion"
  role   = aws_iam_role.ec2["airflow"].id
  policy = data.aws_iam_policy_document.airflow.json
}
