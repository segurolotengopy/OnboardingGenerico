# ---------------------------------------------------------------------------
# Identidad y ABAC multi-tenant en AWS.
#
# Cadena completa de aislamiento:
#
#   Cognito User Pool
#     -> trigger "pre token generation" V2_0 que inyecta el claim
#        https://aws.amazon.com/tags con principal_tags = { TenantID = [...] }
#     -> el cliente llama a sts:AssumeRoleWithWebIdentity contra el rol
#        tenant-scoped; la trust policy permite ADEMAS sts:TagSession, sin lo
#        cual los principal tags se descartan en silencio
#     -> las credenciales resultantes llevan aws:PrincipalTag/TenantID
#     -> DynamoDB aplica dynamodb:LeadingKeys y S3 aplica scoping por prefijo
#
# El trigger debe FALLAR CERRADO: si un usuario no tiene tenant asignado, no se
# emite token. Esa logica vive en el codigo de la Lambda (ver
# policies/cognito-pre-token-generation.md), no en Terraform.
# ---------------------------------------------------------------------------

data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name       = "og-${var.env}"
  account_id = data.aws_caller_identity.current.account_id
  partition  = data.aws_partition.current.partition

  issuer_host = "cognito-idp.${var.aws_region}.amazonaws.com"
  issuer_url  = "https://${local.issuer_host}/${aws_cognito_user_pool.this.id}"
}

# ---------------------------------------------------------------------------
# Cognito
# ---------------------------------------------------------------------------

resource "aws_cognito_user_pool" "this" {
  name = "${local.name}-users"

  # MFA obligatorio para operadores de revision manual; los usuarios finales del
  # onboarding no se autentican contra este pool (entran por el sistema
  # requirente), de ahi que el valor por defecto sea OPTIONAL y se endurezca
  # en produccion desde el entorno.
  mfa_configuration = var.mfa_configuration

  dynamic "software_token_mfa_configuration" {
    for_each = var.mfa_configuration == "OFF" ? [] : [1]
    content {
      enabled = true
    }
  }

  password_policy {
    minimum_length                   = 12
    require_lowercase                = true
    require_numbers                  = true
    require_symbols                  = true
    require_uppercase                = true
    temporary_password_validity_days = 3
  }

  # Atributo de tenant. Es inmutable a proposito: cambiar el tenant de un
  # usuario existente debe ser una operacion de provisioning, no una edicion
  # de perfil.
  schema {
    name                     = "tenant_id"
    attribute_data_type      = "String"
    mutable                  = false
    required                 = false
    developer_only_attribute = false

    string_attribute_constraints {
      min_length = 1
      max_length = 64
    }
  }

  # Trigger V2 de generacion de token. `lambda_version = "V2_0"` es obligatorio:
  # solo el evento V2 admite claimsAndScopeOverrideDetails y principal_tags.
  dynamic "lambda_config" {
    for_each = var.pre_token_generation_lambda_arn == null ? [] : [1]
    content {
      pre_token_generation_config {
        lambda_arn     = var.pre_token_generation_lambda_arn
        lambda_version = "V2_0"
      }
    }
  }

  user_pool_add_ons {
    advanced_security_mode = var.advanced_security_mode
  }

  deletion_protection = var.enable_deletion_protection ? "ACTIVE" : "INACTIVE"

  tags = var.tags
}

resource "aws_cognito_user_pool_client" "backend" {
  name         = "${local.name}-client"
  user_pool_id = aws_cognito_user_pool.this.id

  generate_secret               = true
  prevent_user_existence_errors = "ENABLED"

  # Solo flujos que no exponen credenciales al navegador.
  explicit_auth_flows = [
    "ALLOW_USER_SRP_AUTH",
    "ALLOW_REFRESH_TOKEN_AUTH",
  ]

  access_token_validity  = var.access_token_validity_minutes
  id_token_validity      = var.id_token_validity_minutes
  refresh_token_validity = var.refresh_token_validity_days

  token_validity_units {
    access_token  = "minutes"
    id_token      = "minutes"
    refresh_token = "days"
  }

  read_attributes  = ["email", "custom:tenant_id"]
  write_attributes = ["email"]
}

# Permiso para que Cognito invoque la Lambda del trigger.
resource "aws_lambda_permission" "pre_token_generation" {
  count = var.pre_token_generation_lambda_arn == null ? 0 : 1

  statement_id  = "AllowCognitoInvokePreTokenGeneration"
  action        = "lambda:InvokeFunction"
  function_name = var.pre_token_generation_lambda_arn
  principal     = "cognito-idp.amazonaws.com"
  source_arn    = aws_cognito_user_pool.this.arn
}

# ---------------------------------------------------------------------------
# Proveedor OIDC: necesario para AssumeRoleWithWebIdentity contra el user pool
# ---------------------------------------------------------------------------

resource "aws_iam_openid_connect_provider" "cognito" {
  url             = local.issuer_url
  client_id_list  = [aws_cognito_user_pool_client.backend.id]
  thumbprint_list = var.oidc_thumbprints

  tags = merge(var.tags, { Name = "${local.name}-oidc-cognito" })
}

# ---------------------------------------------------------------------------
# Rol tenant-scoped: el corazon del ABAC
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "tenant_trust" {
  statement {
    sid    = "AssumeWithTenantSessionTag"
    effect = "Allow"

    # sts:TagSession es OBLIGATORIO. Sin esta accion la federacion funciona pero
    # los principal tags se descartan y todas las politicas de datos deniegan.
    actions = [
      "sts:AssumeRoleWithWebIdentity",
      "sts:TagSession",
    ]

    principals {
      type        = "Federated"
      identifiers = [aws_iam_openid_connect_provider.cognito.arn]
    }

    condition {
      test     = "StringEquals"
      variable = "${local.issuer_host}/${aws_cognito_user_pool.this.id}:aud"
      values   = [aws_cognito_user_pool_client.backend.id]
    }

    # Solo se admite el tag TenantID como tag transitivo de sesion. Limitar el
    # conjunto de claves evita que un token manipulado inyecte tags adicionales.
    condition {
      test     = "ForAllValues:StringEquals"
      variable = "sts:TransitiveTagKeys"
      values   = ["TenantID"]
    }
  }
}

