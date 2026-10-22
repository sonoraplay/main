# Security Groups de la arquitectura v1 (sección 3). Cada SG solo acepta tráfico de otro SG,
# nunca de un rango abierto, salvo el ALB (público) y la NAT (solo desde la VPC).
# Se crean todos aquí porque sg-rds depende de los SG de quienes lo consumen.

locals {
  security_groups = {
    alb           = "ALB publico: 443 y 80 (redirige) desde internet (HU 18)"
    nat           = "Instancia NAT: todo el trafico desde la VPC"
    api-titulares = "API de sellos en Fargate (HU 12, 18)"
    api-contratos = "API F4 en Fargate, solo la consulta Spark (HU 11)"
    simulador     = "Simulador F2 en Fargate Spot; solo salida"
    consumidor    = "Consumidor F2 a Bronze en Fargate Spot; solo salida"
    spark         = "Jobs de Spark en Fargate Spot; solo salida"
    rabbitmq      = "RabbitMQ en EC2 (HU 20)"
    airflow       = "Airflow en EC2; sin entrada, se usa por tunel SSM"
    rds           = "RDS PostgreSQL privado"
  }

  # Entrada entre SG: destino => [(origen, puerto, descripción)].
  reglas_entre_sg = [
    { destino = "api-titulares", origen = "alb", puerto = 8000, desc = "ALB a la API de sellos" },
    { destino = "api-contratos", origen = "spark", puerto = 8000, desc = "Spark consulta el porcentaje vigente" },
    { destino = "rds", origen = "api-titulares", puerto = 5432, desc = "API de sellos lee liquidaciones" },
    { destino = "rds", origen = "api-contratos", puerto = 5432, desc = "API F4 lee contratos" },
    { destino = "rds", origen = "spark", puerto = 5432, desc = "Spark carga modelo y liquidacion" },
    { destino = "rds", origen = "airflow", puerto = 5432, desc = "Tunel SSM de Power BI (flujo 12)" },
    { destino = "rabbitmq", origen = "simulador", puerto = 5672, desc = "Simulador publica eventos F2" },
    { destino = "rabbitmq", origen = "consumidor", puerto = 5672, desc = "Consumidor lee eventos F2" },
    { destino = "rabbitmq", origen = "airflow", puerto = 5672, desc = "Broker de Celery" },
  ]
}

resource "aws_security_group" "servicio" {
  for_each = local.security_groups

  name        = "${local.nombre}-${each.key}"
  description = each.value
  vpc_id      = aws_vpc.principal.id

  tags = { Name = "sg-${each.key}" }

  lifecycle {
    create_before_destroy = true
  }
}

# Alias para leer mejor el resto del código.
locals {
  sg = { for k, v in aws_security_group.servicio : k => v.id }
}

# Salida libre para todos: las privadas solo llegan a internet por la NAT.
resource "aws_vpc_security_group_egress_rule" "todo" {
  for_each = local.sg

  security_group_id = each.value
  description       = "Salida"
  ip_protocol       = "-1"
  cidr_ipv4         = "0.0.0.0/0"
}

resource "aws_vpc_security_group_ingress_rule" "entre_sg" {
  for_each = { for r in local.reglas_entre_sg : "${r.destino}-desde-${r.origen}-${r.puerto}" => r }

  security_group_id            = local.sg[each.value.destino]
  referenced_security_group_id = local.sg[each.value.origen]
  ip_protocol                  = "tcp"
  from_port                    = each.value.puerto
  to_port                      = each.value.puerto
  description                  = each.value.desc
}

resource "aws_vpc_security_group_ingress_rule" "alb_publico" {
  for_each = toset(["80", "443"])

  security_group_id = local.sg["alb"]
  cidr_ipv4         = "0.0.0.0/0"
  ip_protocol       = "tcp"
  from_port         = tonumber(each.value)
  to_port           = tonumber(each.value)
  description       = each.value == "443" ? "HTTPS publico" : "HTTP, solo para redirigir a 443"
}

resource "aws_vpc_security_group_ingress_rule" "nat_desde_vpc" {
  security_group_id = local.sg["nat"]
  cidr_ipv4         = var.vpc_cidr
  ip_protocol       = "-1"
  description       = "Trafico de las subredes privadas hacia internet"
}
