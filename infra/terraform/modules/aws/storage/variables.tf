variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "kms_key_arn" {
  description = "ARN de la llave KMS usada como cifrado por defecto de todos los buckets. El cifrado por tenant a nivel de objeto es adicional y lo aplica la aplicacion."
  type        = string
}

variable "bucket_name_suffix" {
  description = "Sufijo que garantiza la unicidad global del nombre de bucket. Si se deja vacio se usa el identificador de la cuenta de AWS."
  type        = string
  default     = ""
}

variable "document_retention_days" {
  description = "Dias de retencion de las imagenes de documentos de identidad. Debe derivarse de la obligacion KYC/AML de la jurisdiccion mas exigente entre los tenants del entorno; nulo desactiva la expiracion."
  type        = number
  default     = 2555 # aproximadamente 7 anios
}

variable "biometric_retention_days" {
  description = "Dias de retencion de selfies, frames de liveness y embeddings. Suele ser menor que la del documento porque en varias jurisdicciones la biometria es dato de categoria especial."
  type        = number
  default     = 1095 # 3 anios
}

variable "staging_retention_days" {
  description = "Dias de retencion de artefactos intermedios. Debe ser corto: son datos derivados y reconstruibles."
  type        = number
  default     = 7
}

variable "noncurrent_version_retention_days" {
  description = "Dias que se conservan las versiones no actuales antes de expirar. El versionado protege contra sobrescritura accidental, pero cada version se factura."
  type        = number
  default     = 30
}

variable "evidence_object_lock_mode" {
  description = "Modo de Object Lock del bucket de evidencia: GOVERNANCE permite eludir la retencion con el permiso s3:BypassGovernanceRetention; COMPLIANCE no lo permite a nadie, ni al root de la cuenta."
  type        = string
  default     = "GOVERNANCE"

  validation {
    condition     = contains(["GOVERNANCE", "COMPLIANCE"], var.evidence_object_lock_mode)
    error_message = "evidence_object_lock_mode debe ser GOVERNANCE o COMPLIANCE."
  }
}

variable "evidence_retention_years" {
  description = "Anios de retencion por defecto de los objetos de evidencia. Con modo COMPLIANCE este valor es irreversible objeto por objeto."
  type        = number
  default     = 7
}

variable "allow_force_destroy" {
  description = "Permite que Terraform borre buckets con objetos. Solo debe activarse en entornos efimeros. Nunca aplica al bucket de evidencia."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
