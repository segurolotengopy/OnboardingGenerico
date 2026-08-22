output "documents_bucket_name" {
  description = "Nombre del bucket de imagenes de documentos de identidad."
  value       = google_storage_bucket.this["documents"].name
}

output "biometrics_bucket_name" {
  description = "Nombre del bucket de datos biometricos."
  value       = google_storage_bucket.this["biometrics"].name
}

output "staging_bucket_name" {
  description = "Nombre del bucket de artefactos intermedios."
  value       = google_storage_bucket.this["staging"].name
}

output "evidence_bucket_name" {
  description = "Nombre del bucket WORM de evidencia de auditoria."
  value       = google_storage_bucket.evidence.name
}

output "tenant_scoped_bucket_names" {
  description = "Nombres de los buckets sujetos a condiciones de IAM por prefijo de tenant. Es el valor que espera tenant_scoped_bucket_names del modulo gcp/identity."
  value       = [
    google_storage_bucket.this["documents"].name,
    google_storage_bucket.this["biometrics"].name,
    google_storage_bucket.this["staging"].name,
  ]
}

output "bucket_urls" {
  description = "Mapa de nombre logico a URL gs:// del bucket."
  value       = merge(
    { for k, v in google_storage_bucket.this : k => v.url },
    { evidence = google_storage_bucket.evidence.url },
  )
}
