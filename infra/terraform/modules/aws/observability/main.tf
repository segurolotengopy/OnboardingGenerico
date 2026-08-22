# ---------------------------------------------------------------------------
# Observabilidad, eventos de dominio y alarmas.
#
# Principio rector: la TENANCY DEBE SER OBSERVABLE. Toda metrica, log y traza
# lleva la dimension TenantId. Las metricas por tenant se emiten desde el codigo
# con el formato de metricas embebidas de CloudWatch (EMF), que evita una
# llamada sincrona a la API de metricas por cada medicion.
#
# Lo que este modulo NO hace: crear las metricas por tenant. Esas nacen del
# codigo. Aqui se crean las alarmas de plataforma y el panel.
# ---------------------------------------------------------------------------

data "aws_region" "current" {}

locals {
  name = "og-${var.env}"
}

# ---------------------------------------------------------------------------
# Bus de eventos de dominio
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_event_bus" "domain" {
  name = "${local.name}-domain-events"
  tags = var.tags
}

# El archivo permite reproducir eventos historicos: util para reconstruir el
# estado de un caso ante una disputa o una auditoria.
resource "aws_cloudwatch_event_archive" "domain" {
  name             = "${local.name}-domain-archive"
  event_source_arn = aws_cloudwatch_event_bus.domain.arn
  retention_days   = var.event_archive_retention_days
  description      = "Archivo de eventos de dominio para reproduccion ante auditoria."
}

# Todo evento de dominio se persiste en logs con retencion larga: el historial
# de Step Functions solo vive 90 dias y la obligacion regulatoria es de anios.
resource "aws_cloudwatch_log_group" "domain_events" {
  name              = "/og/${var.env}/domain-events"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.log_kms_key_arn

  tags = var.tags
}

resource "aws_cloudwatch_event_rule" "capture_all" {
  name           = "${local.name}-capture-domain-events"
  description    = "Copia todos los eventos de dominio a CloudWatch Logs."
  event_bus_name = aws_cloudwatch_event_bus.domain.name

  event_pattern = jsonencode({
    source = [{ prefix = "onboarding." }]
  })

  tags = var.tags
}

resource "aws_cloudwatch_event_target" "capture_all" {
  rule           = aws_cloudwatch_event_rule.capture_all.name
  event_bus_name = aws_cloudwatch_event_bus.domain.name
  target_id      = "to-cloudwatch-logs"
  arn            = aws_cloudwatch_log_group.domain_events.arn
}

# ---------------------------------------------------------------------------
# Canal de notificacion de alarmas
# ---------------------------------------------------------------------------

resource "aws_sns_topic" "alarms" {
  name              = "${local.name}-alarms"
  kms_master_key_id = var.sns_kms_key_id

  tags = var.tags
}

resource "aws_sns_topic_subscription" "alarms" {
  for_each = var.alarm_email_subscriptions

  topic_arn = aws_sns_topic.alarms.arn
  protocol  = "email"
  endpoint  = each.value
}

