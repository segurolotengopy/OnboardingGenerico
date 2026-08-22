# Modulo `aws/orchestration`

## Que crea

- **`og-{env}-onboarding-saga`** — maquina de estado **Standard** (padre). Resuelve el plan de pasos
  contra el Registro de Capacidades, lanza los hijos Express en paralelo, calcula riesgo y espera la
  decision humana con `.waitForTaskToken`.
- **`og-{env}-extraction-express`** — hijo **Express**: preprocesado, OCR generico y extraccion de
  campos con modelo multimodal.
- **`og-{env}-biometrics-express`** — hijo **Express**: comparacion facial y vivacidad en paralelo.
- Log groups con retencion parametrizada, roles de ejecucion de menor privilegio y el rol que usa
  API Gateway para llamar a `StartExecution` sin Lambda intermedia.

Las definiciones ASL se generan con `jsonencode()` sobre estructuras HCL: quedan versionadas junto al
resto de la configuracion y se pueden componer con variables.

## Como se usa

```hcl
module "orchestration" {
  source = "../../modules/aws/orchestration"
  env    = var.env

  plan_resolver_function_arn         = module.compute.function_arns["plan-resolver"]
  preprocess_function_arn            = module.compute.function_arns["preprocess"]
  ocr_function_arn                   = module.compute.function_arns["ocr"]
  field_extraction_function_arn      = module.compute.function_arns["field-extraction"]
  face_match_function_arn            = module.compute.function_arns["face-match"]
  liveness_function_arn              = module.compute.function_arns["liveness"]
  risk_scoring_function_arn          = module.compute.function_arns["risk-scoring"]
  human_review_dispatch_function_arn = module.compute.function_arns["human-review-dispatch"]
  decision_recorder_function_arn     = module.compute.function_arns["decision-recorder"]

  invokable_function_arns = values(module.compute.function_arns)
  event_bus_arn           = module.observability.event_bus_arn
  event_bus_name          = module.observability.event_bus_name

  log_retention_days = 400
  log_level          = "ERROR"
}
```

## Advertencias

- 🔴 **Payload de 256 KiB.** Ningun dato binario viaja por el estado: solo punteros `s3://`. Los
  `ResultSelector` de este modulo estan puestos precisamente para recortar la respuesta de cada Lambda
  antes de que engorde el estado.
- 🔴 **Historial de Standard: 25.000 eventos por ejecucion.** Un bucle sobre muchos documentos con
  reintentos lo agota y la ejecucion falla. Si su flujo se acerca al limite, encadene ejecuciones
  nuevas en lugar de alargar la misma.
- **Duracion maxima de Standard: 1 anio** (no "sin limite"). Express: **5 minutos**.
- **Express no soporta `.waitForTaskToken`, `.sync`, Distributed Map ni Activities.** Todo lo que
  implique espera humana o job largo vive en el padre.
- **Express es at-least-once.** Cada Task invocado desde un hijo Express debe ser idempotente: clave de
  idempotencia derivada de `caseId` + `stepId` y escrituras condicionales en DynamoDB. El modulo pasa
  `idempotencyKey` explicitamente en el primer paso como recordatorio del patron.
- **Los hijos Express no tienen historial consultable.** Sin CloudWatch Logs no hay forma de saber que
  paso. Para trazabilidad KYC/AML eso no es opcional, y su coste no es despreciable.
- **El historial de Standard se retiene 90 dias** tras el cierre de la ejecucion. La obligacion
  regulatoria es de anios: exporte la evidencia al bucket WORM durante la ejecucion, no confie en el
  historial del servicio.
- **`include_execution_data = true` vuelca entradas y salidas a los logs.** En eKYC eso significa
  metadatos de PII en CloudWatch. Mantengalo apagado en produccion.
- **El patron `.sync` necesita permisos sobre `StepFunctionsGetEventsForStepFunctionsExecutionRule`**
  de EventBridge. Si faltan, el estado se queda esperando indefinidamente sin un error claro.
- **No cite porcentajes de ahorro genericos.** El ahorro del patron anidado depende del numero de
  transiciones del padre y de la duracion media de los hijos. Calculelo con sus propios numeros.
- El nombre de ejecucion se deriva de `$context.requestId` en la plantilla VTL: es unico y da
  idempotencia natural ante reintentos del cliente, ya que `StartExecution` con el mismo nombre y la
  misma entrada no crea una segunda ejecucion.
