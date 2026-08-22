# ---------------------------------------------------------------------------
# Entorno stg.
#
# Perfil: espejo funcional de produccion con datos de prueba. PITR y proteccion
# de borrado activas para poder ensayar procedimientos de recuperacion, pero
# Object Lock sigue en GOVERNANCE y sin prevent_destroy: el entorno debe poder
# reconstruirse. Retencion de logs intermedia.
#
# Orden de aplicacion recomendado (ver README de infra/terraform):
#   1. kms  2. networking  3. data + storage  4. identity  5. compute
#   6. observability  7. orchestration  8. api  9. gdpr
# Terraform resuelve las dependencias solo; el orden importa cuando se aplica
# por objetivos (`-target`) tras un fallo parcial.
# ---------------------------------------------------------------------------

terraform {
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 6.10"
    }
  }
}

# ---------------------------------------------------------------------------
# Providers
#
# Las etiquetas obligatorias del proyecto se aplican una sola vez, aqui, con
# default_tags. Los modulos solo agregan las especificas del recurso
# (data-classification, tenant-id).
# ---------------------------------------------------------------------------

provider "aws" {
  region = var.aws_region

  default_tags {
    tags = {
      project               = "onboarding-generico"
      env                   = var.env
      owner                 = var.owner
      "data-classification" = "internal"
      "cost-center"         = var.cost_center
    }
  }
}

provider "google" {
  project = var.gcp_project_id
  region  = var.gcp_region

  default_labels = local.common_labels
}

provider "google-beta" {
  project = var.gcp_project_id
  region  = var.gcp_region

  default_labels = local.common_labels
}

data "aws_caller_identity" "current" {}

locals {
  deploy_aws = contains(["aws", "both"], var.cloud_provider)
  deploy_gcp = contains(["gcp", "both"], var.cloud_provider)

  # Las etiquetas de GCP solo admiten minusculas, digitos, guiones y guiones
  # bajos: por eso `data-classification` usa guion bajo aqui.
  common_labels = {
    project             = "onboarding-generico"
    env                 = var.env
    owner               = var.owner
    data_classification = "internal"
    cost_center         = var.cost_center
  }

  # ARN construido a mano para romper la dependencia circular entre
  # observability (que lo vigila) y orchestration (que publica en el bus).
  parent_state_machine_arn = "arn:aws:states:${var.aws_region}:${data.aws_caller_identity.current.account_id}:stateMachine:og-${var.env}-onboarding-saga"

  # Misma tecnica para el rol tenant-scoped: kms le concede un grant por tenant,
  # identity depende de data y storage, y data depende de kms. Construir el ARN
  # a partir del nombre conocido rompe ese ciclo.
  tenant_scoped_role_arn = "arn:aws:iam::${data.aws_caller_identity.current.account_id}:role/og-${var.env}-tenant-scoped"

  # Nombres de bucket construidos a mano por la misma razon: identity necesita
  # los nombres y storage necesita la cuenta de servicio de identity.
  gcp_bucket_names = [
    "og-${var.env}-documents-${var.gcp_project_id}",
    "og-${var.env}-biometrics-${var.gcp_project_id}",
    "og-${var.env}-staging-${var.gcp_project_id}",
  ]
}

# ===========================================================================
# AWS
# ===========================================================================

module "aws_kms" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/kms"

  env                        = var.env
  tenants                    = var.tenants
  deletion_window_in_days    = 14 # ventana intermedia para ensayar el crypto-shredding
  key_administrator_arns     = var.key_administrator_arns
  tenant_grant_principal_arn = local.tenant_scoped_role_arn
}

module "aws_networking" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/networking"

  env             = var.env
  aws_region      = var.aws_region
  private_subnets = var.aws_private_subnets

  # Espejo de produccion: se validan aqui los endpoints antes de prd.
  enable_interface_endpoints = true
  enable_nat_gateway         = false
}

module "aws_data" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/data"

  env         = var.env
  kms_key_arn = module.aws_kms[0].platform_key_arn

  enable_point_in_time_recovery = true
  enable_deletion_protection    = true
  # Sin prevent_destroy: stg debe poder reconstruirse desde cero.
  protect_from_destroy = false
}

