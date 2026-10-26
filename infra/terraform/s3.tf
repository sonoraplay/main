# Data Lake por capas (criterio 4 de la EG-26, tema 7). Un bucket por capa, para que IAM pueda
# dar permisos por capa (el consumidor solo escribe en Bronze; Spark lee Bronze y escribe
# Silver y Gold). Cifrado SSE-S3 y Block Public Access en los cuatro niveles.
# Formato y particionamiento de los objetos: ADR-0014 (EG-31).

locals {
  capas = toset(["bronze", "silver", "gold"])
}

resource "aws_s3_bucket" "capa" {
  for_each = local.capas

  bucket = "${var.proyecto}-${local.cuenta}-${each.key}"
  # destroy sin huérfanos (ADR-0020): los datos se regeneran con el simulador y el seed.
  force_destroy = var.destruccion_limpia

  tags = { Name = "${var.proyecto}-${each.key}", Capa = each.key }
}

resource "aws_s3_bucket_public_access_block" "capa" {
  for_each = aws_s3_bucket.capa

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_server_side_encryption_configuration" "capa" {
  for_each = aws_s3_bucket.capa

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256" # SSE-S3, sin costo (arquitectura v1)
    }
  }
}

# Sin ACL: el acceso se decide solo con IAM y la política del bucket.
resource "aws_s3_bucket_ownership_controls" "capa" {
  for_each = aws_s3_bucket.capa

  bucket = each.value.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

# Rechaza cualquier petición sin TLS.
resource "aws_s3_bucket_policy" "capa" {
  for_each = aws_s3_bucket.capa

  bucket = each.value.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "SoloTLS"
      Effect    = "Deny"
      Principal = "*"
      Action    = "s3:*"
      Resource  = [each.value.arn, "${each.value.arn}/*"]
      Condition = { Bool = { "aws:SecureTransport" = "false" } }
    }]
  })

  depends_on = [aws_s3_bucket_public_access_block.capa]
}

# Las cargas multiparte incompletas cobran almacenamiento sin verse: se limpian a los 7 días.
resource "aws_s3_bucket_lifecycle_configuration" "capa" {
  for_each = aws_s3_bucket.capa

  bucket = each.value.id

  rule {
    id     = "limpiar-multiparte"
    status = "Enabled"
    filter {}

    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}
