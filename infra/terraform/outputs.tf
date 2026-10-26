output "vpc_id" {
  value = aws_vpc.principal.id
}

output "subredes_publicas" {
  description = "Solo para el ALB (HU 18) y la NAT."
  value       = [for s in aws_subnet.publica : s.id]
}

output "subredes_privadas" {
  description = "Cómputo y datos."
  value       = [for s in aws_subnet.privada : s.id]
}

output "security_groups" {
  value = local.sg
}

output "buckets" {
  value = { for c, b in aws_s3_bucket.capa : c => b.bucket }
}

output "rds_endpoint" {
  description = "Host privado de RDS; solo se alcanza desde la VPC o por túnel SSM."
  value       = aws_db_instance.principal.address
}

output "rds_parametros_ssm" {
  description = "Dónde leer la conexión. La contraseña nunca sale de SSM."
  value = merge(
    { for k, p in aws_ssm_parameter.rds_conexion : k => p.name },
    { password = aws_ssm_parameter.rds_password.name },
  )
}

output "roles_ecs" {
  value = {
    for s in keys(local.servicios_ecs) : s => {
      ejecucion = aws_iam_role.ecs_ejecucion[s].arn
      tarea     = aws_iam_role.ecs_tarea[s].arn
    }
  }
}

output "perfiles_ec2" {
  value = { for k, p in aws_iam_instance_profile.ec2 : k => p.name }
}

output "nat_instance_id" {
  value = aws_instance.nat.id
}

# --- EG-27 ----------------------------------------------------------------------------------

output "ecs_cluster" {
  value = aws_ecs_cluster.principal.name
}

output "api_titulares_url" {
  description = "URL pública de la API de sellos (vacía si no se pasó api_titulares_imagen_tag)."
  value       = local.api_activa ? "${local.api_https ? "https" : "http"}://${aws_lb.api[0].dns_name}" : ""
}

output "api_titulares_task_definition" {
  description = "Revisión desplegada (family:N), criterio 2."
  value       = local.api_activa ? "${aws_ecs_task_definition.api_titulares[0].family}:${aws_ecs_task_definition.api_titulares[0].revision}" : ""
}
