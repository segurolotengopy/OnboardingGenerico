output "service_urls" {
  description = "Mapa de nombre logico a URL del servicio de Cloud Run."
  value       = { for k, v in google_cloud_run_v2_service.this : k => v.uri }
}

output "service_names" {
  description = "Mapa de nombre logico a nombre completo del servicio."
  value       = { for k, v in google_cloud_run_v2_service.this : k => v.name }
}

output "job_names" {
  description = "Mapa de nombre logico a nombre completo del job."
  value       = { for k, v in google_cloud_run_v2_job.this : k => v.name }
}

output "artifact_registry_repository_id" {
  description = "Identificador del repositorio de Artifact Registry."
  value       = google_artifact_registry_repository.containers.repository_id
}

output "artifact_registry_host" {
  description = "Host del repositorio de imagenes, en el formato que espera docker push."
  value       = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}"
}
