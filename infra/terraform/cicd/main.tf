# EG-40 · Acceso de GitHub Actions a AWS por OIDC, sin llaves guardadas (ADR-0017).
# Stack PERSISTENTE con estado propio: el rol no cuesta nada y debe existir cuando se hace merge
# a main, aunque el entorno de las ventanas esté destruido.
#
#   terraform -chdir=infra/terraform/cicd init -backend-config=../backend.hcl
#   terraform -chdir=infra/terraform/cicd apply
#   # Copia `rol_arn` a la variable de GitHub AWS_DEPLOY_ROLE_ARN (Settings > Variables).
#
# El rol solo lo puede asumir el workflow de la rama `main` de este repositorio.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  backend "s3" {
    key          = "sonoraplay/cicd.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "proyecto" {
  type    = string
  default = "sonoraplay"
}

variable "entorno" {
  type    = string
  default = "dev"
}

variable "owner" {
  description = "Valor de la etiqueta Owner (EG-32). Mismo valor que el entorno principal."
  type        = string
  default     = "sonoraplay-equipo"
}

variable "repositorio_github" {
  description = "owner/repo que puede asumir el rol."
  type        = string
  default     = "sonoraplay/main"
}

variable "rama" {
  description = "Única rama que puede desplegar."
  type        = string
  default     = "main"
}

variable "crear_proveedor_oidc" {
  description = "false si la cuenta ya tiene el proveedor token.actions.githubusercontent.com (solo puede haber uno)."
  type        = bool
  default     = true
}

variable "ecr_repositorio_prefijo" {
  type    = string
  default = "sonoraplay"
}

locals {
  nombre = "${var.proyecto}-${var.entorno}"
  url    = "https://token.actions.githubusercontent.com"
  etiquetas = {
    Project     = var.proyecto
    Owner       = var.owner
    Environment = var.entorno
    ManagedBy   = "terraform"
  }
}

provider "aws" {
  region = var.region

  default_tags {
    tags = local.etiquetas
  }
}

data "aws_caller_identity" "actual" {}

data "aws_partition" "actual" {}

resource "aws_iam_openid_connect_provider" "github" {
  count = var.crear_proveedor_oidc ? 1 : 0

  url            = local.url
  client_id_list = ["sts.amazonaws.com"]
}

data "aws_iam_openid_connect_provider" "existente" {
  count = var.crear_proveedor_oidc ? 0 : 1
  url   = local.url
}

locals {
  proveedor_arn = var.crear_proveedor_oidc ? aws_iam_openid_connect_provider.github[0].arn : data.aws_iam_openid_connect_provider.existente[0].arn
  cuenta        = data.aws_caller_identity.actual.account_id
  particion     = data.aws_partition.actual.partition
}

data "aws_iam_policy_document" "confianza" {
  statement {
    actions = ["sts:AssumeRoleWithWebIdentity"]

    principals {
      type        = "Federated"
      identifiers = [local.proveedor_arn]
    }

    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:aud"
      values   = ["sts.amazonaws.com"]
    }

    # Solo esta rama de este repositorio: un PR o una rama de feature no puede asumir el rol.
    condition {
      test     = "StringEquals"
      variable = "token.actions.githubusercontent.com:sub"
      values   = ["repo:${var.repositorio_github}:ref:refs/heads/${var.rama}"]
    }
  }
}

resource "aws_iam_role" "despliegue" {
  name                 = "${local.nombre}-github-deploy"
  description          = "GitHub Actions (OIDC): publica imágenes en ECR y actualiza los servicios de ECS"
  assume_role_policy   = data.aws_iam_policy_document.confianza.json
  max_session_duration = 3600
}

data "aws_iam_policy_document" "despliegue" {
  statement {
    sid       = "TokenDeEcr"
    actions   = ["ecr:GetAuthorizationToken"]
    resources = ["*"] # la API no admite recursos
  }

  statement {
    sid = "PublicarImagenes"
    actions = [
      "ecr:BatchCheckLayerAvailability",
      "ecr:BatchGetImage",
      "ecr:CompleteLayerUpload",
      "ecr:DescribeImages",
      "ecr:GetDownloadUrlForLayer",
      "ecr:InitiateLayerUpload",
      "ecr:PutImage",
      "ecr:UploadLayerPart",
    ]
    resources = ["arn:${local.particion}:ecr:${var.region}:${local.cuenta}:repository/${var.ecr_repositorio_prefijo}/*"]
  }

  statement {
    sid = "LeerYActualizarServicios"
    actions = [
      "ecs:DescribeServices",
      "ecs:UpdateService",
    ]
    resources = ["arn:${local.particion}:ecs:${var.region}:${local.cuenta}:service/${local.nombre}/*"]
  }

  statement {
    sid = "DefinicionesDeTarea"
    actions = [
      "ecs:DescribeTaskDefinition",
      "ecs:RegisterTaskDefinition",
    ]
    resources = ["*"] # estas dos acciones no admiten recursos
  }

  statement {
    sid       = "PasarSoloLosRolesDeLasTareas"
    actions   = ["iam:PassRole"]
    resources = ["arn:${local.particion}:iam::${local.cuenta}:role/${local.nombre}-*"]

    condition {
      test     = "StringEquals"
      variable = "iam:PassedToService"
      values   = ["ecs-tasks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role_policy" "despliegue" {
  name   = "despliegue"
  role   = aws_iam_role.despliegue.id
  policy = data.aws_iam_policy_document.despliegue.json
}

output "rol_arn" {
  description = "Valor de la variable de GitHub AWS_DEPLOY_ROLE_ARN."
  value       = aws_iam_role.despliegue.arn
}
