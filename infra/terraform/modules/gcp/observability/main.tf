# ---------------------------------------------------------------------------
# Observabilidad y auditoria en GCP.
#
# PUNTO CRITICO: los Data Access audit logs estan DESHABILITADOS POR DEFECTO
# (salvo BigQuery). Sin ellos no hay traza de quien leyo datos de que tenant, lo
# que en eKYC es un fallo de cumplimiento silencioso. Y aqui pesa mas que en
# AWS: como GCP no puede PREVENIR el acceso cruzado entre tenants, la DETECCION
# es la unica capa que queda.
#
# Este modulo habilita esos logs (tambien se declaran en gcp/identity para que
# el modulo de identidad sea autonomo; si se usan ambos, deje uno solo activo
# con `enable_audit_config` para evitar conflictos de propiedad del recurso).
#
# Instrumentacion: use OpenTelemetry. Es el denominador comun entre Cloud Trace
# y X-Ray; instrumentar con el SDK propio de cada nube duplica el trabajo.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"
}

# ---------------------------------------------------------------------------
# Bucket de logs con retencion explicita
#
# El bucket _Required (Admin Activity, System Event, Policy Denied) retiene 400
# dias y NO es configurable. El bucket _Default de un proyecto retiene 30 dias
# por defecto y admite de 1 a 3.650 dias.
# ---------------------------------------------------------------------------

resource "google_logging_project_bucket_config" "audit" {
  project        = var.project_id
  location       = var.log_bucket_location
  retention_days = var.audit_log_retention_days
  bucket_id      = "${local.name}-audit"
  description    = "Logs de auditoria del middleware de onboarding con retencion regulatoria."
}

resource "google_logging_project_sink" "audit" {
  project     = var.project_id
  name        = "${local.name}-audit-sink"
  description = "Enruta los logs de acceso a datos al bucket de auditoria."

  destination = "logging.googleapis.com/projects/${var.project_id}/locations/${var.log_bucket_location}/buckets/${google_logging_project_bucket_config.audit.bucket_id}"

  filter = join(" OR ", [
    "logName:\"cloudaudit.googleapis.com%2Fdata_access\"",
    "logName:\"cloudaudit.googleapis.com%2Factivity\"",
    "resource.type=\"audited_resource\"",
  ])

  unique_writer_identity = true
}

# Copia a Cloud Storage para retencion de anios y evidencia inmutable.
resource "google_logging_project_sink" "long_term" {
  count = var.long_term_sink_bucket == null ? 0 : 1

  project     = var.project_id
  name        = "${local.name}-long-term-sink"
  description = "Copia los logs de auditoria a Cloud Storage para retencion de anios."

  destination = "storage.googleapis.com/${var.long_term_sink_bucket}"

  filter = "logName:\"cloudaudit.googleapis.com%2Fdata_access\""

  unique_writer_identity = true
}

resource "google_storage_bucket_iam_member" "long_term_writer" {
  count = var.long_term_sink_bucket == null ? 0 : 1

  bucket = var.long_term_sink_bucket
  role   = "roles/storage.objectCreator"
  member = google_logging_project_sink.long_term[0].writer_identity
}

# Reduce el ruido de alto volumen. NUNCA excluya accesos a datos de tenant: son
# justamente los que hay que poder demostrar ante una auditoria.
resource "google_logging_project_exclusion" "health_checks" {
  project     = var.project_id
  name        = "${local.name}-exclude-health-checks"
  description = "Excluye las sondas de salud del bucket por defecto. No afecta a los logs de acceso a datos."

  filter = "resource.type=\"cloud_run_revision\" AND httpRequest.requestUrl:\"/healthz\""
}

# ---------------------------------------------------------------------------
# Data Access audit logs
# ---------------------------------------------------------------------------

resource "google_project_iam_audit_config" "data_access" {
  for_each = var.enable_audit_config ? toset(var.audited_services) : toset([])

  project = var.project_id
  service = each.value

  audit_log_config {
    log_type = "DATA_READ"
  }

  audit_log_config {
    log_type = "DATA_WRITE"
  }

  audit_log_config {
    log_type = "ADMIN_READ"
  }
}

# ---------------------------------------------------------------------------
# Metricas basadas en logs
# ---------------------------------------------------------------------------

