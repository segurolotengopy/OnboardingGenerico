# ---------------------------------------------------------------------------
# Buckets S3 por clase de dato.
#
#   documents  - imagenes de documentos de identidad (anverso, reverso, MRZ)
#   biometrics - selfies, frames de liveness, embeddings faciales
#   evidence   - evidencia de auditoria inmutable (WORM con Object Lock)
#   staging    - artefactos intermedios efimeros (recortes, normalizaciones)
#
# Convencion de claves obligatoria en los tres primeros:
#
#   <tenantId>/<caseId>/<tipo>/<objeto>
#
# El primer segmento debe ser el tenant porque la politica ABAC del modulo
# `aws/identity` restringe por prefijo `${aws:PrincipalTag/TenantID}/`. Ningun
# objeto puede escribirse fuera de ese prefijo.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}

locals {
  name = "og-${var.env}"

  # Sufijo de unicidad global del nombre de bucket.
  suffix = var.bucket_name_suffix != "" ? var.bucket_name_suffix : data.aws_caller_identity.current.account_id

  buckets = {
    documents = {
      classification = "restricted"
      versioning     = true
      # Los documentos se consultan mucho durante el onboarding y casi nunca
      # despues. Transicion agresiva a clases frias.
      transitions = [
        { days = 30, storage_class = "STANDARD_IA" },
        { days = 90, storage_class = "GLACIER_IR" },
        { days = 365, storage_class = "DEEP_ARCHIVE" },
      ]
      expiration_days = var.document_retention_days
    }

    biometrics = {
      classification = "restricted"
      versioning     = true
      transitions = [
        { days = 30, storage_class = "STANDARD_IA" },
        { days = 180, storage_class = "GLACIER_IR" },
      ]
      # La biometria suele tener retencion mas corta que el documento: en varias
      # jurisdicciones es dato sensible de categoria especial.
      expiration_days = var.biometric_retention_days
    }

    staging = {
      classification  = "internal"
      versioning      = false
      transitions     = []
      expiration_days = var.staging_retention_days
    }
  }
}

# ---------------------------------------------------------------------------
# Buckets sin Object Lock
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "this" {
  for_each = local.buckets

  bucket        = "${local.name}-${each.key}-${local.suffix}"
  force_destroy = var.allow_force_destroy

  tags = merge(var.tags, { "data-classification" = each.value.classification })
}

resource "aws_s3_bucket_public_access_block" "this" {
  for_each = aws_s3_bucket.this

  bucket                  = each.value.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    object_ownership = "BucketOwnerEnforced" # deshabilita las ACL por completo
  }
}

resource "aws_s3_bucket_versioning" "this" {
  for_each = local.buckets

  bucket = aws_s3_bucket.this[each.key].id

  versioning_configuration {
    status = each.value.versioning ? "Enabled" : "Suspended"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    # Reduce drasticamente las llamadas a KMS reutilizando una data key de
    # bucket durante un intervalo corto.
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "this" {
  for_each = local.buckets

  bucket = aws_s3_bucket.this[each.key].id

  rule {
    id     = "transitions-and-expiration"
    status = "Enabled"

    filter {}

    dynamic "transition" {
      for_each = each.value.transitions
      content {
        days          = transition.value.days
        storage_class = transition.value.storage_class
      }
    }

    dynamic "expiration" {
      for_each = each.value.expiration_days == null ? [] : [each.value.expiration_days]
      content {
        days = expiration.value
      }
    }

    # Las subidas multiparte abortadas se cobran indefinidamente si no se limpian.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }

  dynamic "rule" {
    for_each = each.value.versioning ? [1] : []
    content {
      id     = "noncurrent-versions"
      status = "Enabled"

      filter {}

      noncurrent_version_expiration {
        noncurrent_days = var.noncurrent_version_retention_days
      }
    }
  }

  depends_on = [aws_s3_bucket_versioning.this]
}

# ---------------------------------------------------------------------------
# Bucket de evidencia WORM
#
# ADVERTENCIA: Object Lock SOLO puede habilitarse en la CREACION del bucket y
# exige versionado. No hay forma de habilitarlo despues sobre un bucket
# existente: habria que crear un bucket nuevo y copiar los objetos.
# ---------------------------------------------------------------------------

resource "aws_s3_bucket" "evidence" {
  bucket = "${local.name}-evidence-${local.suffix}"

  # Solo se puede fijar al crear el bucket. Cambiar este valor obliga a recrear.
  object_lock_enabled = true

  # Nunca force_destroy en un bucket WORM: con modo COMPLIANCE los objetos no
  # pueden borrarse ni siquiera por el root de la cuenta hasta que expire la
  # retencion.
  force_destroy = false

  tags = merge(var.tags, { "data-classification" = "restricted" })
}

resource "aws_s3_bucket_versioning" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  # Object Lock exige versionado habilitado; no puede suspenderse mientras haya
  # objetos retenidos.
  versioning_configuration {
    status = "Enabled"
  }
}

resource "aws_s3_bucket_object_lock_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    default_retention {
      # GOVERNANCE permite eludir la retencion con el permiso
      # s3:BypassGovernanceRetention; COMPLIANCE no lo permite a nadie, ni al
      # root de la cuenta. Use COMPLIANCE solo en produccion y solo cuando la
      # obligacion regulatoria lo exija.
      mode  = var.evidence_object_lock_mode
      years = var.evidence_retention_years
    }
  }

  depends_on = [aws_s3_bucket_versioning.evidence]
}