module "aws_storage" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/storage"

  env         = var.env
  kms_key_arn = module.aws_kms[0].platform_key_arn

  document_retention_days  = 180
  biometric_retention_days = 90
  staging_retention_days   = 7

  # GOVERNANCE tambien en stg: con COMPLIANCE el entorno seria indestructible y
  # se perderia la capacidad de reconstruirlo.
  evidence_object_lock_mode = "GOVERNANCE"
  evidence_retention_years  = 2

  allow_force_destroy = false
}

module "aws_identity" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/identity"

  env        = var.env
  aws_region = var.aws_region

  pre_token_generation_lambda_arn = try(module.aws_compute[0].function_arns["pre-token-generation"], null)

  tenant_table_arns  = [module.aws_data[0].core_table_arn]
  tenant_bucket_arns = module.aws_storage[0].tenant_scoped_bucket_arns

  mfa_configuration          = "ON"
  advanced_security_mode     = "AUDIT"
  enable_deletion_protection = true
}

module "aws_compute" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/compute"

  env = var.env
  # Punto de partida para el perfilado. El valor definitivo sale de medir la
  # funcion real con su modelo real, no de esta cifra.
  inference_memory_mb = 4096
  log_retention_days  = 30
  log_level           = "INFO"

  zip_functions         = var.aws_zip_functions
  container_functions   = var.aws_container_functions
  artifacts_bucket_name = var.aws_artifacts_bucket_name

  core_table_name         = module.aws_data[0].core_table_name
  capabilities_table_name = module.aws_data[0].capabilities_table_name
  capabilities_table_arn  = module.aws_data[0].capabilities_table_arn
  locks_table_name        = module.aws_data[0].locks_table_name
  locks_table_arn         = module.aws_data[0].locks_table_arn
  keystore_table_name     = module.aws_data[0].keystore_table_name
  keystore_table_arn      = module.aws_data[0].keystore_table_arn

  documents_bucket_name  = module.aws_storage[0].documents_bucket_name
  biometrics_bucket_name = module.aws_storage[0].biometrics_bucket_name
  staging_bucket_name    = module.aws_storage[0].staging_bucket_name
  staging_bucket_arn     = module.aws_storage[0].staging_bucket_arn
  evidence_bucket_name   = module.aws_storage[0].evidence_bucket_name
  evidence_bucket_arn    = module.aws_storage[0].evidence_bucket_arn

  platform_kms_key_arn = module.aws_kms[0].platform_key_arn
}

module "aws_observability" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/observability"

  env                      = var.env
  parent_state_machine_arn = local.parent_state_machine_arn
  core_table_name          = module.aws_data[0].core_table_name
  api_name                 = "og-${var.env}-api"
  api_stage_name           = "v1"

  monitored_function_names     = module.aws_compute[0].function_names
  log_retention_days           = 90
  event_archive_retention_days = 90
  alarm_email_subscriptions    = var.alarm_email_subscriptions
}

module "aws_orchestration" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/orchestration"

  env = var.env

  plan_resolver_function_arn         = module.aws_compute[0].function_arns["plan-resolver"]
  preprocess_function_arn            = module.aws_compute[0].function_arns["preprocess"]
  ocr_function_arn                   = module.aws_compute[0].function_arns["ocr"]
  field_extraction_function_arn      = module.aws_compute[0].function_arns["field-extraction"]
  face_match_function_arn            = module.aws_compute[0].function_arns["face-match"]
  liveness_function_arn              = module.aws_compute[0].function_arns["liveness"]
  risk_scoring_function_arn          = module.aws_compute[0].function_arns["risk-scoring"]
  human_review_dispatch_function_arn = module.aws_compute[0].function_arns["human-review-dispatch"]
  decision_recorder_function_arn     = module.aws_compute[0].function_arns["decision-recorder"]

  invokable_function_arns = values(module.aws_compute[0].function_arns)
  event_bus_arn           = module.aws_observability[0].event_bus_arn
  event_bus_name          = module.aws_observability[0].event_bus_name

  human_review_timeout_seconds = 259200 # 3 dias
  log_retention_days           = 90
  log_level                    = "ERROR"
  include_execution_data       = false
}

