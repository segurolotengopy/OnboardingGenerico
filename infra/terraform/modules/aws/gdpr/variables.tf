variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "core_table_arn" {
  description = "ARN de la tabla single-table del dominio."
  type        = string
}

variable "core_table_stream_arn" {
  description = "ARN del stream de la tabla core. Debe estar configurado con NEW_AND_OLD_IMAGES: la funcion necesita la imagen previa para saber que objetos borrar."
  type        = string
}

variable "purge_function_arn" {
  description = "ARN de la funcion Lambda de purga."
  type        = string
}

variable "purge_function_name" {
  description = "Nombre de la funcion de purga, para las dimensiones de las alarmas."
  type        = string
}

variable "purge_function_role_name" {
  description = "Nombre del rol de ejecucion de la funcion de purga. Este modulo le adjunta los unicos permisos de borrado de todo el sistema."
  type        = string
}

variable "erasable_bucket_arns" {
  description = "ARNs de los buckets cuyos objetos pueden borrarse al ejercer el derecho de supresion. NUNCA incluya el bucket de evidencia: esta bajo Object Lock y su borrado es imposible por diseno."
  type        = list(string)
}

variable "evidence_bucket_arn" {
  description = "ARN del bucket WORM donde se escribe la evidencia de cada purga. La funcion solo puede escribir, nunca borrar."
  type        = string
}

variable "tenant_kms_key_arns" {
  description = "ARNs de las CMK de tenant sobre las que la funcion puede programar destruccion. Es el mecanismo de crypto-shredding para los datos que no pueden borrarse fisicamente."
  type        = list(string)
  default     = []
}

variable "event_bus_arn" {
  description = "ARN del bus de eventos de dominio donde se publican los eventos de supresion."
  type        = string
}

variable "alarms_topic_arn" {
  description = "ARN del topico SNS al que se publican las alarmas de cumplimiento."
  type        = string
}

variable "kms_key_arn" {
  description = "ARN de la llave KMS que cifra la cola de mensajes fallidos."
  type        = string
}

variable "batch_size" {
  description = "Numero de registros del stream por invocacion. Un lote pequeno reduce la latencia entre la solicitud y la purga."
  type        = number
  default     = 10
}

variable "maximum_batching_window_seconds" {
  description = "Segundos que se espera para completar un lote antes de invocar la funcion."
  type        = number
  default     = 5
}

variable "parallelization_factor" {
  description = "Numero de invocaciones concurrentes por shard. DynamoDB Streams ordena por clave de particion, asi que esto paraleliza entre particiones, nunca dentro de una."
  type        = number
  default     = 2
}

variable "maximum_retry_attempts" {
  description = "Reintentos antes de enviar el registro a la cola de fallos. Sin limite, un registro venenoso bloquea el shard indefinidamente."
  type        = number
  default     = 5
}

variable "maximum_record_age_seconds" {
  description = "Edad maxima de un registro antes de descartarlo. DynamoDB Streams retiene 24 horas, asi que este valor nunca deberia superarlas."
  type        = number
  default     = 43200
}

variable "dlq_retention_seconds" {
  description = "Retencion de los mensajes en la cola de fallos. El maximo de SQS es 1209600 segundos (14 dias); las solicitudes de supresion tienen plazo legal y conviene apurar el maximo."
  type        = number
  default     = 1209600
}

variable "enable_retention_sweep" {
  description = "Crea el barrido programado que reintenta solicitudes pendientes y aplica expiraciones de retencion."
  type        = bool
  default     = true
}

variable "retention_sweep_schedule" {
  description = "Expresion de planificacion del barrido, en sintaxis de EventBridge Scheduler."
  type        = string
  default     = "cron(0 3 * * ? *)"
}

variable "retention_sweep_timezone" {
  description = "Zona horaria en la que se interpreta la expresion de planificacion."
  type        = string
  default     = "UTC"
}

variable "iterator_age_threshold_ms" {
  description = "Retraso maximo aceptable del consumo del stream, en milisegundos. Debe quedar muy por debajo de las 24 horas de retencion del stream."
  type        = number
  default     = 3600000
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
