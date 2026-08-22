output "runtime_service_account_email" {
  description = "Correo de la cuenta de servicio del runtime del middleware."
  value       = google_service_account.runtime.email
}

output "runtime_service_account_id" {
  description = "Identificador completo de la cuenta de servicio del runtime."
  value       = google_service_account.runtime.name
}

output "tenant_service_account_emails" {
  description = "Mapa de tenant_id a correo de su cuenta de servicio dedicada. Solo contiene los tenants de tier premium."
  value       = { for k, v in google_service_account.tenant : k => v.email }
}

output "identity_platform_tenant_ids" {
  description = "Mapa de tenant_id logico al identificador que Identity Platform asigno al tenant."
  value       = { for k, v in google_identity_platform_tenant.this : k => v.name }
}

output "workload_identity_pool_name" {
  description = "Nombre completo del pool de federacion de identidades, o nulo si no se creo."
  value       = try(google_iam_workload_identity_pool.this[0].name, null)
}

output "workload_identity_provider_name" {
  description = "Nombre completo del proveedor OIDC de federacion, o nulo si no se creo."
  value       = try(google_iam_workload_identity_pool_provider.oidc[0].name, null)
}
