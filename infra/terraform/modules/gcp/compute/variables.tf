variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "region" {
  description = "Region de los servicios, los jobs y el repositorio de imagenes."
  type        = string
}

variable "runtime_service_account_email" {
  description = "Cuenta de servicio con la que se ejecutan los servicios y los jobs."
  type        = string
}

variable "services" {
  description = "Mapa de nombre logico a definicion de servicio de Cloud Run. ADVERTENCIA: existe una relacion obligatoria entre CPU y memoria (1 vCPU admite hasta 4 GiB; 4 vCPU, de 2 a 16 GiB; 8 vCPU, de 4 a 32 GiB) y el sistema de archivos escribible es tmpfs que consume memoria."
  type = map(object({
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
    secret_environment = optional(map(object({
      secret  = string
      version = string
    })), {})
  }))
  default = {}
}

variable "jobs" {
  description = "Mapa de nombre logico a definicion de job de Cloud Run. Los jobs admiten hasta 7 dias de ejecucion y 10.000 tareas, que es el mecanismo de fan-out masivo en GCP al no existir Distributed Map."
  type = map(object({
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

variable "image_names" {
  description = "Nombres de las imagenes gestionadas en el repositorio, usados por la politica de limpieza para decidir que versiones conservar."
  type        = list(string)
  default     = []
}

variable "retained_image_count" {
  description = "Numero de versiones recientes que se conservan por imagen."
  type        = number
  default     = 10
}

variable "vpc_network_name" {
  description = "Nombre de la VPC para Direct VPC egress. Nulo desactiva el egreso privado."
  type        = string
  default     = null
}

variable "vpc_subnet_name" {
  description = "Nombre de la subred para Direct VPC egress. Debe ser /26 o mayor."
  type        = string
  default     = null
}

variable "firestore_database_name" {
  description = "Nombre de la base de datos de Firestore que consume el runtime."
  type        = string
}

variable "capabilities_collection" {
  description = "Nombre del grupo de colecciones del Registro de Capacidades."
  type        = string
  default     = "capabilities"
}

variable "documents_bucket_name" {
  description = "Nombre del bucket de imagenes de documentos."
  type        = string
}

variable "biometrics_bucket_name" {
  description = "Nombre del bucket de datos biometricos."
  type        = string
}

variable "staging_bucket_name" {
  description = "Nombre del bucket de artefactos intermedios."
  type        = string
}

variable "evidence_bucket_name" {
  description = "Nombre del bucket WORM de evidencia."
  type        = string
}

variable "platform_kms_key_id" {
  description = "Identificador completo de la llave de Cloud KMS de plataforma, usada como CMEK del repositorio de imagenes."
  type        = string
  default     = null
}

variable "extra_environment" {
  description = "Variables de entorno adicionales comunes a todos los servicios y jobs."
  type        = map(string)
  default     = {}
}

variable "log_level" {
  description = "Nivel de registro que se inyecta como variable de entorno."
  type        = string
  default     = "INFO"
}

variable "enable_deletion_protection" {
  description = "Activa la proteccion contra borrado de servicios y jobs. Debe estar activa en produccion."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Etiquetas adicionales aplicadas a los recursos de este modulo."
  type        = map(string)
  default     = {}
}
