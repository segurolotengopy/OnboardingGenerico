variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "tenants" {
  description = "Mapa de tenant_id a sus atributos. La clave del mapa es el tenant_id tal como aparece en el session tag TenantID y en el encryption context. Se crea una CMK por entrada."
  type        = map(object({
    tier         = optional(string, "standard")
    jurisdiction = optional(string, "")
  }))
  default = {}
}

variable "deletion_window_in_days" {
  description = "Ventana de espera antes de la destruccion efectiva de una llave. AWS admite de 7 a 30 dias y el minimo duro es 7. Cualquier SLA de borrado prometido al cliente debe ser mayor que este valor mas margen."
  type        = number
  default     = 30

  validation {
    condition     = var.deletion_window_in_days >= 7 && var.deletion_window_in_days <= 30
    error_message = "deletion_window_in_days debe estar entre 7 y 30."
  }
}

variable "rotation_period_in_days" {
  description = "Periodo de rotacion automatica del material criptografico, en dias. El valor por defecto de AWS es 365."
  type        = number
  default     = 365
}

variable "platform_key_multi_region" {
  description = "Crea la llave de plataforma como multi-region. Solo tiene sentido si hay replica de datos en otra region; una llave multi-region no puede convertirse en regional despues."
  type        = bool
  default     = false
}

variable "key_administrator_arns" {
  description = "ARNs de los principals autorizados a administrar las llaves (crear alias, programar destruccion). Lista vacia deja la administracion solo en manos del root de la cuenta."
  type        = list(string)
  default     = []
}

variable "platform_key_user_arns" {
  description = "ARNs de los principals autorizados a usar la llave de plataforma para operaciones criptograficas."
  type        = list(string)
  default     = []
}

variable "tenant_key_user_arns" {
  description = "ARNs de los principals autorizados a usar las CMK de tenant, siempre sujetos a la condicion de encryption context."
  type        = list(string)
  default     = []
}

variable "tenant_grant_principal_arn" {
  description = "ARN del rol tenant-scoped al que se concede un grant por tenant con EncryptionContextEquals. Si es nulo no se crean grants y el acceso depende solo de la politica de llave."
  type        = string
  default     = null
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
