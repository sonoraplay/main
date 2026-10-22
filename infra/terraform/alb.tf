# Application Load Balancer de la API de titulares (EG-27, tema 9, criterio 3).
# Es el único recurso público de la arquitectura (principio 3): vive en las subredes públicas
# y solo reenvía al puerto 8000 del SG api-titulares (security_groups.tf).

resource "aws_lb" "api" {
  count = local.api_activa ? 1 : 0

  name               = "${local.nombre}-api"
  load_balancer_type = "application"
  internal           = false
  security_groups    = [local.sg["alb"]]
  subnets            = [for s in aws_subnet.publica : s.id] # 2 AZ, las que exige el ALB

  drop_invalid_header_fields = true
  enable_deletion_protection = false # el destroy de cada ventana debe borrarlo (ADR-0020)
}

resource "aws_lb_target_group" "api_titulares" {
  count = local.api_activa ? 1 : 0

  name        = "${local.nombre}-api-titulares"
  port        = local.api_puerto
  protocol    = "HTTP" # el TLS termina en el ALB; el tramo ALB → tarea va dentro de la VPC
  target_type = "ip"   # awsvpc: cada tarea tiene su propia IP
  vpc_id      = aws_vpc.principal.id

  deregistration_delay = 30 # la API no tiene conexiones largas

  # Criterio 3: el target group usa /health. 3 fallos seguidos → la tarea sale del ALB y ECS
  # la reemplaza (criterio 4).
  health_check {
    path                = "/health"
    matcher             = "200"
    interval            = 15
    timeout             = 5
    healthy_threshold   = 2
    unhealthy_threshold = 3
  }
}

# Puerto 80: con certificado solo redirige a 443; sin certificado atiende en HTTP (ventanas de
# prueba sin dominio, ver ADR-0012).
resource "aws_lb_listener" "http" {
  count = local.api_activa ? 1 : 0

  load_balancer_arn = aws_lb.api[0].arn
  port              = 80
  protocol          = "HTTP"

  default_action {
    type             = local.api_https ? "redirect" : "forward"
    target_group_arn = local.api_https ? null : aws_lb_target_group.api_titulares[0].arn

    dynamic "redirect" {
      for_each = local.api_https ? [1] : []
      content {
        port        = "443"
        protocol    = "HTTPS"
        status_code = "HTTP_301"
      }
    }
  }
}

resource "aws_lb_listener" "https" {
  count = local.api_activa && local.api_https ? 1 : 0

  load_balancer_arn = aws_lb.api[0].arn
  port              = 443
  protocol          = "HTTPS"
  ssl_policy        = "ELBSecurityPolicy-TLS13-1-2-2021-06"
  certificate_arn   = var.certificado_acm_arn

  default_action {
    type             = "forward"
    target_group_arn = aws_lb_target_group.api_titulares[0].arn
  }
}
