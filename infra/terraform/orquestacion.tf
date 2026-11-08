# ADR-0024: EC2 privada compartida para RabbitMQ y Airflow.
variable "orquestacion_instance_type" {
  type    = string
  default = "t4g.large"
}

variable "orquestacion_git_ref" {
  type    = string
  default = "main"
  validation {
    condition     = can(regex("^[a-zA-Z0-9._/-]+$", var.orquestacion_git_ref))
    error_message = "Referencia Git no válida."
  }
}

# No persistir contraseñas en el estado: valores efímeros y atributos write-only.
ephemeral "random_password" "orquestacion" {
  for_each = toset(["rabbitmq", "fernet", "jwt", "metadata"])
  length   = 32
  special  = false
}

resource "aws_ssm_parameter" "orquestacion" {
  for_each = {
    rabbitmq = { ruta = "rabbitmq/password", secreto = ephemeral.random_password.orquestacion["rabbitmq"].result }
    fernet   = { ruta = "airflow/fernet", secreto = base64encode(ephemeral.random_password.orquestacion["fernet"].result) }
    jwt      = { ruta = "airflow/jwt", secreto = ephemeral.random_password.orquestacion["jwt"].result }
    metadata = { ruta = "airflow/db-password", secreto = ephemeral.random_password.orquestacion["metadata"].result }
  }
  name             = "${local.ssm_prefijo}/${each.value.ruta}"
  type             = "SecureString"
  value_wo         = each.value.secreto
  value_wo_version = 1
  tags             = local.etiquetas
}

resource "aws_instance" "orquestacion" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.value
  instance_type               = var.orquestacion_instance_type
  subnet_id                   = aws_subnet.privada[local.azs[0]].id
  vpc_security_group_ids      = [local.sg["airflow"]]
  iam_instance_profile        = aws_iam_instance_profile.ec2["airflow"].name
  associate_public_ip_address = false
  ebs_optimized               = true
  user_data = templatefile("${path.module}/plantillas/orquestacion-user-data.sh.tftpl", {
    git_ref             = var.orquestacion_git_ref
    region              = var.region
    ssm_prefix          = local.ssm_prefijo
    bronze_bucket       = aws_s3_bucket.capa["bronze"].bucket
    silver_bucket       = aws_s3_bucket.capa["silver"].bucket
    sns_topic_arn       = "arn:${local.particion}:sns:${var.region}:${local.cuenta}:${var.proyecto}-presupuesto-alertas"
    ecs_cluster         = aws_ecs_cluster.principal.name
    ecs_spark_family    = "${local.nombre}-spark"
    ecs_subnets         = join(",", [for s in aws_subnet.privada : s.id])
    ecs_security_groups = local.sg["spark"]
  })
  user_data_replace_on_change = true
  metadata_options {
    http_tokens   = "required"
    http_endpoint = "enabled"
  }
  root_block_device {
    encrypted   = true
    volume_type = "gp3"
    volume_size = 30
    tags        = merge(local.etiquetas, { Name = "${local.nombre}-orquestacion-root" })
  }
  tags = merge(local.etiquetas, { Name = "${local.nombre}-orquestacion" })
  depends_on = [aws_ssm_parameter.orquestacion, aws_ssm_parameter.rds_password, aws_ssm_parameter.rds_conexion]
  lifecycle {
    ignore_changes = [ami]
  }
}
