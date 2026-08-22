# ---------------------------------------------------------------------------
# Llaves KMS: una de plataforma y una CMK por tenant.
#
# CRYPTO-SHREDDING
# ----------------
# La CMK por tenant existe para poder ejercer el derecho de supresion sin
# recorrer petabytes de objetos: al programar la destruccion de la llave del
# tenant, todo su material cifrado (documentos en S3, campos en DynamoDB,
# evidencia WORM que no puede borrarse por Object Lock) queda ilegible de forma
# permanente. La ventana de espera de AWS KMS es de 7 a 30 dias y el minimo
# duro es 7: cualquier SLA de borrado prometido al cliente debe ser mayor que
# `deletion_window_in_days` mas margen operativo.
#
# COSTE
# -----
# Cada CMK cuesta del orden de 1 USD/mes por su mera existencia, mas otro tanto
# cuando la rotacion esta activa. Con miles de tenants esto deja de ser
# despreciable. El patron alternativo es el HIERARCHICAL KEYRING: una sola CMK
# de plataforma y una BRANCH KEY por tenant en DynamoDB (tabla `keystore` del
# modulo `aws/data`), que da aislamiento criptografico por tenant sin coste por
# llave. Use `var.tenants` para tenants regulados que exijan CMK demostrable y
# branch keys para el resto.
#
# NO USE `CachingCryptoMaterialsManager`: en entornos concurrentes su expiracion
# sin coordinacion provoca cache stampede (N hilos generan N data keys
# distintas). La recomendacion de AWS es el hierarchical keyring, cuya cache
# refresca con una sola carga y ventana de pre-expiracion.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "og-${var.env}"
  account_id = data.aws_caller_identity.current.account_id
  root_arn   = "arn:${data.aws_partition.current.partition}:iam::${data.aws_caller_identity.current.account_id}:root"
}

# ---------------------------------------------------------------------------
# Politica de la llave de plataforma
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "platform_key" {
  # Sin esta sentencia la llave queda huerfana: IAM no puede conceder permisos
  # sobre ella y no hay forma de recuperarla.
  statement {
    sid       = "EnableIamUserPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.root_arn]
    }
  }

  statement {
    sid    = "AllowKeyAdministration"
    effect = "Allow"

    actions = [
      "kms:Create*",
      "kms:Describe*",
      "kms:Enable*",
      "kms:List*",
      "kms:Put*",
      "kms:Update*",
      "kms:Revoke*",
      "kms:Disable*",
      "kms:Get*",
      "kms:Delete*",
      "kms:ScheduleKeyDeletion",
      "kms:CancelKeyDeletion",
    ]

    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = length(var.key_administrator_arns) > 0 ? var.key_administrator_arns : [local.root_arn]
    }
  }

  statement {
    sid    = "AllowServiceUse"
    effect = "Allow"

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:ReEncrypt*",
      "kms:GenerateDataKey*",
      "kms:DescribeKey",
    ]

    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = length(var.platform_key_user_arns) > 0 ? var.platform_key_user_arns : [local.root_arn]
    }
  }

  # Permite que servicios de AWS (S3, DynamoDB, CloudWatch Logs) usen la llave
  # a traves de un principal de servicio, acotado a esta cuenta.
  statement {
    sid    = "AllowAwsServicesViaGrants"
    effect = "Allow"

    actions = [
      "kms:CreateGrant",
      "kms:ListGrants",
      "kms:RevokeGrant",
    ]

    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.root_arn]
    }

    condition {
      test     = "Bool"
      variable = "kms:GrantIsForAWSResource"
      values   = ["true"]
    }
  }
}

resource "aws_kms_key" "platform" {
  description             = "Llave de plataforma del middleware de onboarding (${var.env}): cifrado en reposo de tablas, logs y buckets compartidos."
  deletion_window_in_days = var.deletion_window_in_days
  enable_key_rotation     = true # rotacion automatica anual
  rotation_period_in_days = var.rotation_period_in_days
  multi_region            = var.platform_key_multi_region
  policy                  = data.aws_iam_policy_document.platform_key.json

  tags = merge(var.tags, { "data-classification" = "restricted" })
}

resource "aws_kms_alias" "platform" {
  name          = "alias/${local.name}-platform"
  target_key_id = aws_kms_key.platform.key_id
}

# ---------------------------------------------------------------------------
# CMK por tenant
#
# `for_each` sobre el mapa de tenants: agregar un tenant al mapa crea su llave
# y su alias sin tocar las de los demas. Cada llave se condiciona por
# `kms:EncryptionContext:tenant`, de modo que el material cifrado queda atado
# criptograficamente a su tenant: un error de alcance produce un fallo de
# descifrado, no una fuga.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "tenant_key" {
  for_each = var.tenants

  statement {
    sid       = "EnableIamUserPermissions"
    effect    = "Allow"
    actions   = ["kms:*"]
    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = [local.root_arn]
    }
  }

  statement {
    sid    = "TenantScopedCryptographicUse"
    effect = "Allow"

    actions = [
      "kms:Encrypt",
      "kms:Decrypt",
      "kms:GenerateDataKey",
      "kms:GenerateDataKeyWithoutPlaintext",
      "kms:DescribeKey",
    ]

    resources = ["*"]

    principals {
      type        = "AWS"
      identifiers = length(var.tenant_key_user_arns) > 0 ? var.tenant_key_user_arns : [local.root_arn]
    }

    # El encryption context debe coincidir EXACTAMENTE con el usado al cifrar.
    # Una discrepancia falla en el descifrado, no en el cifrado: es un error
    # dificil de detectar en pruebas.
    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:tenant"
      values   = [each.key]
    }
  }
}

resource "aws_kms_key" "tenant" {
  for_each = var.tenants

  description             = "CMK del tenant ${each.key} (${var.env}). Su destruccion implementa el crypto-shredding del tenant."
  deletion_window_in_days = var.deletion_window_in_days
  enable_key_rotation     = true
  rotation_period_in_days = var.rotation_period_in_days
  policy                  = data.aws_iam_policy_document.tenant_key[each.key].json

  tags = merge(
    var.tags,
    {
      "data-classification" = "restricted"
      "tenant-id"           = each.key
      "tenant-tier"         = try(each.value.tier, "standard")
    },
  )
}

resource "aws_kms_alias" "tenant" {
  for_each = var.tenants

  name          = "alias/${local.name}-tenant-${each.key}"
  target_key_id = aws_kms_key.tenant[each.key].key_id
}

# ---------------------------------------------------------------------------
# Grants por tenant
#
# ADVERTENCIA DE CUOTA: `CreateGrant` esta limitada a 50 peticiones por segundo,
# cuota independiente de las operaciones criptograficas. Los grants deben
# crearse en el flujo de PROVISIONING del tenant (aqui, en Terraform), nunca en
# el flujo de peticion.
# ---------------------------------------------------------------------------

resource "aws_kms_grant" "tenant_data_access" {
  for_each = var.tenant_grant_principal_arn == null ? {} : var.tenants

  name              = "${local.name}-grant-${each.key}"
  key_id            = aws_kms_key.tenant[each.key].key_id
  grantee_principal = var.tenant_grant_principal_arn

  operations = [
    "Encrypt",
    "Decrypt",
    "GenerateDataKey",
    "DescribeKey",
  ]

  constraints {
    encryption_context_equals = {
      tenant = each.key
    }
  }
}
