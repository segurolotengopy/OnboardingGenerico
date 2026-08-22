# ---------------------------------------------------------------------------
# Capa de datos en Firestore (modo Native).
#
# POR QUE EL MODELO NO ES UN CALCO DEL DE DYNAMODB
# ------------------------------------------------
# El patron single-table de DynamoDB se apoya en tres cosas que Firestore no
# tiene: clave compuesta PK+SK con consultas de rango sobre la sort key, indices
# globales con proyeccion arbitraria, y `begins_with` sobre la sort key.
#
# El mapeo mas fiel es usar IDENTIFICADORES DE DOCUMENTO COMPUESTOS del estilo
# `TENANT#<t>#CASE#<c>` dentro de una coleccion plana, y hacer consultas de
# rango sobre `__name__`. Los identificadores se ordenan lexicograficamente, asi
# que eso reproduce `begins_with`.
#
# Si el modelo real fuera agresivamente single-table, el destino correcto seria
# Cloud Bigtable (row keys ordenadas, prefijos) o Cloud Spanner (el unico con
# change streams reales: orden garantizado y reproduccion de hasta 7 dias). Este
# modulo elige Firestore porque el volumen de un middleware de onboarding no lo
# justifica, pero la eleccion debe revisarse si el patron de acceso cambia.
#
# BASE DE DATOS POR TENANT
# ------------------------
# Firestore admite hasta 100 bases de datos por proyecto (ampliable). Ese es el
# unico aislamiento REAL de plano de datos disponible en GCP, y por eso los
# tenants premium reciben una base dedicada con IAM sobre el recurso `database`.
# No escala a miles de tenants; para el resto, el control primario es el cifrado
# por tenant con `tenant_id` como Associated Data.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"

  premium_tenants = { for k, v in var.tenants : k => v if try(v.tier, "standard") == "premium" }
}

# ---------------------------------------------------------------------------
# Base de datos compartida
# ---------------------------------------------------------------------------

resource "google_firestore_database" "shared" {
  project     = var.project_id
  name        = var.shared_database_name
  location_id = var.location_id
  type        = "FIRESTORE_NATIVE"

  concurrency_mode                  = "OPTIMISTIC"
  app_engine_integration_mode       = "DISABLED"
  point_in_time_recovery_enablement = var.enable_point_in_time_recovery ? "POINT_IN_TIME_RECOVERY_ENABLED" : "POINT_IN_TIME_RECOVERY_DISABLED"
  delete_protection_state           = var.enable_delete_protection ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED"

  # Cloud KMS Autokey NO soporta Firestore, asi que la CMEK se declara aqui de
  # forma explicita. Recuerde que CMEK es cifrado en reposo a nivel de servicio:
  # NO es lo mismo que el cifrado de campo por tenant, que sigue siendo trabajo
  # de la aplicacion.
  kms_key_name = var.cmek_key_name
}

# ---------------------------------------------------------------------------
# Bases de datos dedicadas por tenant premium
# ---------------------------------------------------------------------------

resource "google_firestore_database" "tenant" {
  for_each = local.premium_tenants

  project     = var.project_id
  name        = "${local.name}-t-${each.key}"
  location_id = var.location_id
  type        = "FIRESTORE_NATIVE"

  concurrency_mode                  = "OPTIMISTIC"
  app_engine_integration_mode       = "DISABLED"
  point_in_time_recovery_enablement = var.enable_point_in_time_recovery ? "POINT_IN_TIME_RECOVERY_ENABLED" : "POINT_IN_TIME_RECOVERY_DISABLED"
  delete_protection_state           = var.enable_delete_protection ? "DELETE_PROTECTION_ENABLED" : "DELETE_PROTECTION_DISABLED"

  kms_key_name = try(var.tenant_cmek_key_names[each.key], var.cmek_key_name)
}

