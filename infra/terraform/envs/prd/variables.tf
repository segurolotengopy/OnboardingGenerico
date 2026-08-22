# ---------------------------------------------------------------------------
# Variables del entorno.
#
# Ningun valor real ni secreto vive en este archivo ni en el repositorio. Los
# valores concretos se pasan por terraform.tfvars (no versionado) o por
# variables de entorno TF_VAR_*.
# ---------------------------------------------------------------------------

variable "cloud_provider" {
  description = "Nube o nubes a desplegar: aws (implementacion de referencia), gcp (alternativa) o both. Controla que arbol de modulos se activa. En produccion no tiene valor por defecto: debe declararse de forma explicita."
  type        = string

  validation {
    condition     = contains(["aws", "gcp", "both"], var.cloud_provider)
    error_message = "cloud_provider debe ser aws, gcp o both."
  }
}

variable "env" {
  description = "Identificador del entorno. Forma parte del prefijo de nombres og-{env}-* de todos los recursos."
  type        = string
  default     = "prd"
}

variable "owner" {
  description = "Equipo responsable del entorno. Etiqueta obligatoria del proyecto."
  type        = string
}

variable "cost_center" {
  description = "Centro de coste al que se imputa el entorno. Etiqueta obligatoria del proyecto."
  type        = string
}

variable "tenants" {
  description = "Mapa de tenant_id a sus atributos. Es la fuente de verdad del aprovisionamiento por tenant: llaves KMS, planes de uso, bases de datos dedicadas."
  type        = map(object({
    tier         = optional(string, "standard")
    jurisdiction = optional(string, "")
  }))
  default = {}
}

variable "alarm_email_subscriptions" {
  description = "Mapa de nombre a direccion de correo que recibe las alarmas. Las suscripciones de SNS requieren confirmacion manual del destinatario."
  type        = map(string)
  default     = {}
}

# ---------------------------------------------------------------------------
# AWS
# ---------------------------------------------------------------------------

variable "aws_region" {
  description = "Region de AWS del entorno."
  type        = string
  default     = "us-east-1"
}

variable "aws_private_subnets" {
  description = "Mapa de zona de disponibilidad a bloque CIDR de subred privada."
  type        = map(string)
  default     = {
    "us-east-1a" = "10.60.1.0/24"
    "us-east-1b" = "10.60.2.0/24"
  }
}

variable "key_administrator_arns" {
  description = "ARNs de los principals autorizados a administrar las llaves KMS. En produccion es obligatorio: dejar la administracion en el root de la cuenta no es aceptable."
  type        = list(string)

  validation {
    condition     = length(var.key_administrator_arns) > 0
    error_message = "En produccion debe declararse al menos un administrador de llaves distinto del root de la cuenta."
  }
}

variable "aws_artifacts_bucket_name" {
  description = "Bucket con los artefactos zip de las funciones y de la capa compartida. Lo aprovisiona el pipeline de integracion continua, fuera de este arbol."
  type        = string
  default     = ""
}

variable "aws_zip_functions" {
  description = "Definicion de las funciones Lambda empaquetadas como zip. La clave del mapa se concatena al prefijo og-{env}-."
  type        = map(object({
    description             = string
    handler                 = string
    s3_key                  = string
    memory_mb               = optional(number, 512)
    timeout_seconds         = optional(number, 30)
    reserved_concurrency    = optional(number, -1)
    provisioned_concurrency = optional(number, 0)
    in_vpc                  = optional(bool, false)
    environment             = optional(map(string), {})
  }))
  default = {}
}

variable "aws_container_functions" {
  description = "Definicion de las funciones Lambda empaquetadas como imagen de contenedor. Se crea un repositorio de ECR por entrada."
  type        = map(object({
    description             = string
    image_tag               = optional(string, "v1")
    architecture            = optional(string, "x86_64")
    memory_mb               = optional(number, null)
    timeout_seconds         = optional(number, 300)
    ephemeral_storage_mb    = optional(number, 2048)
    reserved_concurrency    = optional(number, -1)
    provisioned_concurrency = optional(number, 0)
    in_vpc                  = optional(bool, false)
    environment             = optional(map(string), {})
  }))
  default = {}
}

variable "aws_tenant_usage_plans" {
  description = "Planes de uso de API Gateway por tenant, con cuota y throttling diferenciados por tier."
  type        = map(object({
    tier         = optional(string, "standard")
    rate_limit   = optional(number, 20)
    burst_limit  = optional(number, 40)
    quota_limit  = optional(number, null)
    quota_period = optional(string, "DAY")
  }))
  default = {}
}

# ---------------------------------------------------------------------------
# GCP
# ---------------------------------------------------------------------------

variable "gcp_project_id" {
  description = "Identificador del proyecto de Google Cloud. Solo se usa cuando cloud_provider incluye gcp."
  type        = string
  default     = ""
}

variable "gcp_region" {
  description = "Region de Google Cloud del entorno."
  type        = string
  default     = "us-central1"
}

variable "gcp_firestore_location" {
  description = "Ubicacion de las bases de datos de Firestore. Es inmutable una vez creada la base de datos."
  type        = string
  default     = "nam5"
}

