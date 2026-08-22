# Modulo `aws/gdpr`

## Que crea

- **Mapeo del stream de la tabla core** hacia la funcion de purga, con filtro por
  `entity_type = ERASURE_REQUEST`, lotes pequenos, biseccion ante error, limite de reintentos y destino
  de fallo.
- **Cola SQS de mensajes fallidos** cifrada, con retencion maxima y denegacion de transporte inseguro.
- **Politica de borrado** adjunta al rol de la funcion de purga: son los **unicos** permisos de borrado
  de todo el sistema.
- **Barrido programado** con EventBridge Scheduler para reintentos y expiraciones de retencion.
- **Tres alarmas de cumplimiento**: cola de fallos no vacia, errores de la funcion, y retraso del
  consumo del stream.

## Como se usa

```hcl
module "gdpr" {
  source = "../../modules/aws/gdpr"
  env    = var.env

  core_table_arn        = module.data.core_table_arn
  core_table_stream_arn = module.data.core_table_stream_arn

  purge_function_arn       = module.compute.function_arns["gdpr-purge"]
  purge_function_name      = module.compute.function_names["gdpr-purge"]
  purge_function_role_name = module.compute.execution_role_name

  erasable_bucket_arns = module.storage.tenant_scoped_bucket_arns
  evidence_bucket_arn  = module.storage.evidence_bucket_arn
  tenant_kms_key_arns  = values(module.kms.tenant_key_arns)

  event_bus_arn    = module.observability.event_bus_arn
  alarms_topic_arn = module.observability.alarms_topic_arn
  kms_key_arn      = module.kms.platform_key_arn
}
```

## Advertencias

- 🔴 **El TTL no borra y el ciclo de vida tampoco acredita.** El TTL de DynamoDB elimina "tipicamente"
  dentro de 48 horas, sin transaccionalidad, y los items expirados siguen apareciendo en consultas
  hasta que desaparecen de verdad. Las reglas de S3 se aplican de forma asincrona. Ninguno de los dos
  sirve para demostrar cumplimiento ante un regulador. Por eso existe una purga explicita con
  evidencia.
- 🔴 **La evidencia bajo Object Lock no puede borrarse.** Con modo COMPLIANCE, ni el root de la cuenta
  puede. La unica via para dejarla ilegible es el **crypto-shredding** de la CMK del tenant, con la
  ventana de 7 a 30 dias de AWS KMS. Cualquier promesa contractual de borrado debe ser compatible con
  ese plazo.
- 🔴 **Con versionado activo, `DeleteObject` solo crea un marcador.** Suprimir de verdad exige
  `DeleteObjectVersion` sobre **todas** las versiones. La politica de este modulo lo contempla; el
  codigo de la funcion debe hacerlo explicitamente.
- 🔴 **DynamoDB Streams retiene solo 24 horas.** Si el consumo se retrasa mas, la solicitud de supresion
  se pierde sin dejar rastro en el stream. De ahi la alarma de `IteratorAge` y el barrido programado
  como red de seguridad.
- **Retencion contra supresion es una tension real, no un error de diseno.** Las obligaciones KYC/AML
  suelen exigir conservar de 5 a 10 anios; el derecho de supresion pide borrar. Se concilian
  conservando la evidencia minima necesaria bajo WORM y suprimiendo el resto, con el crypto-shredding
  como ultimo recurso. Documente que se conserva y por que base legal.
- **`bisect_batch_on_function_error` es importante aqui**: sin el, un registro venenoso arrastra a todo
  su lote a la cola de fallos, y hay que discriminar a mano cuales eran validos.
- **Umbral cero en las alarmas.** Una purga fallida no es un incidente operativo menor: es un plazo
  legal corriendo.
- El filtro del mapeo depende de que el codigo escriba `entity_type = "ERASURE_REQUEST"` en el item.
  Si cambia ese nombre en el dominio, este filtro deja de disparar **sin ningun error**.
