# ---------------------------------------------------------------------------
# Identidad y aislamiento multi-tenant en GCP.
#
# BRECHA CENTRAL, DECLARADA SIN RODEOS
# ------------------------------------
# GCP NO tiene equivalente a `dynamodb:LeadingKeys`. Las condiciones de IAM
# exponen `resource.type`, `resource.name`, `resource.service`,
# `resource.matchTag()`, `request.time`, `principal.type` y `principal.subject`,
# y ninguna permite condicionar sobre el prefijo de una clave de fila o el
# identificador de un documento. Firestore no acepta condiciones a nivel de
# documento en sus bindings de rol.
#
# Y las Security Rules de Firestore NO sirven: las bibliotecas de cliente de
# servidor las omiten por completo y se autentican con credenciales por defecto
# de la aplicacion. Solo protegen SDK de cliente movil o web.
#
# Consecuencia: en GCP, si el codigo tiene la cuenta de servicio de Firestore,
# puede leer todos los tenants. La barrera es el codigo, no la plataforma.
#
# COMPENSACION EN CUATRO CAPAS
# ----------------------------
#   1. CRIPTOGRAFICA (control primario): cifrado de sobre por tenant con
#      `tenant_id` como Associated Data. Un error de alcance produce un FALLO DE
#      DESCIFRADO, no una fuga. Ver modulo gcp/kms.
#   2. DE PLATAFORMA para tenants premium: base de datos Firestore dedicada por
#      tenant, con IAM sobre el recurso `database`. Ver modulo gcp/data.
#   3. DE PERIMETRO: VPC Service Controls. Requiere permisos de Organizacion;
#      el recurso queda comentado mas abajo con instrucciones.
#   4. DE DETECCION: Data Access audit logs sobre Firestore, GCS y KMS, con
#      alerta cuando el tenant del path no coincide con el del token.
#
# Y en el codigo: un unico repositorio con alcance de tenant por el que pasa
# toda consulta, reforzado con pruebas de arquitectura que fallen si el cliente
# de Firestore se importa fuera del adaptador.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"
}

# ---------------------------------------------------------------------------
# Identity Platform
# ---------------------------------------------------------------------------

resource "google_identity_platform_config" "this" {
  project = var.project_id

  # Habilita la multi-tenancy nativa. ADVERTENCIA DE CUOTA: sin instrumento de
  # facturacion asociado al proyecto, el limite es de 2 tenants; con el, es
  # ilimitado.
  multi_tenant {
    allow_tenants = true
  }

  dynamic "quota" {
    for_each = var.signup_quota_per_hour == null ? [] : [1]
    content {
      sign_up_quota_config {
        quota          = var.signup_quota_per_hour
        start_time     = var.signup_quota_start_time
        quota_duration = "7200s"
      }
    }
  }
}

resource "google_identity_platform_tenant" "this" {
  for_each = var.tenants

  project      = var.project_id
  display_name = substr("${local.name}-${each.key}", 0, 20)

  allow_password_signup    = try(each.value.allow_password_signup, false)
  enable_email_link_signin = false

  depends_on = [google_identity_platform_config.this]
}

# ---------------------------------------------------------------------------
# Cuentas de servicio
# ---------------------------------------------------------------------------

# Cuenta del runtime. Deliberadamente pobre en permisos: los concede el modulo
# que posee cada recurso, no este.
resource "google_service_account" "runtime" {
  project      = var.project_id
  account_id   = "${local.name}-runtime"
  display_name = "Runtime del middleware de onboarding (${var.env})"
  description  = "Identidad del computo. No debe recibir roles de proyecto amplios: el alcance de tenant lo aplica el codigo, no IAM."
}

# Cuenta por tenant premium. Habilita el patron de base de datos Firestore
# dedicada con IAM real sobre el recurso, que es lo mas cercano a un aislamiento
# de plano de datos que ofrece GCP.
resource "google_service_account" "tenant" {
  for_each = { for k, v in var.tenants : k => v if try(v.tier, "standard") == "premium" }

  project      = var.project_id
  account_id   = substr("${local.name}-t-${each.key}", 0, 30)
  display_name = "Identidad dedicada del tenant ${each.key}"
  description  = "Cuenta de servicio del tenant ${each.key}. Solo tiene acceso a su base de datos Firestore y a su llave de cifrado."
}

# ---------------------------------------------------------------------------
# Workload Identity Federation
#
# Es el analogo mas cercano a los session tags de STS: mapea claims del token
# externo a atributos, y permite conceder roles a
# principalSet://.../attribute.tenant/<valor>.
#
# LIMITACION: gobierna a que RECURSOS de GCP puede acceder la identidad, no que
# FILAS puede leer dentro de una base de datos. No sustituye a LeadingKeys.
# ---------------------------------------------------------------------------

resource "google_iam_workload_identity_pool" "this" {
  count = var.enable_workload_identity_federation ? 1 : 0

  project                   = var.project_id
  workload_identity_pool_id = "${local.name}-wif"
  display_name              = "Federacion de identidades (${var.env})"
  description               = "Pool de federacion para identidades de tenant emitidas por el proveedor OIDC externo."
}