module "aws_api" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/api"

  env = var.env

  authorizer_function_arn = module.aws_compute[0].function_arns["authorizer"]
  api_function_arn        = module.aws_compute[0].function_arns["api"]
  api_function_invoke_arn = module.aws_compute[0].function_invoke_arns["api"]

  start_execution_role_arn         = module.aws_orchestration[0].apigw_start_execution_role_arn
  start_execution_request_template = module.aws_orchestration[0].start_execution_request_template

  tenant_usage_plans           = var.aws_tenant_usage_plans
  authorizer_cache_ttl_seconds = 300
  enable_waf                   = true
  log_retention_days           = 90
}

module "aws_gdpr" {
  count  = local.deploy_aws ? 1 : 0
  source = "../../modules/aws/gdpr"

  env                   = var.env
  core_table_arn        = module.aws_data[0].core_table_arn
  core_table_stream_arn = module.aws_data[0].core_table_stream_arn

  purge_function_arn       = module.aws_compute[0].function_arns["gdpr-purge"]
  purge_function_name      = module.aws_compute[0].function_names["gdpr-purge"]
  purge_function_role_name = module.aws_compute[0].execution_role_name

  erasable_bucket_arns = module.aws_storage[0].tenant_scoped_bucket_arns
  evidence_bucket_arn  = module.aws_storage[0].evidence_bucket_arn
  tenant_kms_key_arns  = values(module.aws_kms[0].tenant_key_arns)

  event_bus_arn    = module.aws_observability[0].event_bus_arn
  alarms_topic_arn = module.aws_observability[0].alarms_topic_arn
  kms_key_arn      = module.aws_kms[0].platform_key_arn

  enable_retention_sweep = true
}

# ===========================================================================
# GCP
# ===========================================================================

module "gcp_kms" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/kms"

  project_id = var.gcp_project_id
  env        = var.env
  location   = var.gcp_region
  tenants    = { for k, v in var.tenants : k => { tier = v.tier } }

  runtime_service_account_email = module.gcp_identity[0].runtime_service_account_email
  tenant_service_account_emails = module.gcp_identity[0].tenant_service_account_emails

  destroy_scheduled_duration = "1209600s" # 14 dias
  labels                     = local.common_labels
}

module "gcp_identity" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/identity"

  project_id = var.gcp_project_id
  env        = var.env
  tenants    = { for k, v in var.tenants : k => { tier = v.tier } }

  tenant_scoped_bucket_names = local.gcp_bucket_names
  oidc_issuer_uri            = var.gcp_oidc_issuer_uri
  oidc_audience              = var.gcp_oidc_audience
}

module "gcp_networking" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/networking"

  project_id = var.gcp_project_id
  env        = var.env
  region     = var.gcp_region

  compute_subnet_cidr      = var.gcp_compute_subnet_cidr
  enable_psc_google_apis   = true
  compute_service_accounts = [module.gcp_identity[0].runtime_service_account_email]
}

module "gcp_data" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/data"

  project_id  = var.gcp_project_id
  env         = var.env
  location_id = var.gcp_firestore_location

  shared_database_name = "og-${var.env}-shared"

  tenants                       = { for k, v in var.tenants : k => { tier = v.tier } }
  tenant_service_account_emails = module.gcp_identity[0].tenant_service_account_emails
  cmek_key_name                 = module.gcp_kms[0].platform_key_id

  enable_point_in_time_recovery = true
  enable_delete_protection      = true
}

module "gcp_storage" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/storage"

  project_id         = var.gcp_project_id
  env                = var.env
  location           = var.gcp_storage_location
  bucket_name_suffix = var.gcp_project_id
  cmek_key_name      = module.gcp_kms[0].platform_key_id

  document_retention_days  = 180
  biometric_retention_days = 90
  staging_retention_days   = 7

  evidence_retention_years = 2
  lock_evidence_retention  = false # irreversible: solo en prd
  allow_force_destroy      = false

  runtime_service_account_email = module.gcp_identity[0].runtime_service_account_email
  labels                        = local.common_labels
}

