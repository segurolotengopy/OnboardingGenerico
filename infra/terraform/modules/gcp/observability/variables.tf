variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "log_bucket_location" {
  description = "Ubicacion del bucket de logs de auditoria. Fijela de forma explicita si hay requisitos de residencia de datos."
  type        = string
  default     = "global"
}

variable "audit_log_retention_days" {
  description = "Dias de retencion del bucket de logs de auditoria. El rango admitido es de 1 a 3650 dias. El bucket _Required retiene 400 dias y no es configurable."
  type        = number
  default     = 400
}

variable "long_term_sink_bucket" {
  description = "Nombre del bucket de Cloud Storage al que se copian los logs de acceso a datos para retencion de anios. Nulo desactiva el sink."
  type        = string
  default     = null
}

variable "enable_audit_config" {
  description = "Habilita los Data Access audit logs desde este modulo. Si tambien los declara el modulo gcp/identity, deje activo solo uno para evitar conflictos de propiedad del recurso."
  type        = bool
  default     = false
}

variable "audited_services" {
  description = "Servicios cuyos Data Access audit logs se habilitan cuando enable_audit_config es verdadero."
  type        = list(string)
  default     = [
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
  ]
}

variable "alert_email_channels" {
  description = "Mapa de nombre a direccion de correo de los canales de notificacion."
  type        = map(string)
  default     = {}
}

variable "workflow_failure_threshold" {
  description = "Numero de ejecuciones fallidas del workflow en cinco minutos que dispara la alerta."
  type        = number
  default     = 0
}

variable "cloud_run_5xx_threshold" {
  description = "Numero de respuestas 5xx en cinco minutos que dispara la alerta."
  type        = number
  default     = 5
}

variable "decryption_failure_threshold" {
  description = "Numero de fallos de descifrado en cinco minutos que dispara la alerta. Cero significa que cualquier fallo se notifica."
  type        = number
  default     = 0
}
