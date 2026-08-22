output "purge_job_name" {
  description = "Nombre del job de Cloud Run que ejecuta la purga."
  value       = google_cloud_run_v2_job.purge.name
}

output "purge_job_id" {
  description = "Identificador completo del job de purga."
  value       = google_cloud_run_v2_job.purge.id
}

output "erasure_trigger_id" {
  description = "Identificador del trigger de Eventarc sobre las solicitudes de supresion, o nulo si esta desactivado."
  value       = try(google_eventarc_trigger.erasure_requested[0].id, null)
}

output "retention_sweep_job_name" {
  description = "Nombre del trabajo de Cloud Scheduler que ejecuta el barrido, o nulo si esta desactivado."
  value       = try(google_cloud_scheduler_job.retention_sweep[0].name, null)
}

output "purge_failure_metric_name" {
  description = "Nombre de la metrica basada en logs que cuenta los fallos de purga."
  value       = google_logging_metric.purge_failures.name
}
