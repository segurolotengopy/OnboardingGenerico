variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "parent_state_machine_arn" {
  description = "ARN de la maquina de estado Standard que orquesta la saga, para las alarmas y el panel."
  type        = string
}

variable "core_table_name" {
  description = "Nombre de la tabla single-table del dominio."
  type        = string
}

variable "api_name" {
  description = "Nombre de la API REST, tal como aparece en la dimension ApiName de CloudWatch."
  type        = string
}

variable "api_stage_name" {
  description = "Nombre de la etapa de la API."
  type        = string
}

variable "monitored_function_names" {
  description = "Mapa de nombre logico a nombre completo de funcion Lambda a vigilar con alarmas de errores y estrangulamiento."
  type        = map(string)
  default     = {}
}

variable "custom_metric_namespace" {
  description = "Espacio de nombres de las metricas propias emitidas por el codigo con el formato de metricas embebidas de CloudWatch."
  type        = string
  default     = "OnboardingGenerico"
}

variable "log_retention_days" {
  description = "Dias de retencion del log group de eventos de dominio. Debe cubrir la obligacion regulatoria, no solo la ventana operativa."
  type        = number
  default     = 400
}

variable "log_kms_key_arn" {
  description = "ARN de la llave KMS para cifrar los log groups de este modulo."
  type        = string
  default     = null
}

variable "event_archive_retention_days" {
  description = "Dias de retencion del archivo de eventos de EventBridge. Cero significa retencion indefinida."
  type        = number
  default     = 365
}

variable "sns_kms_key_id" {
  description = "Identificador de la llave KMS que cifra el topico de alarmas. Nulo deja el topico sin cifrado gestionado por cliente."
  type        = string
  default     = null
}

variable "alarm_email_subscriptions" {
  description = "Mapa de nombre a direccion de correo suscrita al topico de alarmas. Cada suscripcion requiere confirmacion manual del destinatario."
  type        = map(string)
  default     = {}
}

variable "saga_failure_threshold" {
  description = "Numero de ejecuciones fallidas en cinco minutos que dispara la alarma."
  type        = number
  default     = 0
}

variable "lambda_error_threshold" {
  description = "Numero de errores de funcion en cinco minutos que dispara la alarma."
  type        = number
  default     = 0
}

variable "api_5xx_threshold" {
  description = "Numero de errores 5XX en cinco minutos que dispara la alarma."
  type        = number
  default     = 5
}

variable "enable_crypto_health_alarm" {
  description = "Activa la alarma sobre la proporcion de data keys unicas por registro, indicador de cache stampede en el material criptografico."
  type        = bool
  default     = true
}

variable "unique_data_key_ratio_threshold" {
  description = "Proporcion maxima aceptable de data keys unicas por registro escrito. Valores cercanos a uno indican que la cache no esta coordinando y el coste de KMS se dispara."
  type        = number
  default     = 0.1
}

variable "enable_xray" {
  description = "Crea la regla de muestreo de X-Ray."
  type        = bool
  default     = true
}

variable "xray_reservoir_size" {
  description = "Trazas por segundo capturadas de forma garantizada antes de aplicar la tasa fija."
  type        = number
  default     = 2
}

variable "xray_fixed_rate" {
  description = "Proporcion de peticiones muestreadas por encima del reservorio, entre cero y uno."
  type        = number
  default     = 0.05
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
