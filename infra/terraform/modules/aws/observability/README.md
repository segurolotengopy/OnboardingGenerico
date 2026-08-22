# Modulo `aws/observability`

## Que crea

- **Bus de EventBridge** `og-{env}-domain-events` con archivo para reproduccion, y una regla que copia
  todo evento `onboarding.*` a un log group de retencion larga.
- **Topico SNS de alarmas** con suscripciones de correo opcionales.
- **Alarmas**: ejecuciones fallidas y expiradas de la saga, errores y estrangulamientos por funcion,
  5XX de la API, peticiones estranguladas en la tabla core, y proporcion de data keys unicas.
- **Regla de muestreo de X-Ray** acotada a `/v1/*`.
- **Panel de CloudWatch** con saga, API, tabla core y volumen por tenant.

## Como se usa

```hcl
module "observability" {
  source = "../../modules/aws/observability"
  env    = var.env

  parent_state_machine_arn = module.orchestration.parent_state_machine_arn
  core_table_name          = module.data.core_table_name
  api_name                 = "og-${var.env}-api"
  api_stage_name           = "v1"

  monitored_function_names = module.compute.function_names
  log_retention_days       = 400

  alarm_email_subscriptions = {
    oncall = "oncall@example.invalid"
  }
}
```

> Hay una dependencia circular aparente entre este modulo y `orchestration`: la saga publica en el bus
> y el panel observa la saga. Se resuelve creando primero el bus (este modulo, sin
> `parent_state_machine_arn`) o pasando el ARN de la maquina de estado como valor conocido. En el
> arbol de `envs/` el bus se crea antes y la orquestacion lo recibe como entrada.

## Advertencias

- **Las metricas por tenant no se crean aqui.** Nacen del codigo con el formato de metricas embebidas
  de CloudWatch (EMF), que evita una llamada sincrona a la API por medicion. Terraform solo crea las
  alarmas que las consumen; si el codigo no emite, la alarma nunca se evalua.
- **`treat_missing_data = "notBreaching"` es una decision con consecuencias.** Si una funcion deja de
  invocarse por completo, su alarma de errores no se dispara. Complemente con una alarma de ausencia
  de invocaciones si el flujo debe estar siempre activo.
- **El historial de Step Functions solo vive 90 dias** tras el cierre de la ejecucion, y los hijos
  Express no tienen historial. Para trazabilidad KYC/AML, los eventos de dominio de este modulo y la
  evidencia en el bucket WORM son la fuente de verdad a largo plazo, no el historial del servicio.
- **La proporcion de data keys unicas por registro es la senal temprana de un problema caro.** Valores
  cercanos a uno significan que la cache de material criptografico no esta coordinando y cada registro
  esta generando su propia data key. Es el sintoma clasico del `CachingCryptoMaterialsManager` en
  entornos concurrentes.
- **Las suscripciones de correo de SNS requieren confirmacion manual** del destinatario. Terraform las
  crea en estado pendiente y no falla si nadie confirma: la alarma quedara muda.
- **Los logs con `data_trace` o payloads completos son un riesgo de PII**, no solo de coste. Este
  modulo no los habilita en ningun sitio.
- El archivo de EventBridge se factura por almacenamiento; `event_archive_retention_days = 0` significa
  retencion **indefinida**, no cero dias.