resource "google_iam_workload_identity_pool_provider" "oidc" {
  count = var.enable_workload_identity_federation ? 1 : 0

  project                            = var.project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.this[0].workload_identity_pool_id
  workload_identity_pool_provider_id = "${local.name}-oidc"
  display_name                       = "Proveedor OIDC de tenants"

  attribute_mapping = {
    "google.subject"    = "assertion.sub"
    "attribute.tenant"  = "assertion.tenant_id"
    "attribute.tier"    = "assertion.tenant_tier"
    "attribute.aud"     = "assertion.aud"
  }

  # La condicion de atributo es un filtro de admision: un token sin tenant_id
  # nunca llega a intercambiarse por credenciales. Es el equivalente al
  # "fallo cerrado" del trigger de Cognito.
  attribute_condition = join(" && ", [
    "assertion.tenant_id != null",
    "assertion.tenant_id != ''",
    format("assertion.aud == '%s'", var.oidc_audience),
  ])

  oidc {
    issuer_uri        = var.oidc_issuer_uri
    allowed_audiences = [var.oidc_audience]
  }
}

# Vinculacion de cada tenant premium a su propia cuenta de servicio.
resource "google_service_account_iam_member" "tenant_wif" {
  for_each = var.enable_workload_identity_federation ? google_service_account.tenant : {}

  service_account_id = each.value.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.this[0].name}/attribute.tenant/${each.key}"
}

# ---------------------------------------------------------------------------
# Condiciones de IAM: donde SI funcionan
#
# `resource.name.startsWith(...)` funciona bien sobre Cloud Storage (prefijos de
# objeto) y sobre Secret Manager. Es el unico punto donde GCP se acerca al
# scoping por prefijo de S3.
# ---------------------------------------------------------------------------

resource "google_storage_bucket_iam_member" "tenant_prefix" {
  for_each = var.enable_workload_identity_federation ? {
    for pair in setproduct(keys(google_service_account.tenant), var.tenant_scoped_bucket_names) :
    "${pair[0]}|${pair[1]}" => { tenant = pair[0], bucket = pair[1] }
  } : {}

  bucket = each.value.bucket
  role   = "roles/storage.objectUser"
  member = "serviceAccount:${google_service_account.tenant[each.value.tenant].email}"

  condition {
    title       = "solo-prefijo-del-tenant"
    description = "Restringe el acceso a los objetos bajo el prefijo del tenant ${each.value.tenant}."
    expression  = "resource.name.startsWith('projects/_/buckets/${each.value.bucket}/objects/${each.value.tenant}/')"
  }
}

# ---------------------------------------------------------------------------
# Data Access audit logs
#
# CRITICO: estan DESHABILITADOS POR DEFECTO. Sin ellos no hay traza de quien
# leyo datos de que tenant, que en eKYC es un fallo de cumplimiento silencioso.
# Dado que GCP no puede PREVENIR el acceso cruzado entre tenants, la deteccion
# deja de ser opcional.
# ---------------------------------------------------------------------------

resource "google_project_iam_audit_config" "data_access" {
  for_each = toset(var.data_access_audited_services)

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
# VPC Service Controls
#
# PENDIENTE DE HABILITACION MANUAL: estos recursos requieren permisos a nivel de
# ORGANIZACION (roles/accesscontextmanager.policyAdmin) y una politica de acceso
# preexistente. No pueden crearse desde un despliegue con alcance de proyecto,
# por eso quedan comentados.
#
# Que aportan: un perimetro que impide la exfiltracion de datos fuera del
# conjunto de proyectos, aunque una credencial se filtre. Es la unica pieza de
# GCP sin equivalente en AWS y compensa PARCIALMENTE la ausencia de
# LeadingKeys, a granularidad de proyecto (no de fila).
#
# Para habilitarlo:
#   1. Obtenga el identificador de la politica de acceso de la organizacion:
#        gcloud access-context-manager policies list --organization=ORG_ID
#   2. Fije var.access_policy_name con ese valor.
#   3. Descomente el bloque y aplique con credenciales que tengan el rol de
#      administrador de politicas a nivel de organizacion.
#   4. Aplique primero en modo dry-run (`use_explicit_dry_run_spec = true`) y
#      revise las violaciones en los logs antes de hacerlo efectivo. Un
#      perimetro mal dimensionado corta el trafico legitimo de golpe.
#
# resource "google_access_context_manager_service_perimeter" "onboarding" {
#   parent = "accessPolicies/${var.access_policy_name}"
#   name   = "accessPolicies/${var.access_policy_name}/servicePerimeters/og_${var.env}"
#   title  = "Perimetro del middleware de onboarding (${var.env})"
#
#   status {
#     resources = ["projects/${var.project_number}"]
#
#     restricted_services = [
#       "firestore.googleapis.com",
#       "storage.googleapis.com",
#       "cloudkms.googleapis.com",
#       "documentai.googleapis.com",
#       "secretmanager.googleapis.com",
#       "run.googleapis.com",
#     ]
#
#     vpc_accessible_services {
#       enable_restriction = true
#       allowed_services   = ["RESTRICTED-SERVICES"]
#     }
#   }
# }