module "gcp_compute" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/compute"

  project_id = var.gcp_project_id
  env        = var.env
  region     = var.gcp_region

  runtime_service_account_email = module.gcp_identity[0].runtime_service_account_email
  services                      = var.gcp_services
  jobs                          = var.gcp_jobs
  image_names                   = var.gcp_image_names

  vpc_network_name = module.gcp_networking[0].network_name
  vpc_subnet_name  = module.gcp_networking[0].compute_subnet_name

  firestore_database_name = module.gcp_data[0].shared_database_name
  documents_bucket_name   = module.gcp_storage[0].documents_bucket_name
  biometrics_bucket_name  = module.gcp_storage[0].biometrics_bucket_name
  staging_bucket_name     = module.gcp_storage[0].staging_bucket_name
  evidence_bucket_name    = module.gcp_storage[0].evidence_bucket_name
  platform_kms_key_id     = module.gcp_kms[0].platform_key_id

  log_level                  = "INFO"
  enable_deletion_protection = true
  labels                     = local.common_labels
}

module "gcp_orchestration" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/orchestration"

  project_id = var.gcp_project_id
  env        = var.env
  region     = var.gcp_region

  workflow_service_account_email = module.gcp_identity[0].runtime_service_account_email
  composer_service_url           = module.gcp_compute[0].service_urls["composer"]
  composer_service_name          = module.gcp_compute[0].service_names["composer"]
  extraction_service_url         = module.gcp_compute[0].service_urls["extraction"]
  biometrics_service_url         = module.gcp_compute[0].service_urls["biometrics"]
  review_service_url             = module.gcp_compute[0].service_urls["review"]

  firestore_database_name = module.gcp_data[0].shared_database_name
  cmek_key_name           = module.gcp_kms[0].platform_key_id

  call_log_level       = "LOG_ERRORS_ONLY"
  event_retention_days = 7
  labels               = local.common_labels
}

module "gcp_api" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/api"

  project_id = var.gcp_project_id
  env        = var.env
  region     = var.gcp_region

  composer_service_url          = module.gcp_compute[0].service_urls["composer"]
  gateway_service_account_email = module.gcp_identity[0].runtime_service_account_email

  jwt_issuer   = var.gcp_oidc_issuer_uri
  jwt_jwks_uri = var.gcp_jwks_uri
  jwt_audience = var.gcp_oidc_audience

  labels = local.common_labels
}

module "gcp_observability" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/observability"

  project_id = var.gcp_project_id
  env        = var.env

  audit_log_retention_days = 90
  # Los audit configs los declara gcp/identity: dejar solo uno evita conflictos
  # de propiedad del recurso.
  enable_audit_config  = false
  alert_email_channels = var.alarm_email_subscriptions
}

module "gcp_gdpr" {
  count  = local.deploy_gcp ? 1 : 0
  source = "../../modules/gcp/gdpr"

  project_id = var.gcp_project_id
  env        = var.env
  region     = var.gcp_region

  purge_image                     = "${module.gcp_compute[0].artifact_registry_host}/gdpr-purge:v1"
  purge_service_account_email     = module.gcp_identity[0].runtime_service_account_email
  scheduler_service_account_email = module.gcp_identity[0].runtime_service_account_email
  dispatcher_service_name         = module.gcp_compute[0].service_names["composer"]

  firestore_database_name = module.gcp_data[0].shared_database_name
  erasable_bucket_names   = module.gcp_storage[0].tenant_scoped_bucket_names
  evidence_bucket_name    = module.gcp_storage[0].evidence_bucket_name
  tenant_key_ids          = values(module.gcp_kms[0].tenant_key_ids)

  dead_letter_topic_id     = module.gcp_orchestration[0].domain_events_dlq_topic_id
  notification_channel_ids = values(module.gcp_observability[0].notification_channel_ids)

  enable_retention_sweep = true
  labels                 = local.common_labels
}
