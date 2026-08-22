# ---------------------------------------------------------------------------
# Ejercicio del derecho de supresion y ciclo de vida de los datos personales.
#
# POR QUE ESTE MODULO EXISTE
# --------------------------
# Ni el TTL de DynamoDB ni las reglas de ciclo de vida de S3 son mecanismos de
# borrado garantizado: el TTL borra "tipicamente" dentro de 48 horas, sin
# transaccionalidad, y las reglas de S3 se aplican de forma asincrona. Ninguno
# sirve para acreditar ante un regulador que un dato se elimino.
#
# Ademas hay una tension real que no se resuelve borrando: la evidencia de
# auditoria vive bajo Object Lock y NO PUEDE borrarse hasta que expire su
# retencion. La unica via para dejarla ilegible es el crypto-shredding de la
# CMK del tenant (modulo aws/kms).
#
# ARQUITECTURA
# ------------
#   1. Un item de solicitud de supresion se escribe en la tabla core.
#   2. El stream dispara la Lambda de purga con la imagen previa y la posterior.
#   3. La Lambda borra objetos de S3 (todas las versiones), atributos cifrados
#      de DynamoDB, y registra el resultado como evidencia inmutable.
#   4. Lo que no puede borrarse se marca para crypto-shredding.
#   5. Un barrido programado reintenta lo pendiente y verifica la consistencia.
#
# Cualquier fallo va a una cola de mensajes fallidos con alarma: una purga que
# falla en silencio es un incumplimiento normativo, no un incidente operativo
# menor.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"
}

# ---------------------------------------------------------------------------
# Cola de mensajes fallidos
# ---------------------------------------------------------------------------

resource "aws_sqs_queue" "purge_dlq" {
  name                              = "${local.name}-gdpr-purge-dlq"
  message_retention_seconds         = var.dlq_retention_seconds
  kms_master_key_id                 = var.kms_key_arn
  kms_data_key_reuse_period_seconds = 300

  # Las solicitudes de supresion tienen plazo legal: la cola debe conservar el
  # mensaje el maximo posible para dar margen a la intervencion manual.
  tags = merge(var.tags, { "data-classification" = "restricted" })
}

resource "aws_sqs_queue_policy" "purge_dlq" {
  queue_url = aws_sqs_queue.purge_dlq.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Sid       = "DenyInsecureTransport"
        Effect    = "Deny"
        Principal = "*"
        Action    = "sqs:*"
        Resource  = aws_sqs_queue.purge_dlq.arn
        Condition = {
          Bool = { "aws:SecureTransport" = "false" }
        }
      }
    ]
  })
}

# ---------------------------------------------------------------------------
# Consumo del stream de la tabla core
# ---------------------------------------------------------------------------

resource "aws_lambda_event_source_mapping" "purge" {
  event_source_arn  = var.core_table_stream_arn
  function_name     = var.purge_function_arn
  starting_position = "TRIM_HORIZON"

  # Lote pequeno para minimizar la latencia entre la solicitud y la purga, y
  # para que un fallo afecte al menor numero posible de solicitudes.
  batch_size                         = var.batch_size
  maximum_batching_window_in_seconds = var.maximum_batching_window_seconds

  # DynamoDB Streams ordena por clave de particion: subir este factor paraleliza
  # entre particiones, nunca dentro de una misma.
  parallelization_factor = var.parallelization_factor

  # Sin estos limites, un registro venenoso bloquea el shard indefinidamente.
  maximum_retry_attempts         = var.maximum_retry_attempts
  maximum_record_age_in_seconds  = var.maximum_record_age_seconds
  bisect_batch_on_function_error = true

  destination_config {
    on_failure {
      destination_arn = aws_sqs_queue.purge_dlq.arn
    }
  }

  # Solo llegan a la funcion los eventos de solicitud de supresion: filtrar en
  # el origen evita invocaciones inutiles sobre cada escritura de la tabla.
  filter_criteria {
    filter {
      pattern = jsonencode({
        dynamodb = {
          NewImage = {
            entity_type = {
              S = ["ERASURE_REQUEST"]
            }
          }
        }
      })
    }
  }

  function_response_types = ["ReportBatchItemFailures"]
}

