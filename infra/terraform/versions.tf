terraform {
  # 1.11+: atributos write-only y recursos efímeros (la contraseña de RDS no queda en el estado).
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
    random = {
      source  = "hashicorp/random"
      version = "~> 3.7"
    }
  }

  # Configuración parcial: bucket y región van en backend.hcl (ver backend.hcl.example).
  # Bloqueo nativo de S3 (use_lockfile), sin tabla de DynamoDB.
  backend "s3" {
    key          = "sonoraplay/terraform.tfstate"
    encrypt      = true
    use_lockfile = true
  }
}

provider "aws" {
  region = var.region

  # Criterio 1 de la EG-26: todo recurso lleva Project=sonoraplay, para encontrar huérfanos.
  default_tags {
    tags = local.etiquetas
  }
}
