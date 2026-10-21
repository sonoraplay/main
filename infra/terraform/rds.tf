# RDS PostgreSQL (criterio 5 de la EG-26, tema 7): privado, cifrado, backups de 7 días y
# credenciales en SSM Parameter Store.
#
# La contraseña maestra la genera un recurso efímero y llega a RDS y a SSM por atributos
# write-only (password_wo, value_wo): no queda en el plan ni en el estado de Terraform.
# Para rotarla se sube var.rds_password_version.

ephemeral "random_password" "rds" {
  length = 32
  # Sin '/', '@', '"' ni espacios: RDS los rechaza en la contraseña maestra.
  override_special = "!#$%^&*()-_=+[]{}:?"
}

resource "aws_db_subnet_group" "principal" {
  name        = local.nombre
  description = "Subredes privadas de las 2 AZ"
  subnet_ids  = [for s in aws_subnet.privada : s.id]
}

resource "aws_db_parameter_group" "postgres" {
  name        = "${local.nombre}-postgres${var.rds_engine_version}"
  family      = "postgres${var.rds_engine_version}"
  description = "PostgreSQL ${var.rds_engine_version} de SonoraPlay: TLS obligatorio"

  parameter {
    name  = "rds.force_ssl"
    value = "1"
    # Es un parámetro estático: con "immediate" (el valor por defecto) AWS lo guarda como
    # pending-reboot y el plan mostraba un cambio en cada ejecución (hallazgo de la ventana).
    apply_method = "pending-reboot"
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_db_instance" "principal" {
  identifier     = local.nombre
  engine         = "postgres"
  engine_version = var.rds_engine_version
  instance_class = var.rds_instance_class

  db_name             = var.proyecto
  username            = "sonora"
  password_wo         = ephemeral.random_password.rds.result
  password_wo_version = var.rds_password_version

  allocated_storage = 20
  storage_type      = "gp3"
  storage_encrypted = true # clave administrada por AWS (aws/rds); solo se puede activar al crear

  db_subnet_group_name   = aws_db_subnet_group.principal.name
  vpc_security_group_ids = [local.sg["rds"]]
  parameter_group_name   = aws_db_parameter_group.postgres.name
  publicly_accessible    = false
  multi_az               = false # Single-AZ: riesgo aceptado en la arquitectura v1, sección 8
  port                   = 5432

  backup_retention_period = var.rds_backup_retention_days
  backup_window           = "06:00-06:30" # UTC, fuera del horario de pruebas del equipo
  maintenance_window      = "sun:07:00-sun:07:30"
  copy_tags_to_snapshot   = true

  auto_minor_version_upgrade = true
  deletion_protection        = !var.destruccion_limpia
  skip_final_snapshot        = var.destruccion_limpia
  final_snapshot_identifier  = var.destruccion_limpia ? null : "${local.nombre}-final"
  delete_automated_backups   = var.destruccion_limpia

  tags = { Name = local.nombre }
}

# --- Credenciales y conexión en SSM Parameter Store ------------------------------------------
# Los servicios leen estos parámetros con su rol de ejecución (iam.tf); nunca están en el repo.

resource "aws_ssm_parameter" "rds_password" {
  name             = "${local.ssm_prefijo}/rds/password"
  description      = "Contraseña maestra de RDS (EG-26)"
  type             = "SecureString"
  value_wo         = ephemeral.random_password.rds.result
  value_wo_version = var.rds_password_version

  # La contraseña efímera cambia en cada apply. Si RDS falla, SSM no debe quedar guardado con
  # una contraseña que RDS nunca recibió (hallazgo de la ventana del 19 oct). Si ya pasó:
  # terraform apply -var rds_password_version=2
  depends_on = [aws_db_instance.principal]
}

resource "aws_ssm_parameter" "rds_conexion" {
  for_each = {
    host     = aws_db_instance.principal.address
    port     = tostring(aws_db_instance.principal.port)
    dbname   = aws_db_instance.principal.db_name
    username = aws_db_instance.principal.username
  }

  name        = "${local.ssm_prefijo}/rds/${each.key}"
  description = "Conexión a RDS: ${each.key} (EG-26)"
  type        = "String"
  value       = each.value
}
