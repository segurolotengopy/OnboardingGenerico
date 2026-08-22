output "rest_api_id" {
  description = "Identificador de la API REST."
  value       = aws_api_gateway_rest_api.this.id
}

output "invoke_url" {
  description = "URL base de invocacion de la etapa desplegada."
  value       = aws_api_gateway_stage.this.invoke_url
}

output "stage_arn" {
  description = "ARN de la etapa, necesario para asociar un Web ACL o un plan de uso adicional."
  value       = aws_api_gateway_stage.this.arn
}

output "execution_arn" {
  description = "ARN de ejecucion de la API, usado en los permisos de invocacion de Lambda."
  value       = aws_api_gateway_rest_api.this.execution_arn
}

output "tenant_api_key_ids" {
  description = "Mapa de tenant_id a identificador de su clave de API. El valor de la clave no se expone: recuperelo con la API de AWS y entreguelo por un canal seguro."
  value       = { for k, v in aws_api_gateway_api_key.tenant : k => v.id }
}

output "tenant_api_key_values" {
  description = "Mapa de tenant_id al valor de su clave de API. Se marca como sensible y no debe imprimirse ni versionarse."
  value       = { for k, v in aws_api_gateway_api_key.tenant : k => v.value }
  sensitive   = true
}

output "tenant_usage_plan_ids" {
  description = "Mapa de tenant_id a identificador de su plan de uso."
  value       = { for k, v in aws_api_gateway_usage_plan.tenant : k => v.id }
}

output "waf_web_acl_arn" {
  description = "ARN del Web ACL asociado a la etapa, o nulo si el WAF esta desactivado."
  value       = try(aws_wafv2_web_acl.this[0].arn, null)
}

output "access_log_group_name" {
  description = "Nombre del log group de acceso de la API."
  value       = aws_cloudwatch_log_group.access.name
}