# Deteccion de desalineacion entre el tenant del path y el del token. Esta es la
# metrica que compensa, por deteccion, la ausencia de aislamiento en el plano de
# datos. El codigo debe emitir esa entrada de log cuando detecte la anomalia.
resource "google_logging_metric" "tenant_scope_mismatch" {
  project     = var.project_id
  name        = "${local.name}-tenant-scope-mismatch"
  description = "Accesos en los que el tenant del recurso no coincide con el del token. Es la senal de un fallo de aislamiento."

  filter = "jsonPayload.event=\"tenant_scope_mismatch\" AND severity>=WARNING"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"

    labels {
      key         = "tenant_id"
      value_type  = "STRING"
      description = "Tenant del token."
    }
  }

  label_extractors = {
    tenant_id = "EXTRACT(jsonPayload.tenant_id)"
  }
}

resource "google_logging_metric" "decryption_failures" {
  project     = var.project_id
  name        = "${local.name}-decryption-failures"
  description = "Fallos de descifrado. Un pico indica un error de alcance de tenant que el Associated Data esta atajando: es la red de seguridad funcionando, y hay que investigarlo."

  filter = "jsonPayload.event=\"decryption_failed\""

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

# ---------------------------------------------------------------------------
# Alertas
# ---------------------------------------------------------------------------

resource "google_monitoring_notification_channel" "email" {
  for_each = var.alert_email_channels

  project      = var.project_id
  display_name = "Correo ${each.key}"
  type         = "email"

  labels = {
    email_address = each.value
  }
}

resource "google_monitoring_alert_policy" "tenant_scope_mismatch" {
  project      = var.project_id
  display_name = "${local.name}: desalineacion de alcance de tenant"
  combiner     = "OR"

  documentation {
    content   = "Se detecto un acceso cuyo tenant de recurso no coincide con el del token. En GCP no existe aislamiento multi-tenant en el plano de datos, asi que esta alerta es la principal capa de deteccion. Trate cada disparo como un incidente de seguridad, no como una anomalia operativa."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Cualquier desalineacion"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.tenant_scope_mismatch.name}\" AND resource.type=\"cloud_run_revision\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [for c in google_monitoring_notification_channel.email : c.id]

  alert_strategy {
    auto_close = "1800s"
  }
}

resource "google_monitoring_alert_policy" "workflow_failures" {
  project      = var.project_id
  display_name = "${local.name}: ejecuciones fallidas del workflow"
  combiner     = "OR"

  documentation {
    content   = "Ejecuciones fallidas de la saga de onboarding. Cada fallo es un caso de cliente que no avanzo."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Fallos por encima del umbral"

    condition_threshold {
      filter          = "metric.type=\"workflows.googleapis.com/finished_execution_count\" AND resource.type=\"workflows.googleapis.com/Workflow\" AND metric.label.status=\"FAILED\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.workflow_failure_threshold
      duration        = "300s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
}

resource "google_monitoring_alert_policy" "cloud_run_errors" {
  project      = var.project_id
  display_name = "${local.name}: errores 5xx en Cloud Run"
  combiner     = "OR"

  conditions {
    display_name = "Tasa de 5xx elevada"

    condition_threshold {
      filter          = "metric.type=\"run.googleapis.com/request_count\" AND resource.type=\"cloud_run_revision\" AND metric.label.response_code_class=\"5xx\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.cloud_run_5xx_threshold
      duration        = "300s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
}

resource "google_monitoring_alert_policy" "decryption_failures" {
  project      = var.project_id
  display_name = "${local.name}: fallos de descifrado"
  combiner     = "OR"

  documentation {
    content   = "Un pico de fallos de descifrado indica que el Associated Data esta rechazando un acceso con el tenant equivocado. La red de seguridad esta funcionando; investigue por que se llego a intentar."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Fallos de descifrado por encima del umbral"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.decryption_failures.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = var.decryption_failure_threshold
      duration        = "300s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = [for c in google_monitoring_notification_channel.email : c.id]
}

# ---------------------------------------------------------------------------
# Habilitacion de APIs de observabilidad
# ---------------------------------------------------------------------------

resource "google_project_service" "observability" {
  for_each = toset([
    "logging.googleapis.com",
    "monitoring.googleapis.com",
    "cloudtrace.googleapis.com",
  ])

  project = var.project_id
  service = each.value

  disable_on_destroy = false
}