# Aislamiento real de plano de datos: la cuenta de servicio del tenant solo
# tiene el rol sobre SU base de datos. Esto si lo aplica la plataforma.
resource "google_project_iam_member" "tenant_database_access" {
  for_each = {
    for k, v in local.premium_tenants : k => v
    if try(var.tenant_service_account_emails[k], null) != null
  }

  project = var.project_id
  role    = "roles/datastore.user"
  member  = "serviceAccount:${var.tenant_service_account_emails[each.key]}"

  # ADVERTENCIA: esta condicion acota el acceso al RECURSO base de datos, no a
  # documentos concretos dentro de ella. Es lo maximo que permite IAM en GCP.
  condition {
    title       = "solo-base-de-datos-del-tenant"
    description = "Limita el acceso a la base de datos dedicada del tenant ${each.key}."
    expression  = "resource.name.startsWith('projects/${var.project_id}/databases/${local.name}-t-${each.key}')"
  }
}

# ---------------------------------------------------------------------------
# Politica de TTL
#
# Un solo campo TTL por grupo de colecciones; maximo 1.000 configuraciones a
# nivel de campo por base de datos.
#
# ADVERTENCIA: el TTL NO borra subcolecciones. Si se modela
# /casos/{c}/documentos/{d}, expirar el caso deja las subcolecciones huerfanas.
# Por eso el modelo de este repositorio es de COLECCIONES PLANAS con
# identificadores compuestos, no jerarquico.
# ---------------------------------------------------------------------------

resource "google_firestore_field" "ephemeral_ttl" {
  project    = var.project_id
  database   = google_firestore_database.shared.name
  collection = var.ephemeral_collection
  field      = "expires_at"

  ttl_config {}

  # Los campos de trabajo efimeros no se consultan: desactivar su indexacion
  # ahorra entradas de indice y evita acercarse al limite de 40.000 por
  # documento.
  index_config {}
}

# ---------------------------------------------------------------------------
# Indices compuestos
# ---------------------------------------------------------------------------

# Casos por tenant y estado, ordenados por fecha de creacion.
resource "google_firestore_index" "cases_by_status" {
  project    = var.project_id
  database   = google_firestore_database.shared.name
  collection = var.cases_collection

  fields {
    field_path = "tenant_id"
    order      = "ASCENDING"
  }

  fields {
    field_path = "status"
    order      = "ASCENDING"
  }

  fields {
    field_path = "created_at"
    order      = "DESCENDING"
  }
}

# Cola de revision manual: por tenant, prioridad y antiguedad.
resource "google_firestore_index" "review_queue" {
  project    = var.project_id
  database   = google_firestore_database.shared.name
  collection = var.reviews_collection

  fields {
    field_path = "tenant_id"
    order      = "ASCENDING"
  }

  fields {
    field_path = "priority"
    order      = "DESCENDING"
  }

  fields {
    field_path = "queued_at"
    order      = "ASCENDING"
  }
}

# ---------------------------------------------------------------------------
# Registro de Capacidades
#
# Equivalente de la tabla de capacidades de DynamoDB. Coleccion plana con
# identificadores compuestos:
#
#   <capabilityId>#<countryCode>#<documentType>#v<n>
#
# Indice para la consulta inversa: dado un pais y un tipo de documento, que
# capacidades existen y en que version.
# ---------------------------------------------------------------------------

resource "google_firestore_index" "capabilities_by_country" {
  project    = var.project_id
  database   = google_firestore_database.shared.name
  collection = var.capabilities_collection

  fields {
    field_path = "country_code"
    order      = "ASCENDING"
  }

  fields {
    field_path = "document_type"
    order      = "ASCENDING"
  }

  fields {
    field_path = "enabled"
    order      = "ASCENDING"
  }

  fields {
    field_path = "version"
    order      = "DESCENDING"
  }
}

# ---------------------------------------------------------------------------
# Mutex distribuido
#
# Firestore no tiene escrituras condicionales al estilo de DynamoDB, pero si
# transacciones optimistas con precondiciones sobre el documento. El indice
# permite localizar rapidamente los bloqueos vencidos para el proceso de
# recuperacion.
# ---------------------------------------------------------------------------

resource "google_firestore_field" "lock_ttl" {
  project    = var.project_id
  database   = google_firestore_database.shared.name
  collection = var.locks_collection
  field      = "lock_expires_at"

  ttl_config {}
}
