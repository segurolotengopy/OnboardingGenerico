output "shared_database_name" {
  description = "Nombre de la base de datos de Firestore compartida."
  value       = google_firestore_database.shared.name
}

output "shared_database_id" {
  description = "Identificador completo de la base de datos compartida."
  value       = google_firestore_database.shared.id
}

output "tenant_database_names" {
  description = "Mapa de tenant_id a nombre de su base de datos dedicada. Solo contiene tenants de tier premium."
  value       = { for k, v in google_firestore_database.tenant : k => v.name }
}

output "collections" {
  description = "Nombres de los grupos de colecciones usados por el middleware, para que el adaptador no los cablee."
  value = {
    cases        = var.cases_collection
    reviews      = var.reviews_collection
    capabilities = var.capabilities_collection
    locks        = var.locks_collection
    ephemeral    = var.ephemeral_collection
  }
}