# ---------------------------------------------------------------------------
# Alarmas
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "saga_failures" {
  alarm_name          = "${local.name}-saga-executions-failed"
  alarm_description   = "Ejecuciones fallidas de la saga de onboarding. Cada fallo es un caso de cliente que no avanzo."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.saga_failure_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = var.parent_state_machine_arn
  }

  alarm_actions = [aws_sns_topic.alarms.arn]
  ok_actions    = [aws_sns_topic.alarms.arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "saga_timeouts" {
  alarm_name          = "${local.name}-saga-executions-timed-out"
  alarm_description   = "Ejecuciones de la saga que agotaron su tiempo. Suele indicar revisiones manuales sin atender."
  namespace           = "AWS/States"
  metric_name         = "ExecutionsTimedOut"
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    StateMachineArn = var.parent_state_machine_arn
  }

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each = var.monitored_function_names

  alarm_name          = "${local.name}-lambda-errors-${each.key}"
  alarm_description   = "Errores de la funcion ${each.value}."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 2
  threshold           = var.lambda_error_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "lambda_throttles" {
  for_each = var.monitored_function_names

  alarm_name          = "${local.name}-lambda-throttles-${each.key}"
  alarm_description   = "Invocaciones estranguladas de ${each.value}. Revise la concurrencia reservada y la cuota de la cuenta."
  namespace           = "AWS/Lambda"
  metric_name         = "Throttles"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = each.value
  }

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "api_5xx" {
  alarm_name          = "${local.name}-api-5xx"
  alarm_description   = "Errores de servidor en la API. Afectan a todos los tenants por igual."
  namespace           = "AWS/ApiGateway"
  metric_name         = "5XXError"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.api_5xx_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    ApiName = var.api_name
    Stage   = var.api_stage_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "dynamodb_throttles" {
  alarm_name          = "${local.name}-dynamodb-throttled-requests"
  alarm_description   = "Peticiones estranguladas en la tabla core. Con capacidad on-demand suele indicar una clave de particion caliente."
  namespace           = "AWS/DynamoDB"
  metric_name         = "ThrottledRequests"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    TableName = var.core_table_name
  }

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = var.tags
}

# Indicador de salud del cifrado: un ratio alto de data keys unicas por registro
# delata un problema de coordinacion de cache (cache stampede) que dispara el
# coste de KMS. La metrica la emite el codigo por EMF.
resource "aws_cloudwatch_metric_alarm" "unique_data_key_ratio" {
  count = var.enable_crypto_health_alarm ? 1 : 0

  alarm_name          = "${local.name}-unique-data-key-ratio"
  alarm_description   = "Proporcion de data keys unicas por registro escrito. Un valor alto indica cache stampede en el material criptografico."
  namespace           = var.custom_metric_namespace
  metric_name         = "UniqueDataKeyRatio"
  statistic           = "Average"
  period              = 900
  evaluation_periods  = 2
  threshold           = var.unique_data_key_ratio_threshold
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  alarm_actions = [aws_sns_topic.alarms.arn]

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Muestreo de X-Ray
# ---------------------------------------------------------------------------

resource "aws_xray_sampling_rule" "onboarding" {
  count = var.enable_xray ? 1 : 0

  rule_name      = "${local.name}-onboarding"
  priority       = 1000
  version        = 1
  reservoir_size = var.xray_reservoir_size
  fixed_rate     = var.xray_fixed_rate
  service_name   = "*"
  service_type   = "*"
  host           = "*"
  http_method    = "*"
  url_path       = "/v1/*"
  resource_arn   = "*"
}

# ---------------------------------------------------------------------------
# Panel
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_dashboard" "main" {
  dashboard_name = "${local.name}-onboarding"

  dashboard_body = jsonencode({
    widgets = [
      {
        type       = "metric"
        x          = 0
        y          = 0
        width      = 12
        height     = 6
        properties = {
          title   = "Saga de onboarding"
          region  = data.aws_region.current.name
          view    = "timeSeries"
          stat    = "Sum"
          period  = 300
          metrics = [
            ["AWS/States", "ExecutionsStarted", "StateMachineArn", var.parent_state_machine_arn],
            [".", "ExecutionsSucceeded", ".", "."],
            [".", "ExecutionsFailed", ".", "."],
            [".", "ExecutionsTimedOut", ".", "."],
          ]
        }
      },
      {
        type       = "metric"
        x          = 12
        y          = 0
        width      = 12
        height     = 6
        properties = {
          title   = "API"
          region  = data.aws_region.current.name
          view    = "timeSeries"
          period  = 300
          metrics = [
            ["AWS/ApiGateway", "Count", "ApiName", var.api_name, "Stage", var.api_stage_name, { stat = "Sum" }],
            [".", "4XXError", ".", ".", ".", ".", { stat = "Sum" }],
            [".", "5XXError", ".", ".", ".", ".", { stat = "Sum" }],
            [".", "Latency", ".", ".", ".", ".", { stat = "p95" }],
          ]
        }
      },
      {
        type       = "metric"
        x          = 0
        y          = 6
        width      = 12
        height     = 6
        properties = {
          title   = "Tabla core"
          region  = data.aws_region.current.name
          view    = "timeSeries"
          stat    = "Sum"
          period  = 300
          metrics = [
            ["AWS/DynamoDB", "ConsumedReadCapacityUnits", "TableName", var.core_table_name],
            [".", "ConsumedWriteCapacityUnits", ".", "."],
            [".", "ThrottledRequests", ".", "."],
          ]
        }
      },
      {
        type       = "metric"
        x          = 12
        y          = 6
        width      = 12
        height     = 6
        properties = {
          title   = "Volumen por tenant (metricas EMF emitidas por el codigo)"
          region  = data.aws_region.current.name
          view    = "timeSeries"
          stat    = "Sum"
          period  = 300
          metrics = [
            [var.custom_metric_namespace, "CasesProcessed", "TenantId", "ALL"],
          ]
        }
      },
    ]
  })
}
