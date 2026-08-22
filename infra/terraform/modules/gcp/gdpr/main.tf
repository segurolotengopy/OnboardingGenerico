# ---------------------------------------------------------------------------
# Derecho de supresion y retencion en GCP.
#
# Mismo problema que en AWS, con dos agravantes propios de GCP:
#
#   1. El borrado suave de Cloud Storage esta ACTIVO POR DEFECTO y retiene los
#      objetos 7 dias. El modulo gcp/storage lo desactiva; si alguien lo
#      reactiva, el borrado deja de ser borrado sin que nada falle.
#   2. Firestore con Eventarc NO permite reproducir el stream historico. Si el
#      trigger falla o no existia cuando se creo la solicitud, no hay forma de
#      rebobinar: hay que iterar la coleccion. Por eso el barrido programado no
#      es un extra, es parte del mecanismo.
#
# Y la tension de fondo es la misma: la evidencia bajo Bucket Lock NO puede
# borrarse. La unica via es el crypto-shredding de la llave del tenant, con la
# ventana de destroy_scheduled_duration de Cloud KMS (30 dias por defecto).
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"
}

# ---------------------------------------------------------------------------
# Job de purga
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_job" "purge" {
  name     = "${local.name}-gdpr-purge"
  project  = var.project_id
  location = var.region

  deletion_protection = var.enable_deletion_protection

  template {
    task_count  = 1
    parallelism = 1

    template {
      service_account = var.purge_service_account_email

      # Un job admite hasta 7 dias; una purga masiva de un tenant grande puede
      # tardar horas iterando versiones de objetos.
      timeout     = "${var.purge_timeout_seconds}s"
      max_retries = var.purge_max_retries

      containers {
        image = var.purge_image

        resources {
          limits = {
            cpu    = "1"
            memory = "2Gi"
          }
        }

        env {
          name  = "ENV"
          value = var.env
        }

        env {
          name  = "FIRESTORE_DATABASE"
          value = var.firestore_database_name
        }

        env {
          name  = "ERASABLE_BUCKETS"
          value = join(",", var.erasable_bucket_names)
        }

        env {
          name  = "EVIDENCE_BUCKET"
          value = var.evidence_bucket_name
        }

        env {
          name  = "MODE"
          value = "ERASURE"
        }
      }
    }
  }

  labels = merge(var.labels, { "data-classification" = "restricted" })
}

# ---------------------------------------------------------------------------
# Permisos de la identidad de purga
#
# Son los unicos permisos de borrado de todo el sistema.
# ---------------------------------------------------------------------------

resource "google_storage_bucket_iam_member" "purge_object_admin" {
  for_each = toset(var.erasable_bucket_names)

  bucket = each.value
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${var.purge_service_account_email}"
}

# Sobre el bucket WORM solo puede crear: la evidencia de la purga es evidencia.
resource "google_storage_bucket_iam_member" "purge_evidence_creator" {
  bucket = var.evidence_bucket_name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${var.purge_service_account_email}"
}

resource "google_project_iam_member" "purge_firestore" {
  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${var.purge_service_account_email}"
}

# El crypto-shredding es la ultima linea: destruir la llave del tenant deja
# ilegible lo que no puede borrarse. El rol se concede solo sobre las llaves de
# tenant, nunca sobre la de plataforma.
resource "google_kms_crypto_key_iam_member" "purge_shredding" {
  for_each = toset(var.tenant_key_ids)

  crypto_key_id = each.value
  role          = "roles/cloudkms.admin"
  member        = "serviceAccount:${var.purge_service_account_email}"
}

# ---------------------------------------------------------------------------
# Disparo por evento: solicitud de supresion escrita en Firestore
#
# ADVERTENCIA: Eventarc sobre Firestore no garantiza orden y no permite
# reproduccion. Este trigger cubre el camino feliz; el barrido programado cubre
# todo lo demas.
# ---------------------------------------------------------------------------

