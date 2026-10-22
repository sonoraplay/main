data "aws_caller_identity" "actual" {}

data "aws_partition" "actual" {}

data "aws_availability_zones" "disponibles" {
  state = "available"

  filter {
    name   = "opt-in-status"
    values = ["opt-in-not-required"]
  }
}

locals {
  nombre    = "${var.proyecto}-${var.entorno}"
  cuenta    = data.aws_caller_identity.actual.account_id
  particion = data.aws_partition.actual.partition

  etiquetas = {
    Project     = var.proyecto
    Environment = var.entorno
    ManagedBy   = "terraform"
  }

  # Dos AZ: el grupo de subredes de RDS y el ALB (HU 18) las exigen.
  azs = slice(data.aws_availability_zones.disponibles.names, 0, 2)

  # /24 por subred: públicas 10.0.0.0/24 y 10.0.1.0/24; privadas 10.0.10.0/24 y 10.0.11.0/24.
  subredes_publicas = { for i, az in local.azs : az => cidrsubnet(var.vpc_cidr, 8, i) }
  subredes_privadas = { for i, az in local.azs : az => cidrsubnet(var.vpc_cidr, 8, i + 10) }

  # Raíz de los parámetros de SSM del proyecto (ADR-0017).
  ssm_prefijo = "/${var.proyecto}"
}
