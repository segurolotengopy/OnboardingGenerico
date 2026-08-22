# ---------------------------------------------------------------------------
# Buckets de Cloud Storage por clase de dato.
#
# Es la capacidad que mejor se porta desde S3, con dos diferencias que hay que
# tener presentes:
#
#   1. SOFT DELETE ESTA ACTIVO POR DEFECTO en GCS y retiene los objetos borrados
#      durante 7 dias. Para el derecho de supresion eso significa que un
#      `Delete` NO es un borrado. Este modulo lo DESACTIVA de forma explicita en
#      los buckets con datos personales.
#   2. Archive de GCS recupera en milisegundos, no en horas como Glacier Deep
#      Archive. Es una ventaja real: la evidencia archivada sigue siendo
#      consultable de inmediato ante un requerimiento.
#
# Convencion de objetos: <tenantId>/<caseId>/<tipo>/<objeto>. El primer segmento
# debe ser el tenant porque las condiciones de IAM del modulo gcp/identity
# restringen con resource.name.startsWith(...).
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"

  buckets = {
    documents = {
      classification = "restricted"
      versioning     = true
      transitions = [
        { age = 30, storage_class = "NEARLINE" },
        { age = 90, storage_class = "COLDLINE" },
        { age = 365, storage_class = "ARCHIVE" },
      ]
      expiration_age = var.document_retention_days
    }

    biometrics = {
      classification = "restricted"
      versioning     = true
      transitions = [
        { age = 30, storage_class = "NEARLINE" },
        { age = 180, storage_class = "COLDLINE" },
      ]
      expiration_age = var.biometric_retention_days
    }

    staging = {
      classification = "internal"
      versioning     = false
      transitions    = []
      expiration_age = var.staging_retention_days
    }
  }
}

resource "google_storage_bucket" "this" {
  for_each = local.buckets

  name     = "${local.name}-${each.key}-${var.bucket_name_suffix}"
  project  = var.project_id
  location = var.location

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true # desactiva las ACL por objeto
  public_access_prevention    = "enforced"

  force_destroy = var.allow_force_destroy

  versioning {
    enabled = each.value.versioning
  }

  # Un `Delete` debe ser un borrado. Con la politica por defecto, GCS retiene
  # los objetos borrados 7 dias, lo que es incompatible con el derecho de
  # supresion. `retention_duration_seconds = 0` desactiva la retencion suave.
  soft_delete_policy {
    retention_duration_seconds = var.soft_delete_retention_seconds
  }

  encryption {
    default_kms_key_name = var.cmek_key_name
  }

  dynamic "lifecycle_rule" {
    for_each = each.value.transitions
    content {
      action {
        type          = "SetStorageClass"
        storage_class = lifecycle_rule.value.storage_class
      }
      condition {
        age = lifecycle_rule.value.age
      }
    }
  }

  dynamic "lifecycle_rule" {
    for_each = each.value.expiration_age == null ? [] : [each.value.expiration_age]
    content {
      action {
        type = "Delete"
      }
      condition {
        age = lifecycle_rule.value
      }
    }
  }

  dynamic "lifecycle_rule" {
    for_each = each.value.versioning ? [1] : []
    content {
      action {
        type = "Delete"
      }
      condition {
        days_since_noncurrent_time = var.noncurrent_version_retention_days
      }
    }
  }

  lifecycle_rule {
    action {
      type = "AbortIncompleteMultipartUpload"
    }
    condition {
      age = 7
    }
  }

  labels = merge(var.labels, { "data-classification" = each.value.classification })
}

# ---------------------------------------------------------------------------
# Bucket de evidencia WORM
#
# El equivalente de S3 Object Lock es la retention policy del bucket
# (Bucket Lock). Cuando `is_locked = true`, la politica NO puede acortarse ni
# eliminarse: solo alargarse. Es irreversible, incluida la imposibilidad de
# borrar el bucket hasta que expire la retencion de todos sus objetos.
# ---------------------------------------------------------------------------

resource "google_storage_bucket" "evidence" {
  name     = "${local.name}-evidence-${var.bucket_name_suffix}"
  project  = var.project_id
  location = var.location

  storage_class               = "STANDARD"
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"

  # Nunca en un bucket WORM.
  force_destroy = false

  versioning {
    enabled = true
  }

  # La evidencia no se borra: la retencion suave no aporta nada y solo genera
  # coste y confusion.
  soft_delete_policy {
    retention_duration_seconds = 0
  }

  encryption {
    default_kms_key_name = var.cmek_key_name
  }

  retention_policy {
    retention_period = var.evidence_retention_years * 365 * 24 * 3600

    # ADVERTENCIA: irreversible. Una vez bloqueada, la politica solo puede
    # alargarse. Actívelo solo en produccion y solo cuando la obligacion
    # regulatoria lo exija.
    is_locked = var.lock_evidence_retention
  }

  # Archive de GCS recupera en milisegundos: la evidencia archivada sigue siendo
  # consultable de inmediato.
  lifecycle_rule {
    action {
      type          = "SetStorageClass"
      storage_class = "ARCHIVE"
    }
    condition {
      age = 90
    }
  }

  labels = merge(var.labels, { "data-classification" = "restricted" })
}

# ---------------------------------------------------------------------------
# Acceso del runtime
# ---------------------------------------------------------------------------

resource "google_storage_bucket_iam_member" "runtime_object_user" {
  for_each = var.runtime_service_account_email == null ? {} : google_storage_bucket.this

  bucket = each.value.name
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${var.runtime_service_account_email}"
}

# Sobre el bucket WORM el runtime solo puede crear y leer, nunca borrar.
resource "google_storage_bucket_iam_member" "runtime_evidence_writer" {
  count = var.runtime_service_account_email == null ? 0 : 1

  bucket = google_storage_bucket.evidence.name
  role   = "roles/storage.objectCreator"
  member = "serviceAccount:${var.runtime_service_account_email}"
}

resource "google_storage_bucket_iam_member" "runtime_evidence_reader" {
  count = var.runtime_service_account_email == null ? 0 : 1

  bucket = google_storage_bucket.evidence.name
  role   = "roles/storage.objectViewer"
  member = "serviceAccount:${var.runtime_service_account_email}"
}
