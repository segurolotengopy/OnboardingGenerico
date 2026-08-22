output "key_ring_id" {
  description = "Identificador completo del keyring."
  value       = google_kms_key_ring.this.id
}

output "platform_key_id" {
  description = "Identificador completo de la llave de plataforma. Es el valor que espera default_kms_key_name de los buckets y kms_key_name de Firestore."
  value       = google_kms_crypto_key.platform.id
}

output "tenant_key_ids" {
  description = "Mapa de tenant_id a identificador completo de su llave dedicada."
  value       = { for k, v in google_kms_crypto_key.tenant : k => v.id }
}

output "tenant_key_names" {
  description = "Mapa de tenant_id a nombre corto de su llave."
  value       = { for k, v in google_kms_crypto_key.tenant : k => v.name }
}
