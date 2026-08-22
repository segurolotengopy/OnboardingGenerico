variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "plan_resolver_function_arn" {
  description = "ARN de la funcion que resuelve el plan de pasos contra el Registro de Capacidades segun tenant, pais y tipo de documento."
  type        = string
}

variable "preprocess_function_arn" {
  description = "ARN de la funcion de normalizacion de imagen (recorte, correccion de perspectiva, control de calidad)."
  type        = string
}

variable "ocr_function_arn" {
  description = "ARN de la funcion de OCR generico."
  type        = string
}

variable "field_extraction_function_arn" {
  description = "ARN de la funcion que estructura los campos del documento con un modelo multimodal, con prompt por pais y tipo de documento."
  type        = string
}

variable "face_match_function_arn" {
  description = "ARN de la funcion de comparacion facial entre el retrato del documento y la selfie."
  type        = string
}

variable "liveness_function_arn" {
  description = "ARN de la funcion que consulta el resultado de la sesion de vivacidad."
  type        = string
}

variable "risk_scoring_function_arn" {
  description = "ARN de la funcion que calcula el puntaje de riesgo y propone decision automatica."
  type        = string
}

variable "human_review_dispatch_function_arn" {
  description = "ARN de la funcion que publica el caso en la cola de revision manual junto con el task token."
  type        = string
}

variable "decision_recorder_function_arn" {
  description = "ARN de la funcion que persiste la decision final y escribe la evidencia en el bucket WORM."
  type        = string
}

variable "invokable_function_arns" {
  description = "Lista completa de ARNs de funciones que las maquinas de estado pueden invocar. Debe incluir todas las anteriores; se usa para construir la politica de menor privilegio."
  type        = list(string)
}

variable "event_bus_arn" {
  description = "ARN del bus de EventBridge donde la saga publica eventos de dominio."
  type        = string
}

variable "event_bus_name" {
  description = "Nombre del bus de EventBridge, tal como lo espera la integracion events:putEvents."
  type        = string
}

variable "parent_timeout_seconds" {
  description = "Tiempo maximo de vida de una ejecucion de la saga, en segundos. El maximo del servicio es un anio; un valor finito evita ejecuciones zombis."
  type        = number
  default     = 2592000 # 30 dias
}

variable "human_review_timeout_seconds" {
  description = "Tiempo maximo de espera de la decision humana. Debe cubrir fines de semana y escalados a compliance. El tiempo de espera no se factura."
  type        = number
  default     = 604800 # 7 dias
}

variable "human_review_heartbeat_seconds" {
  description = "Intervalo maximo entre latidos de la tarea de revision manual. Permite detectar que el proceso revisor murio sin esperar al timeout completo."
  type        = number
  default     = 86400 # 1 dia
}

variable "log_retention_days" {
  description = "Dias de retencion de los log groups de las maquinas de estado. Recuerde que el historial de Standard solo vive 90 dias y los hijos Express no tienen historial: para trazabilidad KYC/AML hay que exportar antes de que expire."
  type        = number
  default     = 30
}

variable "log_kms_key_arn" {
  description = "ARN de la llave KMS para cifrar los log groups. Nulo usa el cifrado gestionado por el servicio."
  type        = string
  default     = null
}

variable "log_level" {
  description = "Nivel de registro de las maquinas de estado: ALL, ERROR, FATAL u OFF."
  type        = string
  default     = "ERROR"

  validation {
    condition     = contains(["ALL", "ERROR", "FATAL", "OFF"], var.log_level)
    error_message = "log_level debe ser ALL, ERROR, FATAL u OFF."
  }
}

variable "include_execution_data" {
  description = "Incluye los datos de entrada y salida en los logs. ADVERTENCIA: en eKYC eso vuelca punteros y metadatos de PII a CloudWatch. Mantengalo desactivado en produccion."
  type        = bool
  default     = false
}

variable "enable_xray" {
  description = "Habilita el trazado con X-Ray en las tres maquinas de estado."
  type        = bool
  default     = true
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
