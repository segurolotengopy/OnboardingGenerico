# Modulo `aws/api`

## Que crea

- **API REST** `og-{env}-api` con endpoint regional.
- **Lambda Authorizer** de tipo `REQUEST` sobre la cabecera `Authorization`, con TTL de cache
  parametrizable.
- **`POST /v1/onboarding/cases`** con integracion **directa** a `states:action/StartExecution` mediante
  plantilla VTL. Sin Lambda intermedia.
- **`ANY /v1/{proxy+}`** con integracion `AWS_PROXY` hacia la funcion de consulta y administracion.
- **Validador de peticion** y modelo JSON Schema que **rechaza `additionalProperties`**, de modo que
  nadie pueda colar un `tenantId` en el cuerpo.
- **Etapa** con logs de acceso en formato JSON que incluyen `tenantId`, y `method_settings` con
  throttling.
- **Un plan de uso y una clave de API por tenant**, con cuota y throttling por tier.
- **WAFv2 opcional** con el conjunto de reglas comunes de AWS y limite de tasa por IP.

## Como se usa

```hcl
module "api" {
  source = "../../modules/aws/api"
  env    = var.env

  authorizer_function_arn = module.compute.function_arns["authorizer"]
  api_function_arn        = module.compute.function_arns["api"]
  api_function_invoke_arn = module.compute.function_invoke_arns["api"]

  start_execution_role_arn         = module.orchestration.apigw_start_execution_role_arn
  start_execution_request_template = module.orchestration.start_execution_request_template

  tenant_usage_plans = {
    "acme"   = { tier = "premium",  rate_limit = 100, burst_limit = 200, quota_limit = 500000 }
    "globex" = { tier = "standard", rate_limit = 20,  burst_limit = 40 }
  }

  enable_waf = true
}
```

## Advertencias

- 🔴 **El tenant jamas se toma del cuerpo de la peticion.** Sale de `$context.authorizer.tenantId`. El
  modelo de entrada declara `additionalProperties: false` precisamente para que un `tenantId` enviado
  por el cliente sea rechazado, no ignorado.
- **La cache del autorizador retrasa la revocacion.** Un token revocado sigue siendo aceptado hasta que
  expira la entrada de cache. En eKYC, prefiera un TTL bajo o cero y absorba el coste de invocacion.
- **Mantenga el autorizador delgado.** GCP API Gateway solo admite autenticacion declarativa (claves de
  API, JWT contra emisores configurados, cuentas de servicio); **no ejecuta codigo arbitrario por
  peticion**. Si la logica de autorizacion se cablea en este Lambda, no habra adaptador equivalente en
  GCP. La logica pertenece al nucleo; este autorizador solo la invoca.
- **`data_trace_enabled` y `sampled_requests_enabled` estan apagados a proposito**: volcarian cuerpos de
  peticion con PII a CloudWatch y a los registros de muestra del WAF.
- **Las imagenes no pasan por el gateway.** El cliente pide una URL prefirmada de S3 y sube
  directamente. Ademas de evitar el limite de payload, saca los binarios del camino critico.
- **Las claves de API no son autenticacion.** Sirven para medir y limitar por tenant; la identidad la
  aporta el token validado por el autorizador. No las trate como secreto de seguridad.
- **`aws_api_gateway_deployment` necesita el `triggers` con hash de la definicion.** Sin el, un cambio
  de integracion se aplica al recurso pero no llega a la etapa desplegada, y la API sigue sirviendo la
  version anterior sin ningun error visible.
- El limite de burst de una etapa y el de un plan de uso se aplican **ambos**: el mas restrictivo gana.