resource "aws_s3_bucket_public_access_block" "evidence" {
  bucket                  = aws_s3_bucket.evidence.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

resource "aws_s3_bucket_ownership_controls" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    object_ownership = "BucketOwnerEnforced"
  }
}

resource "aws_s3_bucket_server_side_encryption_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm     = "aws:kms"
      kms_master_key_id = var.kms_key_arn
    }
    bucket_key_enabled = true
  }
}

resource "aws_s3_bucket_lifecycle_configuration" "evidence" {
  bucket = aws_s3_bucket.evidence.id

  rule {
    id     = "archive-evidence"
    status = "Enabled"

    filter {}

    # La evidencia se escribe una vez y casi nunca se lee: solo ante auditoria o
    # requerimiento judicial. Glacier Instant Retrieval mantiene lectura en
    # milisegundos, que es lo que un auditor espera.
    transition {
      days          = 90
      storage_class = "GLACIER_IR"
    }

    # No hay regla de expiracion: el ciclo de vida NO puede borrar objetos
    # retenidos por Object Lock. La expiracion la marca la retencion WORM.
    abort_incomplete_multipart_upload {
      days_after_initiation = 7
    }
  }
}

# ---------------------------------------------------------------------------
# Politicas de bucket comunes
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "baseline" {
  for_each = merge(
    { for k, v in aws_s3_bucket.this : k => v.arn },
    { evidence = aws_s3_bucket.evidence.arn },
  )

  statement {
    sid       = "DenyInsecureTransport"
    effect    = "Deny"
    actions   = ["s3:*"]
    resources = [each.value, "${each.value}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "Bool"
      variable = "aws:SecureTransport"
      values   = ["false"]
    }
  }

  statement {
    sid       = "DenyUnencryptedObjectUploads"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${each.value}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption"
      values   = ["aws:kms"]
    }
  }

  statement {
    sid       = "DenyWrongKmsKey"
    effect    = "Deny"
    actions   = ["s3:PutObject"]
    resources = ["${each.value}/*"]

    principals {
      type        = "*"
      identifiers = ["*"]
    }

    condition {
      test     = "StringNotEquals"
      variable = "s3:x-amz-server-side-encryption-aws-kms-key-id"
      values   = [var.kms_key_arn]
    }
  }
}

resource "aws_s3_bucket_policy" "this" {
  for_each = aws_s3_bucket.this

  bucket = each.value.id
  policy = data.aws_iam_policy_document.baseline[each.key].json

  depends_on = [aws_s3_bucket_public_access_block.this]
}

resource "aws_s3_bucket_policy" "evidence" {
  bucket = aws_s3_bucket.evidence.id
  policy = data.aws_iam_policy_document.baseline["evidence"].json

  depends_on = [aws_s3_bucket_public_access_block.evidence]
}
