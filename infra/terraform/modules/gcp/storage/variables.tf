variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "location" {
  description = "Ubicacion de los buckets. Puede ser una region, una region dual o una multirregion. Fijela de forma explicita si hay requisitos de residencia de datos."
  type        = string
  default     = "US"
}

variable "bucket_name_suffix" {
  description = "Sufijo que garantiza la unicidad global del nombre de bucket, normalmente el identificador del proyecto."
  type        = string
}

variable "cmek_key_name" {
  description = "Nombre completo de la llave de Cloud KMS usada como cifrado por defecto. Es cifrado en reposo a nivel de servicio: no sustituye al cifrado de campo por tenant."
  type        = string
  default     = null
}

variable "document_retention_days" {
  description = "Dias de retencion de las imagenes de documentos de identidad. Nulo desactiva la expiracion."
  type        = number
  default     = 2555
}

variable "biometric_retention_days" {
  description = "Dias de retencion de selfies, frames de vivacidad y embeddings."
  type        = number
  default     = 1095
}

variable "staging_retention_days" {
  description = "Dias de retencion de artefactos intermedios."
  type        = number
  default     = 7
}

variable "noncurrent_version_retention_days" {
  description = "Dias que se conservan las versiones no actuales antes de eliminarse."
  type        = number
  default     = 30
}

variable "soft_delete_retention_seconds" {
  description = "Segundos de retencion de la politica de borrado suave. Cero la DESACTIVA. El valor por defecto de Google Cloud son 7 dias, lo que hace que un borrado no sea un borrado: incompatible con el derecho de supresion."
  type        = number
  default     = 0
}

variable "evidence_retention_years" {
  description = "Anios de retencion de la politica del bucket de evidencia."
  type        = number
  default     = 7
}

variable "lock_evidence_retention" {
  description = "Bloquea la politica de retencion del bucket de evidencia. IRREVERSIBLE: una vez bloqueada solo puede alargarse, nunca acortarse ni eliminarse, y el bucket no puede borrarse hasta que expire la retencion de todos sus objetos."
  type        = bool
  default     = false
}

variable "allow_force_destroy" {
  description = "Permite que Terraform borre buckets con objetos. Solo en entornos efimeros. Nunca aplica al bucket de evidencia."
  type        = bool
  default     = false
}

variable "runtime_service_account_email" {
  description = "Correo de la cuenta de servicio del runtime a la que se conceden los roles de acceso a los buckets."
  type        = string
  default     = null
}

variable "labels" {
  description = "Etiquetas adicionales aplicadas a los buckets. Las obligatorias del proyecto se propagan desde el entorno."
  type        = map(string)
  default     = {}
}
