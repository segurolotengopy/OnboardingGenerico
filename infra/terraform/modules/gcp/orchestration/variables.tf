variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "region" {
  description = "Region del workflow, las colas de Cloud Tasks y los triggers de Eventarc."
  type        = string
}

variable "workflow_service_account_email" {
  description = "Cuenta de servicio con la que se ejecuta el workflow y con la que se firman los tokens OIDC de las llamadas salientes."
  type        = string
}

variable "composer_service_url" {
  description = "URL base del servicio Cloud Run que resuelve el plan, calcula riesgo y registra decisiones."
  type        = string
}

variable "composer_service_name" {
  description = "Nombre del servicio Cloud Run del composer, para el destino del trigger de Eventarc."
  type        = string
}

variable "extraction_service_url" {
  description = "URL base del servicio de extraccion documental."
  type        = string
}

variable "biometrics_service_url" {
  description = "URL base del servicio de biometria."
  type        = string
}

variable "review_service_url" {
  description = "URL base del servicio de cola de revision manual."
  type        = string
}

variable "callback_timeout_seconds" {
  description = "Tiempo de espera del callback de revision manual. El valor por defecto del servicio es 43200 segundos (12 horas). PENDIENTE DE VERIFICAR: no esta documentado un maximo por encima de ese valor. Si la revision puede cruzar un fin de semana, use el patron de persistir y relanzar en lugar de subir este numero."
  type        = number
  default     = 43200
}

variable "call_log_level" {
  description = "Nivel de registro de las llamadas del workflow: LOG_ALL_CALLS, LOG_ERRORS_ONLY o LOG_NONE. LOG_ALL_CALLS registra cuerpos de peticion y puede volcar metadatos de PII."
  type        = string
  default     = "LOG_ERRORS_ONLY"
}

variable "task_max_dispatches_per_second" {
  description = "Despachos por segundo de la cola de verificaciones. El maximo del servicio es 500 por cola."
  type        = number
  default     = 100
}

variable "task_max_concurrent_dispatches" {
  description = "Tareas concurrentes en vuelo en la cola de verificaciones."
  type        = number
  default     = 50
}

variable "task_max_attempts" {
  description = "Intentos maximos por tarea antes de darla por fallida."
  type        = number
  default     = 5
}

variable "task_max_retry_duration_seconds" {
  description = "Tiempo maximo durante el que se reintenta una tarea."
  type        = number
  default     = 3600
}

variable "task_log_sampling_ratio" {
  description = "Proporcion de operaciones de cola registradas, entre cero y uno."
  type        = number
  default     = 0.1
}

variable "external_max_dispatches_per_second" {
  description = "Despachos por segundo hacia proveedores externos. Debe respetar el limite contractual del proveedor."
  type        = number
  default     = 10
}

variable "external_max_concurrent_dispatches" {
  description = "Llamadas concurrentes a proveedores externos."
  type        = number
  default     = 10
}

variable "event_retention_days" {
  description = "Dias de retencion de los mensajes en el topico y la suscripcion. El maximo del servicio es 31 dias."
  type        = number
  default     = 7
}

variable "enable_message_ordering" {
  description = "Activa las claves de ordenacion en la suscripcion. Necesario si la saga depende del orden de eventos por caso, ya que Firestore con Eventarc no garantiza orden. Reduce el rendimiento a 1 MBps por clave."
  type        = bool
  default     = true
}

variable "max_delivery_attempts" {
  description = "Intentos de entrega antes de mover el mensaje al topico de mensajes fallidos."
  type        = number
  default     = 5
}

variable "enable_firestore_trigger" {
  description = "Crea el trigger de Eventarc sobre cambios en la coleccion de casos."
  type        = bool
  default     = true
}

variable "firestore_database_name" {
  description = "Nombre de la base de datos de Firestore observada por el trigger."
  type        = string
  default     = "(default)"
}

variable "cases_collection" {
  description = "Nombre del grupo de colecciones de casos, para el patron de ruta del trigger."
  type        = string
  default     = "cases"
}

variable "cmek_key_name" {
  description = "Nombre completo de la llave de Cloud KMS que cifra los topicos de Pub/Sub."
  type        = string
  default     = null
}

variable "labels" {
  description = "Etiquetas adicionales aplicadas a los recursos de este modulo."
  type        = map(string)
  default     = {}
}
