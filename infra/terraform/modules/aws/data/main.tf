# ---------------------------------------------------------------------------
# Capa de datos en DynamoDB.
#
# Cuatro tablas, cada una con una razon de existir distinta:
#
#   1. core         - single-table del dominio (casos, documentos, decisiones)
#   2. capabilities - Registro de Capacidades: que proveedor cubre que paso,
#                     para que pais y para que tipo de documento
#   3. locks        - mutex distribuido con TTL y fencing token
#   4. keystore     - branch keys del hierarchical keyring (AWS Database
#                     Encryption SDK). Ver advertencias del README.
#
# Convencion de claves de la tabla core (fijada el dia uno; `LeadingKeys` no es
# retrofitable sin migracion de datos):
#
#   PK = TENANT#<tenantId>
#   SK = CASE#<caseId> | CASE#<caseId>#DOC#<docId> | CASE#<caseId>#STEP#<stepId>
#
# Todos los GSI llevan el tenant en su propia partition key porque
# `dynamodb:LeadingKeys` NO cubre los indices globales.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"

  # Indices globales de la tabla core. GSI1PK y GSI2PK siempre empiezan por
  # TENANT#<tenantId> para permanecer dentro del perimetro ABAC.
  core_gsis = [
    {
      # Busqueda de casos por estado: GSI1PK = TENANT#<t>#STATUS#<estado>
      name               = "GSI1"
      hash_key           = "GSI1PK"
      range_key          = "GSI1SK"
      projection_type    = "INCLUDE"
      non_key_attributes = [
        "case_status",
        "case_created_at",
        "case_country",
        "case_document_type",
      ]
    },
    {
      # Cola de revision manual: GSI2PK = TENANT#<t>#REVIEW#<prioridad>
      name               = "GSI2"
      hash_key           = "GSI2PK"
      range_key          = "GSI2SK"
      projection_type    = "KEYS_ONLY"
      non_key_attributes = null
    },
    {
      # Indice de beacon del AWS Database Encryption SDK. El nombre del atributo
      # lo fija la libreria (prefijo aws_dbe_b_). Se construye como beacon
      # compuesto con el tenant como primera parte para no romper el ABAC.
      name               = "GSI3-beacon"
      hash_key           = "aws_dbe_b_TenantScopedIdentityCompound"
      range_key          = null
      projection_type    = "KEYS_ONLY"
      non_key_attributes = null
    },
  ]

  core_attributes = [
    { name = "PK", type = "S" },
    { name = "SK", type = "S" },
    { name = "GSI1PK", type = "S" },
    { name = "GSI1SK", type = "S" },
    { name = "GSI2PK", type = "S" },
    { name = "GSI2SK", type = "S" },
    { name = "aws_dbe_b_TenantScopedIdentityCompound", type = "S" },
  ]
}

# ---------------------------------------------------------------------------
# Tabla core
#
# `prevent_destroy` no admite expresiones ni variables en Terraform ni en
# OpenTofu: solo literales. Por eso la tabla se declara dos veces y se
# selecciona con `count`. Es feo, pero es la unica forma real de tener
# proteccion contra `terraform destroy` en prd y no tenerla en dev.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "core" {
  count = var.protect_from_destroy ? 0 : 1

  name         = "${local.name}-core"
  billing_mode = var.billing_mode
  hash_key     = "PK"
  range_key    = "SK"

  read_capacity  = var.billing_mode == "PROVISIONED" ? var.provisioned_read_capacity : null
  write_capacity = var.billing_mode == "PROVISIONED" ? var.provisioned_write_capacity : null

  deletion_protection_enabled = var.enable_deletion_protection
  table_class                 = var.table_class

  dynamic "attribute" {
    for_each = local.core_attributes
    content {
      name = attribute.value.name
      type = attribute.value.type
    }
  }

  dynamic "global_secondary_index" {
    for_each = local.core_gsis
    content {
      name               = global_secondary_index.value.name
      hash_key           = global_secondary_index.value.hash_key
      range_key          = global_secondary_index.value.range_key
      projection_type    = global_secondary_index.value.projection_type
      non_key_attributes = global_secondary_index.value.non_key_attributes
    }
  }

  # TTL: solo para artefactos efimeros (payloads intermedios, tokens de tarea).
  # Los items de caso NUNCA llevan `expires_at`: la retencion KYC/AML es de
  # anios, no de dias, y el borrado TTL de DynamoDB no es garantizado ni
  # transaccional (tipicamente hasta 48 h de retraso).
  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  # NEW_AND_OLD_IMAGES es requisito de la Lambda de purga GDPR: necesita la
  # imagen previa para saber que objetos de S3 y que llaves borrar.
  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = merge(var.tags, { "data-classification" = "restricted" })
}

