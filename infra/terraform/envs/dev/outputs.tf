# ---------------------------------------------------------------------------
# Salidas del entorno.
#
# Todo lo que otro sistema necesita para integrarse: URLs, identificadores y
# nombres. Los valores sensibles se marcan como tales y no se imprimen.
# ---------------------------------------------------------------------------

output "cloud_provider" {
  description = "Nube o nubes efectivamente desplegadas en este entorno."
  value       = var.cloud_provider
}

# --- AWS -------------------------------------------------------------------

output "aws_api_invoke_url" {
  description = "URL base de la API de AWS, o nulo si el arbol de AWS no esta desplegado."
  value       = try(module.aws_api[0].invoke_url, null)
}

output "aws_user_pool_id" {
  description = "Identificador del user pool de Cognito."
  value       = try(module.aws_identity[0].user_pool_id, null)
}

output "aws_user_pool_client_secret" {
  description = "Secreto del cliente de aplicacion de Cognito. Guardelo en Secrets Manager; nunca lo versione."
  value       = try(module.aws_identity[0].user_pool_client_secret, null)
  sensitive   = true
}

output "aws_tenant_scoped_role_arn" {
  description = "ARN del rol que asume cada sesion de tenant con session tags."
  value       = try(module.aws_identity[0].tenant_scoped_role_arn, null)
}

output "aws_core_table_name" {
  description = "Nombre de la tabla single-table del dominio."
  value       = try(module.aws_data[0].core_table_name, null)
}

output "aws_state_machine_arn" {
  description = "ARN de la maquina de estado Standard que orquesta la saga."
  value       = try(module.aws_orchestration[0].parent_state_machine_arn, null)
}

output "aws_evidence_bucket_name" {
  description = "Nombre del bucket WORM de evidencia de auditoria."
  value       = try(module.aws_storage[0].evidence_bucket_name, null)
}

output "aws_ecr_repository_urls" {
  description = "Mapa de nombre logico a URL del repositorio de ECR, destino del push del pipeline de construccion."
  value       = try(module.aws_compute[0].ecr_repository_urls, {})
}

output "aws_tenant_api_key_values" {
  description = "Mapa de tenant_id al valor de su clave de API. Entreguelas por un canal seguro."
  value       = try(module.aws_api[0].tenant_api_key_values, {})
  sensitive   = true
}

# --- GCP -------------------------------------------------------------------

output "gcp_gateway_url" {
  description = "Nombre de host de la pasarela de GCP, o nulo si el arbol de GCP no esta desplegado."
  value       = try(module.gcp_api[0].gateway_url, null)
}

output "gcp_runtime_service_account_email" {
  description = "Cuenta de servicio del runtime del middleware en GCP."
  value       = try(module.gcp_identity[0].runtime_service_account_email, null)
}

output "gcp_firestore_database_name" {
  description = "Nombre de la base de datos de Firestore compartida."
  value       = try(module.gcp_data[0].shared_database_name, null)
}

output "gcp_workflow_name" {
  description = "Nombre del workflow de la saga de onboarding."
  value       = try(module.gcp_orchestration[0].workflow_name, null)
}

output "gcp_service_urls" {
  description = "Mapa de nombre logico a URL del servicio de Cloud Run."
  value       = try(module.gcp_compute[0].service_urls, {})
}

output "gcp_artifact_registry_host" {
  description = "Host de Artifact Registry, en el formato que espera docker push."
  value       = try(module.gcp_compute[0].artifact_registry_host, null)
}

output "gcp_evidence_bucket_name" {
  description = "Nombre del bucket WORM de evidencia en Cloud Storage."
  value       = try(module.gcp_storage[0].evidence_bucket_name, null)
}
