# Red (criterio 2 de la EG-26, tema 6). VPC en 2 AZ con subredes públicas y privadas.
# En las públicas solo viven el ALB (HU 18) y la instancia NAT; el cómputo y los datos van en
# las privadas, que salen a internet por la NAT y a S3 por el endpoint gateway.

resource "aws_vpc" "principal" {
  cidr_block           = var.vpc_cidr
  enable_dns_support   = true
  enable_dns_hostnames = true # lo necesitan Cloud Map (HU 11) y el endpoint de RDS

  tags = { Name = local.nombre }
}

# El SG por defecto queda sin reglas: nadie puede usarlo por descuido.
resource "aws_default_security_group" "principal" {
  vpc_id = aws_vpc.principal.id

  tags = { Name = "${local.nombre}-default-sin-reglas" }
}

resource "aws_internet_gateway" "principal" {
  vpc_id = aws_vpc.principal.id

  tags = { Name = local.nombre }
}

resource "aws_subnet" "publica" {
  for_each = local.subredes_publicas

  vpc_id            = aws_vpc.principal.id
  availability_zone = each.key
  cidr_block        = each.value
  # Nada recibe IP pública por defecto: la NAT la pide de forma explícita.
  map_public_ip_on_launch = false

  tags = { Name = "${local.nombre}-publica-${each.key}", Tier = "publica" }
}

resource "aws_subnet" "privada" {
  for_each = local.subredes_privadas

  vpc_id                  = aws_vpc.principal.id
  availability_zone       = each.key
  cidr_block              = each.value
  map_public_ip_on_launch = false

  tags = { Name = "${local.nombre}-privada-${each.key}", Tier = "privada" }
}

# --- Rutas ---------------------------------------------------------------------------------

resource "aws_route_table" "publica" {
  vpc_id = aws_vpc.principal.id

  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.principal.id
  }

  tags = { Name = "${local.nombre}-publica" }
}

resource "aws_route_table_association" "publica" {
  for_each = aws_subnet.publica

  subnet_id      = each.value.id
  route_table_id = aws_route_table.publica.id
}

# Una tabla por AZ privada: si más adelante se agrega una NAT por AZ, solo cambia la ruta.
resource "aws_route_table" "privada" {
  for_each = aws_subnet.privada

  vpc_id = aws_vpc.principal.id

  route {
    cidr_block           = "0.0.0.0/0"
    network_interface_id = aws_instance.nat.primary_network_interface_id
  }

  tags = { Name = "${local.nombre}-privada-${each.key}" }
}

resource "aws_route_table_association" "privada" {
  for_each = aws_subnet.privada

  subnet_id      = each.value.id
  route_table_id = aws_route_table.privada[each.key].id
}

# Endpoint gateway de S3: gratis, y el tráfico al Data Lake no pasa por la NAT (arquitectura v1).
resource "aws_vpc_endpoint" "s3" {
  vpc_id            = aws_vpc.principal.id
  service_name      = "com.amazonaws.${var.region}.s3"
  vpc_endpoint_type = "Gateway"
  route_table_ids   = [for rt in aws_route_table.privada : rt.id]

  tags = { Name = "${local.nombre}-s3" }
}

# --- Instancia NAT (ADR-0010) ---------------------------------------------------------------

data "aws_ssm_parameter" "al2023_arm64" {
  name = "/aws/service/ami-amazon-linux-latest/al2023-ami-kernel-default-arm64"
}

resource "aws_instance" "nat" {
  ami                         = data.aws_ssm_parameter.al2023_arm64.value
  instance_type               = var.nat_instance_type
  subnet_id                   = aws_subnet.publica[local.azs[0]].id
  vpc_security_group_ids      = [local.sg["nat"]]
  associate_public_ip_address = true
  source_dest_check           = false # obligatorio para reenviar tráfico de otras instancias
  ebs_optimized               = true
  iam_instance_profile        = aws_iam_instance_profile.ec2["nat"].name

  user_data = templatefile("${path.module}/plantillas/nat-user-data.sh.tftpl", {
    vpc_cidr = var.vpc_cidr
  })
  user_data_replace_on_change = true

  metadata_options {
    http_tokens   = "required" # IMDSv2
    http_endpoint = "enabled"
  }

  root_block_device {
    volume_type = "gp3"
    volume_size = 8
    encrypted   = true
    # default_tags no llega al volumen raíz: se etiqueta aquí para que destroy no deje dudas.
    tags = merge(local.etiquetas, { Name = "${local.nombre}-nat" })
  }

  tags = { Name = "${local.nombre}-nat" }

  lifecycle {
    # Una AMI nueva no debe reemplazar la NAT en medio de una ventana de prueba.
    ignore_changes = [ami]
  }
}

# Recuperación automática si falla el hardware (riesgo de la arquitectura v1, sección 8).
resource "aws_cloudwatch_metric_alarm" "nat_recuperacion" {
  alarm_name          = "${local.nombre}-nat-recuperacion"
  alarm_description   = "Recupera la instancia NAT si falla la verificación de estado del sistema."
  namespace           = "AWS/EC2"
  metric_name         = "StatusCheckFailed_System"
  statistic           = "Maximum"
  period              = 60
  evaluation_periods  = 2
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  dimensions          = { InstanceId = aws_instance.nat.id }
  alarm_actions       = ["arn:${local.particion}:automate:${var.region}:ec2:recover"]
}
