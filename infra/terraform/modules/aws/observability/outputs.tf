output "event_bus_arn" {
  description = "ARN del bus de eventos de dominio."
  value       = aws_cloudwatch_event_bus.domain.arn
}

output "event_bus_name" {
  description = "Nombre del bus de eventos de dominio, tal como lo espera la integracion events:putEvents de Step Functions."
  value       = aws_cloudwatch_event_bus.domain.name
}

output "alarms_topic_arn" {
  description = "ARN del topico SNS al que se publican las alarmas."
  value       = aws_sns_topic.alarms.arn
}

output "domain_events_log_group_name" {
  description = "Nombre del log group donde se copian todos los eventos de dominio."
  value       = aws_cloudwatch_log_group.domain_events.name
}

output "dashboard_name" {
  description = "Nombre del panel de CloudWatch."
  value       = aws_cloudwatch_dashboard.main.dashboard_name
}
