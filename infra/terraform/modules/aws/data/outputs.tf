locals {
  core_table = var.protect_from_destroy ? aws_dynamodb_table.core_protected[0] : aws_dynamodb_table.core[0]
}

output "core_table_name" {
  description = "Nombre de la tabla single-table del dominio."
  value       = local.core_table.name
}

output "core_table_arn" {
  description = "ARN de la tabla core. Se pasa al modulo de identidad para la politica de dynamodb:LeadingKeys."
  value       = local.core_table.arn
}

output "core_table_stream_arn" {
  description = "ARN del stream de la tabla core. Lo consume la Lambda de purga GDPR."
  value       = local.core_table.stream_arn
}

output "capabilities_table_name" {
  description = "Nombre de la tabla del Registro de Capacidades."
  value       = aws_dynamodb_table.capabilities.name
}

output "capabilities_table_arn" {
  description = "ARN de la tabla del Registro de Capacidades."
  value       = aws_dynamodb_table.capabilities.arn
}

output "capabilities_table_stream_arn" {
  description = "ARN del stream del Registro de Capacidades, usado para invalidar la cache en proceso."
  value       = aws_dynamodb_table.capabilities.stream_arn
}

output "locks_table_name" {
  description = "Nombre de la tabla de mutex distribuido."
  value       = aws_dynamodb_table.locks.name
}

output "locks_table_arn" {
  description = "ARN de la tabla de mutex distribuido."
  value       = aws_dynamodb_table.locks.arn
}

output "keystore_table_name" {
  description = "Nombre de la tabla de branch keys del hierarchical keyring, o nulo si no se creo."
  value       = try(aws_dynamodb_table.keystore[0].name, null)
}

output "keystore_table_arn" {
  description = "ARN de la tabla de branch keys, o nulo si no se creo."
  value       = try(aws_dynamodb_table.keystore[0].arn, null)
}
