# Repositorios de ECR (EG-27, criterio 1, tema 8). Stack PERSISTENTE, separado del entorno:
# las imágenes sobreviven al destroy de cada ventana (ADR-0020) y no hay que volver a
# construirlas. Guardar imágenes cuesta centavos (≈ 0,10 USD/GB-mes).
#
#   terraform -chdir=infra/terraform/ecr init -backend-config=../backend.hcl
#   terraform -chdir=infra/terraform/ecr apply
#
# Las políticas de iam.tf ya esperan estos nombres: sonoraplay/<servicio>.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Mismo bucket que el entorno (backend.hcl), otra llave: destruir el entorno no toca ECR.
  backend "s3" {
    key          = "sonoraplay/ecr.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

variable "region" {
  type    = string
  default = "us-east-1"
}

variable "prefijo" {
  description = "Prefijo de los repositorios; debe coincidir con ecr_repositorio_prefijo del entorno."
  type        = string
  default     = "sonoraplay"
}

variable "servicios" {
  description = "Un repositorio por componente que corre en ECS (iam.tf, servicios_ecs)."
  type        = set(string)
  default     = ["api-titulares", "api-contratos", "simulador", "consumidor", "spark"]
}

variable "imagenes_a_conservar" {
  description = "Imágenes etiquetadas que se guardan por repositorio; las más viejas se borran."
  type        = number
  default     = 10
}

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project     = var.prefijo
      Environment = "persistente"
      ManagedBy   = "terraform"
    }
  }
}

resource "aws_ecr_repository" "servicio" {
  for_each = var.servicios

  name = "${var.prefijo}/${each.key}"

  # Criterio 1: la etiqueta es el SHA del commit. Inmutable: un SHA siempre es la misma imagen,
  # así que la definición de tarea versionada apunta a un contenido que no cambia.
  image_tag_mutability = "IMMUTABLE"

  image_scanning_configuration {
    scan_on_push = true # escaneo básico de vulnerabilidades, sin costo
  }

  encryption_configuration {
    encryption_type = "AES256"
  }

  # Las imágenes se pueden regenerar desde el repo con su SHA.
  force_delete = true
}

resource "aws_ecr_lifecycle_policy" "servicio" {
  for_each = aws_ecr_repository.servicio

  repository = each.value.name
  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Borra las imagenes sin etiqueta despues de 1 dia"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 1
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Conserva solo las imagenes mas recientes"
        selection = {
          tagStatus   = "any"
          countType   = "imageCountMoreThan"
          countNumber = var.imagenes_a_conservar
        }
        action = { type = "expire" }
      },
    ]
  })
}

output "repositorios" {
  value = { for s, r in aws_ecr_repository.servicio : s => r.repository_url }
}
