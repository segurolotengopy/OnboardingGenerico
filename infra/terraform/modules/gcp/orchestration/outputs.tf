output "workflow_id" {
  description = "Identificador completo del workflow de la saga de onboarding."
  value       = google_workflows_workflow.onboarding.id
}

output "workflow_name" {
  description = "Nombre del workflow, necesario para lanzar ejecuciones con executions.run."
  value       = google_workflows_workflow.onboarding.name
}

output "verification_queue_id" {
  description = "Identificador de la cola de Cloud Tasks de verificaciones."
  value       = google_cloud_tasks_queue.verification.id
}

output "external_providers_queue_id" {
  description = "Identificador de la cola de Cloud Tasks de llamadas a proveedores externos."
  value       = google_cloud_tasks_queue.external_providers.id
}

output "domain_events_topic_id" {
  description = "Identificador del topico de eventos de dominio."
  value       = google_pubsub_topic.domain_events.id
}

output "domain_events_dlq_topic_id" {
  description = "Identificador del topico de mensajes fallidos."
  value       = google_pubsub_topic.domain_events_dlq.id
}

output "firestore_trigger_id" {
  description = "Identificador del trigger de Eventarc sobre la coleccion de casos, o nulo si esta desactivado."
  value       = try(google_eventarc_trigger.firestore_case_written[0].id, null)
}
