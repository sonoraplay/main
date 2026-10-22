# Bootstrap · bucket del estado de Terraform (EG-26, ADR-0011).
#
# Es el único recurso que sobrevive entre ventanas de prueba (ADR-0020): se crea una sola vez
# con estado local y no se destruye con el stack principal. Cuesta centavos al mes.

terraform {
  required_version = ">= 1.11"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 6.0"
    }
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

provider "aws" {
  region = var.region

  default_tags {
    tags = {
      Project   = var.proyecto
      ManagedBy = "terraform"
      Stack     = "bootstrap"
    }
  }
}

data "aws_caller_identity" "actual" {}

resource "aws_s3_bucket" "estado" {
  # El ID de la cuenta hace el nombre único en todo S3.
  bucket = "${var.proyecto}-${data.aws_caller_identity.actual.account_id}-tfstate"

  lifecycle {
    prevent_destroy = true
  }
}

resource "aws_s3_bucket_versioning" "estado" {
  bucket = aws_s3_bucket.estado.id

  versioning_configuration {
    status = "Enabled" # permite recuperar un estado dañado
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "estado" {
  bucket = aws_s3_bucket.estado.id

  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_policy" "estado" {
  bucket = aws_s3_bucket.estado.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "SoloTLS"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [aws_s3_bucket.estado.arn, "${aws_s3_bucket.estado.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.estado]
}

resource "aws_s3_bucket_lifecycle_configuration" "estado" {
  bucket = aws_s3_bucket.estado.id

  rule {
    id     = "versiones-antiguas"
    status = "Enabled"
    filter {}

    noncurrent_version_expiration {
      noncurrent_days = 30
    }

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

output "bucket_estado" {
  description = "Nombre del bucket para backend.hcl del stack principal."
  value       = aws_s3_bucket.estado.bucket
}