resource "aws_dynamodb_table" "core_protected" {
  count = var.protect_from_destroy ? 1 : 0

  name         = "${local.name}-core"
  billing_mode = var.billing_mode
  hash_key     = "PK"
  range_key    = "SK"

  read_capacity  = var.billing_mode == "PROVISIONED" ? var.provisioned_read_capacity : null
  write_capacity = var.billing_mode == "PROVISIONED" ? var.provisioned_write_capacity : null

  deletion_protection_enabled = var.enable_deletion_protection
  table_class                 = var.table_class

  dynamic "attribute" {
    for_each = local.core_attributes
    content {
      name = attribute.value.name
      type = attribute.value.type
    }
  }

  dynamic "global_secondary_index" {
    for_each = local.core_gsis
    content {
      name               = global_secondary_index.value.name
      hash_key           = global_secondary_index.value.hash_key
      range_key          = global_secondary_index.value.range_key
      projection_type    = global_secondary_index.value.projection_type
      non_key_attributes = global_secondary_index.value.non_key_attributes
    }
  }

  ttl {
    attribute_name = "expires_at"
    enabled        = true
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  stream_enabled   = true
  stream_view_type = "NEW_AND_OLD_IMAGES"

  tags = merge(var.tags, { "data-classification" = "restricted" })

  lifecycle {
    prevent_destroy = true
  }
}

# ---------------------------------------------------------------------------
# Registro de Capacidades
#
# Describe que proveedor implementa que capacidad (OCR, liveness, face match,
# listas AML) para que pais y tipo de documento, con su version y su estado.
# Es el dato que hace dinamica la composicion de pasos: el flujo no esta
# cableado en la maquina de estados, se resuelve en tiempo de ejecucion.
#
#   PK = CAPABILITY#<capabilityId>          (p. ej. CAPABILITY#ocr-mrz)
#   SK = COUNTRY#<iso2>#DOCTYPE#<tipo>#V<n>
#
# No lleva prefijo TENANT# porque es un catalogo de plataforma, compartido y de
# solo lectura para los tenants. Por eso NO se incluye en `tenant_table_arns`
# del modulo de identidad: se lee con el rol de plataforma o con una politica
# de solo lectura sin LeadingKeys.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "capabilities" {
  name         = "${local.name}-capability-registry"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"
  range_key    = "SK"

  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "PK"
    type = "S"
  }

  attribute {
    name = "SK"
    type = "S"
  }

  attribute {
    name = "GSI1PK"
    type = "S"
  }

  attribute {
    name = "GSI1SK"
    type = "S"
  }

  # Consulta inversa: dado un pais y tipo de documento, que capacidades existen.
  # GSI1PK = COUNTRY#<iso2>#DOCTYPE#<tipo>
  global_secondary_index {
    name            = "GSI1"
    hash_key        = "GSI1PK"
    range_key       = "GSI1SK"
    projection_type = "ALL"
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  # El catalogo alimenta una cache en proceso; el stream invalida esa cache.
  stream_enabled   = true
  stream_view_type = "NEW_IMAGE"

  tags = merge(var.tags, { "data-classification" = "internal" })
}

# ---------------------------------------------------------------------------
# Mutex distribuido
#
# Evita que dos ejecuciones procesen el mismo caso a la vez (reintentos
# at-least-once de los workflows Express, reproceso de stream, doble entrega de
# webhook). El patron es: PutItem condicional sobre attribute_not_exists(PK) OR
# lock_expires_at < now, con `fencing_token` incremental para detectar
# titulares obsoletos.
#
#   PK = LOCK#<tenantId>#<recurso>
#
# El TTL es la red de seguridad ante un proceso que muera con el lock tomado.
# ADVERTENCIA: el borrado por TTL puede tardar horas; la expiracion real debe
# evaluarse en la condicion de escritura leyendo `lock_expires_at`, nunca
# confiando en que el item ya no exista.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "locks" {
  name         = "${local.name}-locks"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "PK"

  deletion_protection_enabled = false

  attribute {
    name = "PK"
    type = "S"
  }

  ttl {
    attribute_name = "lock_expires_at"
    enabled        = true
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(var.tags, { "data-classification" = "internal" })
}

# ---------------------------------------------------------------------------
# Keystore de branch keys (hierarchical keyring)
#
# El AWS Database Encryption SDK exige una tabla dedicada con PK
# `branch-key-id` y SK `version`. El esquema lo fija la libreria, no nosotros.
# La creacion de branch keys se hace con la API del SDK (`keystore.CreateKey`),
# no con Terraform: aqui solo se aprovisiona la tabla.
# ---------------------------------------------------------------------------

resource "aws_dynamodb_table" "keystore" {
  count = var.create_keystore_table ? 1 : 0

  name         = "${local.name}-keystore"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "branch-key-id"
  range_key    = "version"

  deletion_protection_enabled = var.enable_deletion_protection

  attribute {
    name = "branch-key-id"
    type = "S"
  }

  attribute {
    name = "version"
    type = "S"
  }

  point_in_time_recovery {
    enabled = var.enable_point_in_time_recovery
  }

  server_side_encryption {
    enabled     = true
    kms_key_arn = var.kms_key_arn
  }

  tags = merge(var.tags, { "data-classification" = "restricted" })
}
