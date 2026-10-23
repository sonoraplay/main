# Presupuesto y alarma de costos (EG-32, criterio 3, arquitectura v1 sec. 7).
#
# Stack PERSISTENTE, aparte del principal: el presupuesto debe seguir vigilando entre
# ventanas de prueba, así que no se destruye con `terraform destroy` del stack principal
# (ADR-0020). Estado propio en S3: sonoraplay/presupuesto.tfstate.
#
# Recorrido: AWS Budgets -> tema SNS -> correo. La suscripción de correo hay que CONFIRMARLA a
# mano con el enlace que envía AWS; mientras no se confirme, la alarma no llega a nadie.
#
# El correo NO va en el repositorio: se pasa al aplicar (-var correo_alertas=...) o en un
# terraform.tfvars local que .gitignore ya excluye.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Configuración parcial: bucket y región van en ../backend.hcl (ver backend.hcl.example).
  backend "s3" {
    key          = "sonoraplay/presupuesto.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

variable "region" {
  description = "Región de AWS (ADR-0009)."
  type        = string
  default     = "us-east-1"
}

variable "proyecto" {
  description = "Prefijo de nombres y valor de la etiqueta Project."
  type        = string
  default     = "sonoraplay"
}

variable "owner" {
  description = "Valor de la etiqueta Owner: a quién se atribuye el costo en Cost Explorer."
  type        = string
  default     = "sonoraplay-equipo"
}

variable "limite_usd" {
  description = "Presupuesto mensual máximo en USD. Estimado del proyecto: ~35 USD en seis semanas (EG-32)."
  type        = number
  default     = 50

  validation {
    condition     = var.limite_usd > 0
    error_message = "El límite debe ser mayor que 0."
  }
}

variable "correo_alertas" {
  description = "Correo obligatorio que recibe las alertas de presupuesto (EG-32)."
  type        = string
  sensitive   = true

  validation {
    condition     = can(regex("^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$", var.correo_alertas))
    error_message = "correo_alertas debe ser una dirección de correo válida."
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.proyecto
      Owner       = var.owner
      Environment = "persistente"
      ManagedBy   = "terraform"
      Stack       = "presupuesto"
    }
  }
}

data "aws_caller_identity" "actual" {}

# --- Tema SNS -------------------------------------------------------------------------------

resource "aws_sns_topic" "alertas" {
  name = "${var.proyecto}-presupuesto-alertas"
  # Sin kms_master_key_id: AWS Budgets no puede publicar en un tema cifrado con la clave
  # administrada aws/sns. Ver la excepción CKV_AWS_26 en .checkov.yaml.
}

# AWS Budgets publica en el tema como servicio; se limita a esta cuenta para evitar que otra
# cuenta use el permiso (problema del "confused deputy").
data "aws_iam_policy_document" "alertas" {
  statement {
    sid       = "PermitirABudgetsPublicar"
    actions   = ["SNS:Publish"]
    resources = [aws_sns_topic.alertas.arn]

    principals {
      type        = "Service"
      identifiers = ["budgets.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [data.aws_caller_identity.actual.account_id]
    }
  }

  statement {
    sid = "AdministracionDeLaCuenta"
    actions = [
      "SNS:Publish",
      "SNS:Subscribe",
      "SNS:GetTopicAttributes",
      "SNS:SetTopicAttributes",
      "SNS:ListSubscriptionsByTopic",
      "SNS:DeleteTopic",
    ]
    resources = [aws_sns_topic.alertas.arn]

    principals {
      type        = "AWS"
      identifiers = ["arn:aws:iam::${data.aws_caller_identity.actual.account_id}:root"]
    }
  }
}

resource "aws_sns_topic_policy" "alertas" {
  arn    = aws_sns_topic.alertas.arn
  policy = data.aws_iam_policy_document.alertas.json
}

# La suscripción queda "pendiente de confirmación" hasta que alguien pulsa el enlace del correo.
resource "aws_sns_topic_subscription" "correo" {
  topic_arn = aws_sns_topic.alertas.arn
  protocol  = "email"
  endpoint  = var.correo_alertas
}

# --- Presupuesto ----------------------------------------------------------------------------

resource "aws_budgets_budget" "mensual" {
  name         = "${var.proyecto}-mensual"
  budget_type  = "COST"
  limit_amount = tostring(var.limite_usd)
  limit_unit   = "USD"
  time_unit    = "MONTHLY"

  # Mide el gasto bruto: no descuenta créditos ni reembolsos, para avisar aunque los créditos
  # de la cuenta lo estén cubriendo. Confirmar el efecto en la consola de Budgets.
  cost_types {
    include_credit = false
    include_refund = false
  }

  # Dos avisos por gasto real y uno por proyección (criterio 3: "actual o proyectado").
  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 50
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.alertas.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 80
    threshold_type            = "PERCENTAGE"
    notification_type         = "ACTUAL"
    subscriber_sns_topic_arns = [aws_sns_topic.alertas.arn]
  }

  notification {
    comparison_operator       = "GREATER_THAN"
    threshold                 = 100
    threshold_type            = "PERCENTAGE"
    notification_type         = "FORECASTED"
    subscriber_sns_topic_arns = [aws_sns_topic.alertas.arn]
  }

  depends_on = [aws_sns_topic_policy.alertas]
}

output "tema_sns_arn" {
  description = "ARN del tema donde Budgets publica las alertas."
  value       = aws_sns_topic.alertas.arn
}

output "presupuesto" {
  description = "Nombre y límite del presupuesto mensual."
  value       = "${aws_budgets_budget.mensual.name}: ${var.limite_usd} USD"
}
