# ---------------------------------------------------------------------------
# Cloud KMS: keyring, llave de plataforma y una llave por tenant.
#
# ESTA ES LA PIEZA MAS IMPORTANTE DEL AISLAMIENTO MULTI-TENANT EN GCP.
#
# Como GCP no puede aplicar aislamiento en el plano de datos (no existe
# `dynamodb:LeadingKeys`), el cifrado de sobre por tenant deja de ser defensa en
# profundidad opcional y se convierte en el CONTROL PRIMARIO:
#
#   - Se cifra con una DEK envuelta por la llave (KEK) del tenant.
#   - `tenant_id` viaja como Associated Data (AAD) junto con `record_id`.
#   - Un error de alcance produce un FALLO DE DESCIFRADO, no una fuga de datos.
#
# En GCP la biblioteca es Tink (KmsEnvelopeAead). NO existe equivalente al AWS
# Database Encryption SDK: Tink no aporta firma del registro completo, ni
# atributos firmados-pero-no-cifrados, ni beacons de busqueda sobre campos
# cifrados. Si el diseno de AWS usa beacons, ese patron NO se porta y hay que
# reimplementarlo con un indice HMAC determinista por tenant, asumiendo el
# analisis de fuga de frecuencia.
#
# CACHE OBLIGATORIA: Tink no trae cache de material criptografico. Sin una cache
# del objeto Aead por tenant, la latencia de la llamada a KMS por operacion hace
# el sistema inviable. No es una optimizacion, es un requisito.
#
# CRYPTO-SHREDDING: Cloud KMS no permite destruccion inmediata. Una version se
# PROGRAMA para destruccion y permanece en ese estado durante
# `destroy_scheduled_duration`, con valor por defecto de 30 dias. Durante la
# ventana puede restaurarse.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"
}

resource "google_kms_key_ring" "this" {
  name     = "${local.name}-keyring"
  project  = var.project_id
  location = var.location
}

# ---------------------------------------------------------------------------
# Llave de plataforma (CMEK de servicios gestionados)
# ---------------------------------------------------------------------------

resource "google_kms_crypto_key" "platform" {
  name     = "${local.name}-platform"
  key_ring = google_kms_key_ring.this.id
  purpose  = "ENCRYPT_DECRYPT"

  rotation_period = var.rotation_period

  # Ventana antes de la destruccion efectiva de una version.
  # PENDIENTE DE VERIFICAR: el valor minimo configurable no aparece documentado
  # en la pagina de destruccion y restauracion de Cloud KMS. Se cita
  # habitualmente 24 h, pero no esta confirmado. Verifiquelo antes de
  # comprometer cualquier SLA de borrado.
  destroy_scheduled_duration = var.destroy_scheduled_duration

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = var.protection_level
  }

  labels = merge(var.labels, { "data-classification" = "restricted" })

  lifecycle {
    # Una llave de KMS no se destruye realmente al eliminarla de Terraform: solo
    # se elimina del estado, y el keyring y la llave quedan en el proyecto para
    # siempre (Cloud KMS no permite borrar keyrings ni llaves). Es intencional.
    prevent_destroy = true
  }
}

# CMEK para servicios gestionados: cada servicio usa su propio agente de
# servicio, que necesita el rol de cifrador/descifrador sobre la llave.
resource "google_kms_crypto_key_iam_member" "platform_service_agents" {
  for_each = toset(var.platform_key_service_agents)

  crypto_key_id = google_kms_crypto_key.platform.id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = each.value
}

# ---------------------------------------------------------------------------
# Llave por tenant
#
# `for_each` sobre el mapa de tenants: agregar un tenant crea su llave sin tocar
# las de los demas.
#
# COSTE: en Cloud KMS se paga por version activa de llave y por operacion
# criptografica. Con miles de tenants, una llave por tenant deja de ser
# despreciable. Reserve el patron para tenants regulados y use derivacion de
# claves con una llave compartida para el resto.
# ---------------------------------------------------------------------------

resource "google_kms_crypto_key" "tenant" {
  for_each = var.tenants

  name     = "${local.name}-tenant-${each.key}"
  key_ring = google_kms_key_ring.this.id
  purpose  = "ENCRYPT_DECRYPT"

  rotation_period            = var.rotation_period
  destroy_scheduled_duration = var.destroy_scheduled_duration

  version_template {
    algorithm        = "GOOGLE_SYMMETRIC_ENCRYPTION"
    protection_level = try(each.value.protection_level, var.protection_level)
  }

  labels = merge(
    var.labels,
    {
      "data-classification" = "restricted"
      "tenant-id"           = each.key
      "tenant-tier"         = try(each.value.tier, "standard")
    },
  )

  lifecycle {
    prevent_destroy = true
  }
}

# ---------------------------------------------------------------------------
# IAM por tenant
#
# La cuenta de servicio dedicada de cada tenant premium solo puede usar SU
# llave. Este binding es de recurso, asi que si lo aplica la plataforma de
# verdad: es una de las pocas fronteras reales que ofrece GCP en este diseno.
# ---------------------------------------------------------------------------

resource "google_kms_crypto_key_iam_member" "tenant_dedicated" {
  for_each = {
    for k, v in var.tenants : k => v
    if try(var.tenant_service_account_emails[k], null) != null
  }

  crypto_key_id = google_kms_crypto_key.tenant[each.key].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${var.tenant_service_account_emails[each.key]}"
}

# El runtime compartido puede usar todas las llaves de tenant. Aqui la
# plataforma NO aplica ninguna frontera: la separacion la garantiza el AAD del
# cifrado de sobre, que hace fallar el descifrado si el tenant no coincide.
resource "google_kms_crypto_key_iam_member" "runtime_shared" {
  for_each = var.runtime_service_account_email == null ? {} : var.tenants

  crypto_key_id = google_kms_crypto_key.tenant[each.key].id
  role          = "roles/cloudkms.cryptoKeyEncrypterDecrypter"
  member        = "serviceAccount:${var.runtime_service_account_email}"
}

# Solo una identidad de operacion, distinta de la del runtime, puede programar
# la destruccion de una llave. El crypto-shredding no debe estar al alcance del
# camino de ejecucion normal.
resource "google_kms_crypto_key_iam_member" "shredding_operator" {
  for_each = var.shredding_operator_member == null ? {} : var.tenants

  crypto_key_id = google_kms_crypto_key.tenant[each.key].id
  role          = "roles/cloudkms.admin"
  member        = var.shredding_operator_member
}

# ---------------------------------------------------------------------------
# Autokey
#
# Automatiza el aprovisionamiento de CMEK al crear recursos compatibles. Soporta
# unos 27 servicios, incluidos Cloud Storage, Cloud Run, Pub/Sub, Secret Manager
# y Artifact Registry.
#
# ADVERTENCIA: Firestore NO esta en la lista. Su CMEK se declara de forma
# explicita en el modulo gcp/data.
#
# Requiere una carpeta (folder) y ubicaciones con Cloud HSM disponible.
# ---------------------------------------------------------------------------

resource "google_kms_autokey_config" "this" {
  count = var.enable_autokey ? 1 : 0

  folder      = var.autokey_folder_id
  key_project = "projects/${var.project_id}"
}
