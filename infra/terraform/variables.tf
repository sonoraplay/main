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
