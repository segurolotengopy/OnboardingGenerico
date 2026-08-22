output "purge_dlq_arn" {
  description = "ARN de la cola de mensajes fallidos de la purga."
  value       = aws_sqs_queue.purge_dlq.arn
}

output "purge_dlq_url" {
  description = "URL de la cola de mensajes fallidos, para el drenaje manual tras resolver un incidente."
  value       = aws_sqs_queue.purge_dlq.url
}

output "event_source_mapping_uuid" {
  description = "Identificador del mapeo entre el stream de la tabla core y la funcion de purga."
  value       = aws_lambda_event_source_mapping.purge.uuid
}

output "retention_sweep_schedule_arn" {
  description = "ARN de la planificacion del barrido de retencion, o nulo si esta desactivado."
  value       = try(aws_scheduler_schedule.retention_sweep[0].arn, null)
}

output "compliance_alarm_names" {
  description = "Nombres de las alarmas de cumplimiento de este modulo."
  value       = [
    aws_cloudwatch_metric_alarm.purge_dlq_not_empty.alarm_name,
    aws_cloudwatch_metric_alarm.purge_function_errors.alarm_name,
    aws_cloudwatch_metric_alarm.purge_iterator_age.alarm_name,
  ]
}
