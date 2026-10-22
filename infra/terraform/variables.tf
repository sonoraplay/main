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

variable "entorno" {
  description = "Nombre del entorno; solo hay uno (ADR-0020)."
  type        = string
  default     = "dev"
}

variable "vpc_cidr" {
  description = "Rango de la VPC (arquitectura v1)."
  type        = string
  default     = "10.0.0.0/16"
}

variable "nat_instance_type" {
  description = "Tipo de la instancia NAT (ADR-0010). ARM64. t4g.micro porque el plan gratuito de AWS no permite t4g.nano (ADR-0022)."
  type        = string
  default     = "t4g.micro"
}

variable "rds_instance_class" {
  description = "Clase de la instancia de RDS (arquitectura v1)."
  type        = string
  default     = "db.t4g.micro"
}

variable "rds_engine_version" {
  description = "Versión mayor de PostgreSQL; la misma que usa docker compose y el CI."
  type        = string
  default     = "16"
}

variable "rds_backup_retention_days" {
  description = <<-EOT
    Días de backups automáticos de RDS (criterio 5 de la EG-26). El diseño pide 7.
    La cuenta está en el plan gratuito de AWS, que no permite más de 1 día: las ventanas
    de prueba usan 1 (excepción en ADR-0022). Volver a 7 antes del encendido continuo de la
    última semana (ADR-0020) o al pasar la cuenta a plan pago.
  EOT
  type        = number
  default     = 1

  validation {
    condition     = var.rds_backup_retention_days >= 1 && var.rds_backup_retention_days <= 35
    error_message = "Los backups automáticos de RDS deben estar entre 1 y 35 días."
  }
}

variable "rds_password_version" {
  description = "Súbelo en 1 para rotar la contraseña maestra de RDS (atributo write-only)."
  type        = number
  default     = 1
}

variable "destruccion_limpia" {
  description = <<-EOT
    true: terraform destroy borra los buckets con su contenido y RDS sin snapshot final, para no
    dejar huérfanos (criterio 1 de la EG-26, ADR-0020). Los datos se regeneran con el seed.
    Ponerlo en false solo si se quiere conservar datos entre ventanas.
  EOT
  type        = bool
  default     = true
}

variable "ecr_repositorio_prefijo" {
  description = "Prefijo de los repositorios de ECR (persistentes, fuera de este stack)."
  type        = string
  default     = "sonoraplay"
}

# --- EG-27 · API de titulares en ECS Fargate detrás del ALB ---------------------------------

variable "api_titulares_imagen_tag" {
  description = <<-EOT
    Etiqueta de la imagen en ECR = SHA corto del commit (criterio 1 de la EG-27), por ejemplo
    "a1b2c3d". Vacía: no se crean el ALB, la definición de tarea ni el servicio, así una
    ventana solo de la EG-26 no paga el ALB. Publica la imagen con infra/scripts/publicar-imagen.sh.
  EOT
  type        = string
  default     = ""

  validation {
    condition     = var.api_titulares_imagen_tag == "" || can(regex("^[0-9a-f]{7,40}$", var.api_titulares_imagen_tag))
    error_message = "La etiqueta debe ser el SHA del commit (7 a 40 caracteres hexadecimales)."
  }
}

variable "api_titulares_cpu" {
  description = "CPU de la tarea en unidades de Fargate (256 = 0,25 vCPU; arquitectura v1)."
  type        = number
  default     = 256
}

variable "api_titulares_memoria" {
  description = "Memoria de la tarea en MiB (arquitectura v1)."
  type        = number
  default     = 512
}

variable "api_titulares_tareas" {
  description = "Tareas deseadas del servicio. 1 en las ventanas de prueba; 2 si se pide alta disponibilidad."
  type        = number
  default     = 1
}

variable "certificado_acm_arn" {
  description = <<-EOT
    ARN de un certificado de ACM para el dominio de la API. Con él, el ALB escucha en 443 y el
    puerto 80 solo redirige (ADR-0006). Vacío: el ALB atiende en 80 (HTTP), solo para las
    ventanas de prueba, hasta que el equipo tenga un dominio (ver ADR-0012, sección 5).
  EOT
  type        = string
  default     = ""
}

variable "logs_retencion_dias" {
  description = "Retención de los logs de ECS en CloudWatch (criterio 5 de la EG-27)."
  type        = number
  default     = 7
}

variable "jwt_secret_version" {
  description = "Súbelo en 1 para rotar la clave de firma de los tokens de sellos."
  type        = number
  default     = 1
}
