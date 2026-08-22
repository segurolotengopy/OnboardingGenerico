variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "python_runtime" {
  description = "Runtime gestionado de las funciones empaquetadas como zip."
  type        = string
  default     = "python3.12"
}

variable "zip_architecture" {
  description = "Arquitectura de las funciones zip: x86_64 o arm64. arm64 es mas barato pero exige dependencias nativas compiladas para esa arquitectura."
  type        = string
  default     = "arm64"
}

variable "inference_memory_mb" {
  description = "Memoria por defecto de las funciones de inferencia, en MB. Valor de PARTIDA, no recomendacion: el rango real de Lambda es 128 a 10240 MB y la vCPU asignada es proporcional a la memoria, asi que el optimo de coste y latencia solo se encuentra perfilando la funcion con su modelo real. No existe ningun requisito de memoria ligado a extensiones vectoriales."
  type        = number
  default     = 4096

  validation {
    condition     = var.inference_memory_mb >= 128 && var.inference_memory_mb <= 10240
    error_message = "inference_memory_mb debe estar entre 128 y 10240."
  }
}

variable "zip_functions" {
  description = "Mapa de nombre logico a definicion de funcion empaquetada como zip. La clave se concatena al prefijo og-{env}- para formar el nombre de la funcion."
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

variable "container_functions" {
  description = "Mapa de nombre logico a definicion de funcion empaquetada como imagen de contenedor. Se crea un repositorio de ECR por entrada."
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

variable "artifacts_bucket_name" {
  description = "Bucket que contiene los artefactos zip de las funciones y de la capa compartida. Se aprovisiona fuera de este modulo, normalmente por el pipeline de CI."
  type        = string
  default     = ""
}

variable "shared_layer_s3_key" {
  description = "Clave del objeto en el bucket de artefactos que contiene la capa compartida. Nulo desactiva la capa."
  type        = string
  default     = null
}

variable "vpc_config" {
  description = "Configuracion de red para las funciones marcadas con in_vpc. Nulo significa que ninguna funcion se despliega dentro de la VPC."
  type        = object({
    subnet_ids         = list(string)
    security_group_ids = list(string)
  })
  default = null
}

variable "core_table_name" {
  description = "Nombre de la tabla single-table del dominio."
  type        = string
}

variable "capabilities_table_name" {
  description = "Nombre de la tabla del Registro de Capacidades."
  type        = string
}

variable "capabilities_table_arn" {
  description = "ARN de la tabla del Registro de Capacidades. El rol de ejecucion la lee sin scoping de tenant porque es catalogo de plataforma."
  type        = string
}

variable "locks_table_name" {
  description = "Nombre de la tabla de mutex distribuido."
  type        = string
}

variable "locks_table_arn" {
  description = "ARN de la tabla de mutex distribuido."
  type        = string
}

variable "keystore_table_name" {
  description = "Nombre de la tabla de branch keys del hierarchical keyring, o nulo si no se usa."
  type        = string
  default     = null
}

variable "keystore_table_arn" {
  description = "ARN de la tabla de branch keys, o nulo si no se usa."
  type        = string
  default     = null
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

variable "staging_bucket_arn" {
  description = "ARN del bucket de artefactos intermedios."
  type        = string
}

variable "evidence_bucket_name" {
  description = "Nombre del bucket WORM de evidencia."
  type        = string
}

variable "evidence_bucket_arn" {
  description = "ARN del bucket WORM de evidencia."
  type        = string
}

variable "platform_kms_key_arn" {
  description = "ARN de la llave KMS de plataforma. Cifra las variables de entorno, las imagenes de ECR y los objetos de trabajo."
  type        = string
}

variable "tenant_scoped_role_arn" {
  description = "ARN del rol tenant-scoped que las funciones asumen por peticion. Es la unica via por la que el codigo accede a datos de tenant."
  type        = string
  default     = null
}

variable "readable_secret_arns" {
  description = "ARNs de los secretos de Secrets Manager que las funciones pueden leer (credenciales de proveedores externos)."
  type        = list(string)
  default     = []
}

variable "extra_environment" {
  description = "Variables de entorno adicionales comunes a todas las funciones. El limite agregado de variables de entorno por funcion es 4 KB."
  type        = map(string)
  default     = {}
}

variable "ecr_retained_image_count" {
  description = "Numero de imagenes etiquetadas que se conservan por repositorio antes de expirar las mas antiguas."
  type        = number
  default     = 10
}

variable "log_retention_days" {
  description = "Dias de retencion de los log groups de las funciones."
  type        = number
  default     = 30
}

variable "log_kms_key_arn" {
  description = "ARN de la llave KMS para cifrar los log groups. Nulo usa el cifrado gestionado por el servicio."
  type        = string
  default     = null
}

variable "log_level" {
  description = "Nivel de registro que se inyecta como variable de entorno LOG_LEVEL."
  type        = string
  default     = "INFO"
}

variable "enable_xray" {
  description = "Activa el trazado con X-Ray en todas las funciones."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