# ---------------------------------------------------------------------------
# Permisos adicionales de la funcion de purga
#
# Se adjuntan al rol de ejecucion compartido. Son los unicos permisos de borrado
# de todo el sistema: ninguna otra funcion puede borrar objetos de documentos ni
# de biometria.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "purge" {
  statement {
    sid     = "ReadCoreStream"
    effect  = "Allow"
    actions = [
      "dynamodb:DescribeStream",
      "dynamodb:GetRecords",
      "dynamodb:GetShardIterator",
      "dynamodb:ListStreams",
    ]
    resources = [var.core_table_stream_arn]
  }

  statement {
    sid     = "EraseTenantData"
    effect  = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
    ]
    resources = [var.core_table_arn, "${var.core_table_arn}/index/*"]
  }

  # Con versionado activo, un borrado ordinario solo crea un marcador. Para
  # suprimir de verdad hay que borrar TODAS las versiones de cada objeto.
  statement {
    sid     = "EraseObjectVersions"
    effect  = "Allow"
    actions = [
      "s3:DeleteObject",
      "s3:DeleteObjectVersion",
      "s3:ListBucketVersions",
      "s3:GetObject",
      "s3:GetObjectVersion",
    ]
    resources = concat(
      var.erasable_bucket_arns,
      [for arn in var.erasable_bucket_arns : "${arn}/*"],
    )
  }

  # La evidencia de la propia purga tambien es evidencia: se escribe en el
  # bucket WORM y no se borra jamas.
  statement {
    sid       = "WritePurgeEvidence"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:PutObjectRetention"]
    resources = ["${var.evidence_bucket_arn}/*"]
  }

  # Crypto-shredding de lo que no puede borrarse fisicamente.
  statement {
    sid       = "ScheduleTenantKeyDestruction"
    effect    = "Allow"
    actions   = ["kms:ScheduleKeyDeletion", "kms:DescribeKey"]
    resources = var.tenant_kms_key_arns
  }

  statement {
    sid       = "ReportFailures"
    effect    = "Allow"
    actions   = ["sqs:SendMessage"]
    resources = [aws_sqs_queue.purge_dlq.arn]
  }

  statement {
    sid       = "PublishErasureEvents"
    effect    = "Allow"
    actions   = ["events:PutEvents"]
    resources = [var.event_bus_arn]
  }
}

resource "aws_iam_role_policy" "purge" {
  name   = "${local.name}-gdpr-purge-policy"
  role   = var.purge_function_role_name
  policy = data.aws_iam_policy_document.purge.json
}

# ---------------------------------------------------------------------------
# Barrido programado
#
# El stream cubre el caso normal. El barrido cubre lo que el stream no vio:
# solicitudes anteriores al despliegue, reintentos de la cola de fallos, y
# expiraciones de retencion que nadie solicito pero que deben ejecutarse igual.
# ---------------------------------------------------------------------------

resource "aws_scheduler_schedule" "retention_sweep" {
  count = var.enable_retention_sweep ? 1 : 0

  name        = "${local.name}-retention-sweep"
  description = "Barrido periodico de retencion y de solicitudes de supresion pendientes."
  group_name  = "default"

  flexible_time_window {
    mode                      = "FLEXIBLE"
    maximum_window_in_minutes = 30
  }

  schedule_expression          = var.retention_sweep_schedule
  schedule_expression_timezone = var.retention_sweep_timezone

  target {
    arn      = var.purge_function_arn
    role_arn = aws_iam_role.scheduler[0].arn

    input = jsonencode({
      mode   = "RETENTION_SWEEP"
      source = "scheduler"
    })

    retry_policy {
      maximum_retry_attempts       = 3
      maximum_event_age_in_seconds = 3600
    }

    dead_letter_config {
      arn = aws_sqs_queue.purge_dlq.arn
    }
  }
}

resource "aws_iam_role" "scheduler" {
  count = var.enable_retention_sweep ? 1 : 0

  name = "${local.name}-gdpr-scheduler"

  assume_role_policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "scheduler.amazonaws.com" }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "scheduler" {
  count = var.enable_retention_sweep ? 1 : 0

  name = "${local.name}-gdpr-scheduler-policy"
  role = aws_iam_role.scheduler[0].id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [var.purge_function_arn]
      },
      {
        Effect   = "Allow"
        Action   = ["sqs:SendMessage"]
        Resource = [aws_sqs_queue.purge_dlq.arn]
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Alarmas de cumplimiento
#
# Una purga que falla en silencio es un incumplimiento normativo. El umbral es
# cero: cualquier fallo debe verse.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_metric_alarm" "purge_dlq_not_empty" {
  alarm_name          = "${local.name}-gdpr-purge-dlq-not-empty"
  alarm_description   = "Hay solicitudes de supresion sin procesar en la cola de fallos. Cada mensaje es un plazo legal corriendo."
  namespace           = "AWS/SQS"
  metric_name         = "ApproximateNumberOfMessagesVisible"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    QueueName = aws_sqs_queue.purge_dlq.name
  }

  alarm_actions = [var.alarms_topic_arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "purge_function_errors" {
  alarm_name          = "${local.name}-gdpr-purge-errors"
  alarm_description   = "Errores de la funcion de purga."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.purge_function_name
  }

  alarm_actions = [var.alarms_topic_arn]

  tags = var.tags
}

resource "aws_cloudwatch_metric_alarm" "purge_iterator_age" {
  alarm_name          = "${local.name}-gdpr-purge-iterator-age"
  alarm_description   = "El consumo del stream se esta retrasando. Los registros de DynamoDB Streams solo se retienen 24 horas: pasado ese plazo, la solicitud de supresion se pierde."
  namespace           = "AWS/Lambda"
  metric_name         = "IteratorAge"
  statistic           = "Maximum"
  period              = 300
  evaluation_periods  = 1
  threshold           = var.iterator_age_threshold_ms
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"

  dimensions = {
    FunctionName = var.purge_function_name
  }

  alarm_actions = [var.alarms_topic_arn]

  tags = var.tags
}
