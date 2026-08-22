output "user_pool_id" {
  description = "Identificador del user pool de Cognito."
  value       = aws_cognito_user_pool.this.id
}

output "user_pool_arn" {
  description = "ARN del user pool, necesario para el authorizer de API Gateway."
  value       = aws_cognito_user_pool.this.arn
}

output "user_pool_client_id" {
  description = "Identificador del cliente de aplicacion. Es el valor esperado en el claim aud del token."
  value       = aws_cognito_user_pool_client.backend.id
}

output "user_pool_client_secret" {
  description = "Secreto del cliente de aplicacion. Debe almacenarse en Secrets Manager, nunca en el repositorio."
  value       = aws_cognito_user_pool_client.backend.client_secret
  sensitive   = true
}

output "issuer_url" {
  description = "URL del emisor OIDC del user pool. Se usa para validar el token y para la trust policy del rol."
  value       = local.issuer_url
}

output "oidc_provider_arn" {
  description = "ARN del proveedor OIDC de IAM asociado al user pool."
  value       = aws_iam_openid_connect_provider.cognito.arn
}

output "tenant_scoped_role_arn" {
  description = "ARN del rol que asume cada sesion de tenant mediante AssumeRoleWithWebIdentity con session tags."
  value       = aws_iam_role.tenant_scoped.arn
}

output "tenant_scoped_role_name" {
  description = "Nombre del rol tenant-scoped, util para adjuntar politicas adicionales desde otros modulos."
  value       = aws_iam_role.tenant_scoped.name
}

output "platform_role_arn" {
  description = "ARN del rol de plataforma sin scoping de tenant, o nulo si no se creo."
  value       = try(aws_iam_role.platform[0].arn, null)
}
