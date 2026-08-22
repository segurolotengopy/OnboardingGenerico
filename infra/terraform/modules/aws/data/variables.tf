variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "kms_key_arn" {
  description = "ARN de la llave KMS de plataforma usada para el cifrado en reposo de las tablas. El cifrado a nivel de campo por tenant es adicional y vive en la aplicacion."
  type        = string
}

variable "billing_mode" {
  description = "Modo de facturacion de la tabla core: PAY_PER_REQUEST o PROVISIONED. On-demand es lo recomendado mientras el patron de carga no sea estable."
  type        = string
  default     = "PAY_PER_REQUEST"

  validation {
    condition     = contains(["PAY_PER_REQUEST", "PROVISIONED"], var.billing_mode)
    error_message = "billing_mode debe ser PAY_PER_REQUEST o PROVISIONED."
  }
}

variable "provisioned_read_capacity" {
  description = "Unidades de capacidad de lectura cuando billing_mode es PROVISIONED."
  type        = number
  default     = 5
}

variable "provisioned_write_capacity" {
  description = "Unidades de capacidad de escritura cuando billing_mode es PROVISIONED."
  type        = number
  default     = 5
}

variable "table_class" {
  description = "Clase de almacenamiento de la tabla core: STANDARD o STANDARD_INFREQUENT_ACCESS. La segunda conviene cuando el volumen de datos historicos supera con mucho al de accesos."
  type        = string
  default     = "STANDARD"
}

variable "enable_point_in_time_recovery" {
  description = "Habilita point-in-time recovery (ventana de 35 dias). Obligatorio en produccion; en dev encarece sin aportar valor."
  type        = bool
  default     = false
}

variable "enable_deletion_protection" {
  description = "Activa la proteccion contra borrado de la tabla en el propio servicio de DynamoDB, independiente de Terraform."
  type        = bool
  default     = false
}

variable "protect_from_destroy" {
  description = "Cuando es verdadero se crea la variante de la tabla core con lifecycle prevent_destroy. Cambiar este valor sobre una tabla existente fuerza una recreacion: no lo modifique en un entorno con datos."
  type        = bool
  default     = false
}

variable "create_keystore_table" {
  description = "Crea la tabla de branch keys del hierarchical keyring del AWS Database Encryption SDK."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
