# EG-41 · EKS con UN componente (la API F4, api-contratos) para comparar con ECS Fargate.
# Stack EFÍMERO con estado propio: el plano de control cobra ≈ 0,10 USD/h, así que se crea y
# se destruye con la ventana del Sprint 5 y la demo (ADR-0018, ADR-0020).
#
#   terraform -chdir=infra/terraform/eks init -backend-config=../backend.hcl
#   terraform -chdir=infra/terraform/eks apply -var 'acceso_api_cidrs=["TU_IP/32"]'
#   ... probar (docs/infraestructura/eg41-eks-frente-a-ecs.md) ...
#   terraform -chdir=infra/terraform/eks destroy -var 'acceso_api_cidrs=["TU_IP/32"]'
#
# Requiere el entorno principal aplicado (VPC, subredes privadas, RDS) y la imagen de
# api-contratos en ECR: es la MISMA que usa ECS (infra/scripts/publicar-imagen.sh).

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
  }

  # Mismo bucket que el entorno (backend.hcl), otra llave: destruir EKS no toca el entorno.
  backend "s3" {
    key          = "sonoraplay/eks.tfstate"
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

variable "acceso_api_cidrs" {
  description = "CIDR desde los que se llega a la API pública de Kubernetes (tu IP /32). Sin valor por defecto a propósito: nunca 0.0.0.0/0."
  type        = list(string)

  validation {
    condition     = length(var.acceso_api_cidrs) > 0 && !contains(var.acceso_api_cidrs, "0.0.0.0/0")
    error_message = "Indica al menos un CIDR y no uses 0.0.0.0/0."
  }
}

variable "kubernetes_version" {
  description = "Versión del plano de control; verifica la vigente con `aws eks describe-cluster-versions`."
  type        = string
  default     = "1.33"
}

variable "tipo_nodo" {
  description = "Instancia ARM64 (la imagen es la misma que corre en Fargate ARM64, ADR-0012)."
  type        = string
  default     = "t4g.small"
}

variable "nodos" {
  description = "Nodos del grupo: 1 basta para la prueba; el costo es por nodo-hora."
  type        = number
  default     = 1
}

locals {
  nombre = "${var.proyecto}-${var.entorno}-eks"

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

# --- Red y RDS del entorno principal (se buscan por etiqueta, sin acoplar los estados) ------

data "aws_vpc" "principal" {
  tags = { Name = "${var.proyecto}-${var.entorno}" }
}

data "aws_subnets" "privadas" {
  filter {
    name   = "vpc-id"
    values = [data.aws_vpc.principal.id]
  }

  tags = { Tier = "privada" }
}

data "aws_security_group" "rds" {
  name   = "${var.proyecto}-${var.entorno}-rds"
  vpc_id = data.aws_vpc.principal.id
}

# --- Cifrado de los secretos de Kubernetes ----------------------------------------------------

resource "aws_kms_key" "eks" {
  description             = "Cifrado de secretos de ${local.nombre}"
  enable_key_rotation     = true
  deletion_window_in_days = 7
}


# --- Roles ------------------------------------------------------------------------------------

data "aws_iam_policy_document" "asumir_eks" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["eks.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "cluster" {
  name               = "${local.nombre}-cluster"
  assume_role_policy = data.aws_iam_policy_document.asumir_eks.json
}

resource "aws_iam_role_policy_attachment" "cluster" {
  role       = aws_iam_role.cluster.name
  policy_arn = "arn:${data.aws_partition.actual.partition}:iam::aws:policy/AmazonEKSClusterPolicy"
}

data "aws_iam_policy_document" "asumir_ec2" {
  statement {
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["ec2.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "nodos" {
  name               = "${local.nombre}-nodos"
  assume_role_policy = data.aws_iam_policy_document.asumir_ec2.json
}

# Mínimo para un nodo: unirse al clúster, red de pods y LEER imágenes de ECR (no escribir).
resource "aws_iam_role_policy_attachment" "nodos" {
  for_each = toset([
    "AmazonEKSWorkerNodePolicy",
    "AmazonEKS_CNI_Policy",
    "AmazonEC2ContainerRegistryReadOnly",
  ])

  role       = aws_iam_role.nodos.name
  policy_arn = "arn:${data.aws_partition.actual.partition}:iam::aws:policy/${each.key}"
}

# --- Clúster y nodos --------------------------------------------------------------------------

resource "aws_eks_cluster" "principal" {
  name     = local.nombre
  role_arn = aws_iam_role.cluster.arn
  version  = var.kubernetes_version

  vpc_config {
    subnet_ids              = data.aws_subnets.privadas.ids
    endpoint_private_access = true
    endpoint_public_access  = true
    public_access_cidrs     = var.acceso_api_cidrs
  }

  access_config {
    authentication_mode                         = "API"
    bootstrap_cluster_creator_admin_permissions = true
  }

  encryption_config {
    resources = ["secrets"]

    provider {
      key_arn = aws_kms_key.eks.arn
    }
  }

  enabled_cluster_log_types = ["api", "audit", "authenticator", "controllerManager", "scheduler"]

  depends_on = [aws_iam_role_policy_attachment.cluster]
}

resource "aws_eks_node_group" "principal" {
  cluster_name    = aws_eks_cluster.principal.name
  node_group_name = "${local.nombre}-arm64"
  node_role_arn   = aws_iam_role.nodos.arn
  subnet_ids      = data.aws_subnets.privadas.ids
  ami_type        = "AL2023_ARM_64_STANDARD"
  instance_types  = [var.tipo_nodo]
  capacity_type   = "ON_DEMAND"
  disk_size       = 20

  scaling_config {
    desired_size = var.nodos
    min_size     = var.nodos
    max_size     = var.nodos
  }

  depends_on = [aws_iam_role_policy_attachment.nodos]
}

# Los pods usan el SG que EKS crea para el clúster: se le permite llegar a RDS (5432) solo
# mientras este stack exista. Al destruirlo, la regla desaparece con él.
resource "aws_vpc_security_group_ingress_rule" "rds_desde_eks" {
  security_group_id            = data.aws_security_group.rds.id
  referenced_security_group_id = aws_eks_cluster.principal.vpc_config[0].cluster_security_group_id
  ip_protocol                  = "tcp"
  from_port                    = 5432
  to_port                      = 5432
  description                  = "EKS (EG-41): api-contratos lee contratos"
}

output "cluster" {
  value = aws_eks_cluster.principal.name
}

output "kubeconfig" {
  description = "Comando que configura kubectl."
  value       = "aws eks update-kubeconfig --region ${var.region} --name ${aws_eks_cluster.principal.name}"
}
