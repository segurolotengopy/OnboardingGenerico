output "audit_log_bucket_id" {
  description = "Identificador del bucket de logs de auditoria."
  value       = google_logging_project_bucket_config.audit.bucket_id
}

output "audit_sink_writer_identity" {
  description = "Identidad de escritura del sink de auditoria. Necesita permisos sobre el destino."
  value       = google_logging_project_sink.audit.writer_identity
}

output "long_term_sink_writer_identity" {
  description = "Identidad de escritura del sink de retencion larga, o nulo si esta desactivado."
  value       = try(google_logging_project_sink.long_term[0].writer_identity, null)
}

output "notification_channel_ids" {
  description = "Mapa de nombre a identificador del canal de notificacion."
  value       = { for k, v in google_monitoring_notification_channel.email : k => v.id }
}

output "tenant_scope_mismatch_metric_name" {
  description = "Nombre de la metrica basada en logs que detecta desalineacion de alcance de tenant."
  value       = google_logging_metric.tenant_scope_mismatch.name
}