resource "aws_iam_role" "tenant_scoped" {
  name                 = "${local.name}-tenant-scoped"
  description          = "Rol asumido por sesion de tenant. Recibe TenantID como session tag."
  assume_role_policy   = data.aws_iam_policy_document.tenant_trust.json
  max_session_duration = var.tenant_session_duration_seconds

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Politica ABAC sobre DynamoDB
#
# `dynamodb:LeadingKeys` es plural incluso para acciones de item unico y exige
# el modificador de conjunto ForAllValues:. Restringe la partition key de la
# TABLA BASE; un LSI hereda la proteccion, un GSI NO. Por eso todos los GSI del
# modulo `aws/data` llevan el tenant en su propia partition key.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "tenant_dynamodb" {
  statement {
    sid    = "TenantScopedItemAccess"
    effect = "Allow"

    actions = [
      "dynamodb:GetItem",
      "dynamodb:BatchGetItem",
      "dynamodb:Query",
      "dynamodb:PutItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
      "dynamodb:BatchWriteItem",
      "dynamodb:ConditionCheckItem",
    ]

    resources = concat(
      var.tenant_table_arns,
      [for arn in var.tenant_table_arns : "${arn}/index/*"],
    )

    condition {
      test     = "ForAllValues:StringEquals"
      variable = "dynamodb:LeadingKeys"
      # `$${...}` produce la variable de politica literal ${aws:PrincipalTag/TenantID}
      # y no una interpolacion de Terraform.
      values = ["TENANT#$${aws:PrincipalTag/TenantID}"]
    }
  }

  # Denegacion explicita de Scan: una operacion de tabla completa escapa a
  # LeadingKeys porque no declara claves.
  statement {
    sid       = "DenyFullTableScan"
    effect    = "Deny"
    actions   = ["dynamodb:Scan"]
    resources = concat(var.tenant_table_arns, [for arn in var.tenant_table_arns : "${arn}/index/*"])
  }
}

# ---------------------------------------------------------------------------
# Politica ABAC sobre S3: scoping por prefijo ${TenantID}/
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "tenant_s3" {
  statement {
    sid    = "TenantObjectAccess"
    effect = "Allow"

    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
      "s3:GetObjectVersion",
    ]

    resources = [for arn in var.tenant_bucket_arns : "${arn}/$${aws:PrincipalTag/TenantID}/*"]
  }

  # ListBucket actua sobre el bucket, no sobre el objeto: se condiciona por
  # s3:prefix en una sentencia separada.
  statement {
    sid       = "TenantScopedList"
    effect    = "Allow"
    actions   = ["s3:ListBucket"]
    resources = var.tenant_bucket_arns

    condition {
      test     = "StringLike"
      variable = "s3:prefix"
      values   = ["$${aws:PrincipalTag/TenantID}/*"]
    }
  }

  # El cifrado de sobre ata el texto cifrado al tenant via encryption context.
  # Un error de alcance produce AccessDenied en decrypt, no una fuga.
  statement {
    sid    = "TenantScopedKmsUsage"
    effect = "Allow"

    actions = [
      "kms:Decrypt",
      "kms:Encrypt",
      "kms:GenerateDataKey",
      "kms:DescribeKey",
    ]

    resources = var.tenant_kms_key_arns

    condition {
      test     = "StringEquals"
      variable = "kms:EncryptionContext:tenant"
      values   = ["$${aws:PrincipalTag/TenantID}"]
    }
  }
}

resource "aws_iam_policy" "tenant_dynamodb" {
  name        = "${local.name}-tenant-abac-dynamodb"
  description = "ABAC de DynamoDB por dynamodb:LeadingKeys con el session tag TenantID."
  policy      = data.aws_iam_policy_document.tenant_dynamodb.json
  tags        = var.tags
}

resource "aws_iam_policy" "tenant_s3" {
  name        = "${local.name}-tenant-abac-s3"
  description = "ABAC de S3 y KMS por prefijo de objeto y encryption context del tenant."
  policy      = data.aws_iam_policy_document.tenant_s3.json
  tags        = var.tags
}

resource "aws_iam_role_policy_attachment" "tenant_dynamodb" {
  role       = aws_iam_role.tenant_scoped.name
  policy_arn = aws_iam_policy.tenant_dynamodb.arn
}

resource "aws_iam_role_policy_attachment" "tenant_s3" {
  role       = aws_iam_role.tenant_scoped.name
  policy_arn = aws_iam_policy.tenant_s3.arn
}

# ---------------------------------------------------------------------------
# Rol de plataforma: lo asume el propio middleware para operaciones que NO son
# de un tenant concreto (provisioning, purga GDPR, agregados de facturacion).
# No lleva LeadingKeys, por eso su uso debe ser minimo y auditado.
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "platform_trust" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "AWS"
      identifiers = var.platform_role_trusted_principals
    }
  }
}

resource "aws_iam_role" "platform" {
  count = length(var.platform_role_trusted_principals) > 0 ? 1 : 0

  name               = "${local.name}-platform"
  description        = "Rol de operaciones transversales sin scoping de tenant. Uso minimo y auditado."
  assume_role_policy = data.aws_iam_policy_document.platform_trust.json

  tags = var.tags
}
