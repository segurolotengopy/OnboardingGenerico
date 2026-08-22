variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "stage_name" {
  description = "Nombre de la etapa de despliegue de la API."
  type        = string
  default     = "v1"
}

variable "endpoint_type" {
  description = "Tipo de endpoint de la API: EDGE, REGIONAL o PRIVATE. REGIONAL es lo habitual para un middleware B2B con clientes en una region conocida."
  type        = string
  default     = "REGIONAL"
}

variable "authorizer_function_arn" {
  description = "ARN de la funcion Lambda del autorizador. Debe ser una capa delgada que delegue en la logica de autorizacion del nucleo: GCP API Gateway no admite autorizadores de codigo arbitrario y esa logica debe ser portable."
  type        = string
}

variable "authorizer_cache_ttl_seconds" {
  description = "Segundos de cache del resultado del autorizador. Un valor alto ahorra invocaciones pero retrasa la revocacion de un token. Cero desactiva la cache."
  type        = number
  default     = 300
}

variable "api_function_arn" {
  description = "ARN de la funcion que atiende las rutas de consulta y administracion bajo /v1/{proxy+}."
  type        = string
}

variable "api_function_invoke_arn" {
  description = "Invoke ARN de la misma funcion, en el formato que espera la integracion AWS_PROXY."
  type        = string
}

variable "start_execution_role_arn" {
  description = "ARN del rol que asume API Gateway para llamar a StartExecution. Lo produce el modulo de orquestacion."
  type        = string
}

variable "start_execution_request_template" {
  description = "Plantilla VTL de la integracion directa con Step Functions. La produce el modulo de orquestacion para que el ARN de la maquina de estado no se duplique."
  type        = string
}

variable "tenant_usage_plans" {
  description = "Mapa de tenant_id a su plan de uso. Permite cuotas y throttling diferenciados por tier e impide que un tenant ruidoso consuma la capacidad de los demas."
  type        = map(object({
    tier         = optional(string, "standard")
    rate_limit   = optional(number, 20)
    burst_limit  = optional(number, 40)
    quota_limit  = optional(number, null)
    quota_period = optional(string, "DAY")
  }))
  default = {}
}

variable "stage_throttle_rate_limit" {
  description = "Limite de peticiones por segundo a nivel de etapa, aplicado por encima de los planes de uso."
  type        = number
  default     = 200
}

variable "stage_throttle_burst_limit" {
  description = "Capacidad de rafaga a nivel de etapa."
  type        = number
  default     = 400
}

variable "enable_waf" {
  description = "Asocia un Web ACL de WAFv2 a la etapa, con el conjunto de reglas comunes gestionado por AWS y un limite de tasa por IP."
  type        = bool
  default     = false
}

variable "waf_rate_limit" {
  description = "Peticiones por IP en una ventana de cinco minutos antes de bloquear."
  type        = number
  default     = 2000
}

variable "execution_log_level" {
  description = "Nivel de los logs de ejecucion de API Gateway: OFF, ERROR o INFO."
  type        = string
  default     = "ERROR"
}

variable "log_retention_days" {
  description = "Dias de retencion del log group de acceso de la API."
  type        = number
  default     = 30
}

variable "log_kms_key_arn" {
  description = "ARN de la llave KMS para cifrar el log group de acceso. Nulo usa el cifrado gestionado por el servicio."
  type        = string
  default     = null
}

variable "enable_xray" {
  description = "Habilita el trazado con X-Ray en la etapa."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