variable "gcp_storage_location" {
  description = "Ubicacion de los buckets de Cloud Storage. Fijela de forma explicita si hay requisitos de residencia de datos."
  type        = string
  default     = "US"
}

variable "gcp_compute_subnet_cidr" {
  description = "Rango CIDR de la subred del computo. Debe ser /26 o mayor para Direct VPC egress."
  type        = string
  default     = "10.70.0.0/24"
}

variable "gcp_oidc_issuer_uri" {
  description = "URI del emisor OIDC que emite los tokens de los sistemas requirentes."
  type        = string
  default     = ""
}

variable "gcp_oidc_audience" {
  description = "Audiencia esperada en el token emitido por el proveedor OIDC."
  type        = string
  default     = "onboarding-generico"
}

variable "gcp_jwks_uri" {
  description = "URI del conjunto de claves publicas del emisor, usado por API Gateway para verificar la firma del token."
  type        = string
  default     = ""
}

variable "gcp_services" {
  description = "Definicion de los servicios de Cloud Run. Recuerde la relacion obligatoria entre CPU y memoria y que la concurrencia alta rompe los supuestos de una sesion de ONNX."
  type        = map(object({
    description           = string
    image_name            = string
    image_tag             = optional(string, "v1")
    cpu                   = optional(string, "1")
    memory                = optional(string, "2Gi")
    concurrency           = optional(number, 80)
    min_instances         = optional(number, 0)
    max_instances         = optional(number, 20)
    timeout_seconds       = optional(number, 300)
    startup_cpu_boost     = optional(bool, true)
    always_allocated_cpu  = optional(bool, false)
    ingress               = optional(string, "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER")
    use_direct_vpc_egress = optional(bool, false)
    vpc_egress            = optional(string, "PRIVATE_RANGES_ONLY")
    gpu_type              = optional(string, null)
    data_classification   = optional(string, "internal")
    invoker_members       = optional(list(string), [])
    environment           = optional(map(string), {})
    secret_environment    = optional(map(object({
      secret  = string
      version = string
    })), {})
  }))
  default = {}
}

variable "gcp_jobs" {
  description = "Definicion de los jobs de Cloud Run para trabajo por lotes."
  type        = map(object({
    image_name            = string
    image_tag             = optional(string, "v1")
    cpu                   = optional(string, "1")
    memory                = optional(string, "2Gi")
    task_count            = optional(number, 1)
    parallelism           = optional(number, 1)
    timeout_seconds       = optional(number, 3600)
    max_retries           = optional(number, 3)
    use_direct_vpc_egress = optional(bool, false)
    environment           = optional(map(string), {})
  }))
  default = {}
}

variable "gcp_image_names" {
  description = "Nombres de las imagenes gestionadas en Artifact Registry, usados por la politica de limpieza."
  type        = list(string)
  default     = []
}

# ---------------------------------------------------------------------------
# Variables exclusivas de produccion
#
# En prd, los valores con consecuencias irreversibles o regulatorias no llevan
# un valor por defecto comodo: se declaran de forma explicita para que la
# decision quede registrada en el control de versiones.
# ---------------------------------------------------------------------------

variable "enable_internet_egress" {
  description = "Crea NAT Gateway para permitir salida a Internet desde las subredes privadas. Manteniendolo en false, el egreso a Internet es imposible por construccion; actívelo solo si algun adaptador llama a un proveedor SaaS externo."
  type        = bool
  default     = false
}

variable "document_retention_days" {
  description = "Dias de retencion de las imagenes de documentos de identidad. Debe derivarse de la obligacion KYC/AML de la jurisdiccion mas exigente entre los tenants del entorno, no de una cifra generica."
  type        = number
}

variable "biometric_retention_days" {
  description = "Dias de retencion de selfies, frames de vivacidad y embeddings. Suele ser menor que la del documento porque en varias jurisdicciones la biometria es dato de categoria especial."
  type        = number
}

variable "evidence_retention_years" {
  description = "Anios de retencion de la evidencia de auditoria. IRREVERSIBLE en produccion: el modo COMPLIANCE de S3 y el bloqueo de la politica de Cloud Storage impiden acortarla despues."
  type        = number

  validation {
    condition     = var.evidence_retention_years >= 5
    error_message = "La retencion de evidencia en produccion no puede ser inferior a 5 anios."
  }
}

variable "inference_memory_mb" {
  description = "Memoria de las funciones de inferencia, en MB. Debe fijarse a partir del perfilado de la funcion real con su modelo real: el rango admitido por Lambda es de 128 a 10240 MB y la vCPU asignada es proporcional a la memoria."
  type        = number
  default     = 4096

  validation {
    condition     = var.inference_memory_mb >= 128 && var.inference_memory_mb <= 10240
    error_message = "inference_memory_mb debe estar entre 128 y 10240."
  }
}

variable "platform_role_trusted_principals" {
  description = "Principals autorizados a asumir el rol de plataforma, que opera sin scoping de tenant. Su uso debe ser minimo y auditado. Lista vacia significa que el rol no se crea."
  type        = list(string)
  default     = []
}
