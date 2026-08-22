output "platform_key_arn" {
  description = "ARN de la llave KMS de plataforma."
  value       = aws_kms_key.platform.arn
}

output "platform_key_id" {
  description = "Identificador de la llave KMS de plataforma."
  value       = aws_kms_key.platform.key_id
}

output "platform_key_alias" {
  description = "Alias de la llave de plataforma, usable en lugar del ARN en la mayoria de las APIs."
  value       = aws_kms_alias.platform.name
}

output "tenant_key_arns" {
  description = "Mapa de tenant_id a ARN de su CMK dedicada."
  value       = { for k, v in aws_kms_key.tenant : k => v.arn }
}

output "tenant_key_ids" {
  description = "Mapa de tenant_id a identificador de su CMK dedicada."
  value       = { for k, v in aws_kms_key.tenant : k => v.key_id }
}

output "tenant_key_aliases" {
  description = "Mapa de tenant_id a alias de su CMK dedicada."
  value       = { for k, v in aws_kms_alias.tenant : k => v.name }
}

output "tenant_grant_ids" {
  description = "Mapa de tenant_id a identificador del grant creado sobre su CMK."
  value       = { for k, v in aws_kms_grant.tenant_data_access : k => v.grant_id }
  sensitive   = true
}
