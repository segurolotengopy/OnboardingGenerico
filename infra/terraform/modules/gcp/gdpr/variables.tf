variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "region" {
  description = "Region del job de purga, el trigger y el planificador."
  type        = string
}

variable "purge_image" {
  description = "Imagen de contenedor del job de purga, con host de Artifact Registry incluido."
  type        = string
}

variable "purge_service_account_email" {
  description = "Cuenta de servicio del job de purga. Recibe los unicos permisos de borrado del sistema y debe ser distinta de la del runtime."
  type        = string
}

variable "scheduler_service_account_email" {
  description = "Cuenta de servicio con la que Cloud Scheduler invoca la ejecucion del job."
  type        = string
}

variable "dispatcher_service_name" {
  description = "Nombre del servicio de Cloud Run que recibe el evento de Eventarc y lanza la ejecucion del job. Eventarc no puede ejecutar un job directamente."
  type        = string
}

variable "firestore_database_name" {
  description = "Nombre de la base de datos de Firestore sobre la que se ejerce la supresion."
  type        = string
}

variable "erasure_requests_collection" {
  description = "Nombre del grupo de colecciones donde se escriben las solicitudes de supresion."
  type        = string
  default     = "erasure_requests"
}

variable "erasable_bucket_names" {
  description = "Nombres de los buckets cuyos objetos pueden borrarse. NUNCA incluya el bucket de evidencia: esta bajo Bucket Lock y su borrado es imposible por diseno."
  type        = list(string)
}

variable "evidence_bucket_name" {
  description = "Nombre del bucket WORM donde se escribe la evidencia de cada purga. La identidad de purga solo puede crear objetos ahi, nunca borrarlos."
  type        = string
}

variable "tenant_key_ids" {
  description = "Identificadores completos de las llaves de tenant sobre las que la purga puede programar destruccion. Es el mecanismo de crypto-shredding."
  type        = list(string)
  default     = []
}

variable "purge_timeout_seconds" {
  description = "Tiempo maximo de ejecucion del job. Un job admite hasta 7 dias; una purga masiva puede tardar horas iterando versiones de objetos."
  type        = number
  default     = 21600
}

variable "purge_max_retries" {
  description = "Reintentos del job antes de darlo por fallido."
  type        = number
  default     = 3
}

variable "enable_eventarc_trigger" {
  description = "Crea el trigger de Eventarc sobre la coleccion de solicitudes de supresion."
  type        = bool
  default     = true
}

variable "dead_letter_topic_id" {
  description = "Identificador del topico de Pub/Sub usado como transporte y destino de mensajes fallidos del trigger."
  type        = string
  default     = null
}

variable "dead_letter_subscription_id" {
  description = "Identificador de la suscripcion de mensajes fallidos, para la alerta de acumulacion. Nulo desactiva esa alerta."
  type        = string
  default     = null
}

variable "enable_retention_sweep" {
  description = "Crea el barrido programado. No es un extra: al no haber reproduccion del stream de Firestore, es lo que garantiza que ninguna solicitud se pierda."
  type        = bool
  default     = true
}

variable "retention_sweep_schedule" {
  description = "Expresion cron del barrido programado."
  type        = string
  default     = "0 3 * * *"
}

variable "retention_sweep_timezone" {
  description = "Zona horaria en la que se interpreta la expresion cron."
  type        = string
  default     = "Etc/UTC"
}

variable "notification_channel_ids" {
  description = "Identificadores de los canales de notificacion a los que se envian las alertas de cumplimiento."
  type        = list(string)
  default     = []
}

variable "enable_deletion_protection" {
  description = "Activa la proteccion contra borrado del job de purga."
  type        = bool
  default     = false
}

variable "labels" {
  description = "Etiquetas adicionales aplicadas a los recursos de este modulo."
  type        = map(string)
  default     = {}
}