resource "google_eventarc_trigger" "erasure_requested" {
  count = var.enable_eventarc_trigger ? 1 : 0

  name     = "${local.name}-erasure-requested"
  project  = var.project_id
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.firestore.document.v1.created"
  }

  matching_criteria {
    attribute = "database"
    value     = var.firestore_database_name
  }

  matching_criteria {
    attribute = "document"
    operator  = "match-path-pattern"
    value     = "${var.erasure_requests_collection}/{requestId}"
  }

  # Eventarc no puede ejecutar un job directamente: dispara un servicio de Cloud
  # Run que lanza la ejecucion del job. Es un salto mas que en AWS, donde el
  # stream invoca la Lambda directamente.
  destination {
    cloud_run_service {
      service = var.dispatcher_service_name
      region  = var.region
      path    = "/internal/erasure-requested"
    }
  }

  service_account = var.purge_service_account_email

  transport {
    pubsub {
      topic = var.dead_letter_topic_id
    }
  }

  labels = var.labels
}

# ---------------------------------------------------------------------------
# Barrido programado
#
# No es un extra: al no haber reproduccion del stream, es el mecanismo que
# garantiza que ninguna solicitud se pierda.
# ---------------------------------------------------------------------------

resource "google_cloud_scheduler_job" "retention_sweep" {
  count = var.enable_retention_sweep ? 1 : 0

  name        = "${local.name}-retention-sweep"
  project     = var.project_id
  region      = var.region
  description = "Barrido de retencion y de solicitudes de supresion pendientes. Compensa la ausencia de reproduccion del stream de Firestore."
  schedule    = var.retention_sweep_schedule
  time_zone   = var.retention_sweep_timezone

  attempt_deadline = "320s"

  retry_config {
    retry_count          = 3
    min_backoff_duration = "10s"
    max_backoff_duration = "300s"
  }

  http_target {
    http_method = "POST"
    uri         = "https://${var.region}-run.googleapis.com/apis/run.googleapis.com/v1/namespaces/${var.project_id}/jobs/${google_cloud_run_v2_job.purge.name}:run"

    oauth_token {
      service_account_email = var.scheduler_service_account_email
      scope                 = "https://www.googleapis.com/auth/cloud-platform"
    }
  }
}

# ---------------------------------------------------------------------------
# Alertas de cumplimiento
#
# Una purga que falla en silencio es un incumplimiento normativo, no un
# incidente operativo menor.
# ---------------------------------------------------------------------------

resource "google_logging_metric" "purge_failures" {
  project     = var.project_id
  name        = "${local.name}-gdpr-purge-failures"
  description = "Fallos de la purga de datos personales."

  filter = "resource.type=\"cloud_run_job\" AND resource.labels.job_name=\"${google_cloud_run_v2_job.purge.name}\" AND severity>=ERROR"

  metric_descriptor {
    metric_kind = "DELTA"
    value_type  = "INT64"
    unit        = "1"
  }
}

resource "google_monitoring_alert_policy" "purge_failures" {
  project      = var.project_id
  display_name = "${local.name}: fallo de purga de datos personales"
  combiner     = "OR"

  documentation {
    content   = "La purga de datos personales fallo. Cada solicitud sin atender es un plazo legal corriendo. Revise si el fallo afecta a objetos de Cloud Storage, a documentos de Firestore o al crypto-shredding, y recuerde que el borrado suave debe estar desactivado para que un borrado sea un borrado."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Cualquier fallo de purga"

    condition_threshold {
      filter          = "metric.type=\"logging.googleapis.com/user/${google_logging_metric.purge_failures.name}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "0s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_SUM"
      }
    }
  }

  notification_channels = var.notification_channel_ids
}

resource "google_monitoring_alert_policy" "erasure_backlog" {
  count = var.dead_letter_subscription_id == null ? 0 : 1

  project      = var.project_id
  display_name = "${local.name}: solicitudes de supresion sin entregar"
  combiner     = "OR"

  documentation {
    content   = "Hay eventos de supresion en la suscripcion de mensajes fallidos. Firestore con Eventarc no permite reproducir el stream: si estos mensajes se pierden, la solicitud solo se recuperara con el barrido programado."
    mime_type = "text/markdown"
  }

  conditions {
    display_name = "Mensajes sin confirmar en la cola de fallos"

    condition_threshold {
      filter          = "metric.type=\"pubsub.googleapis.com/subscription/num_undelivered_messages\" AND resource.type=\"pubsub_subscription\" AND resource.labels.subscription_id=\"${var.dead_letter_subscription_id}\""
      comparison      = "COMPARISON_GT"
      threshold_value = 0
      duration        = "300s"

      aggregations {
        alignment_period   = "300s"
        per_series_aligner = "ALIGN_MAX"
      }
    }
  }

  notification_channels = var.notification_channel_ids
}
