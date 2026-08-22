# ---------------------------------------------------------------------------
# API Gateway REST: fachada del middleware.
#
# Dos rutas de entrada distintas y deliberadas:
#
#   POST /v1/onboarding/cases  -> integracion DIRECTA con Step Functions
#                                 (StartExecution) mediante plantilla VTL.
#                                 Sin Lambda intermedia: menos latencia, menos
#                                 coste y una superficie menos que mantener.
#
#   ANY  /v1/{proxy+}          -> integracion AWS_PROXY con la Lambda de la
#                                 API de consulta y administracion.
#
# El tenant NUNCA se toma del cuerpo de la peticion. Sale del contexto del
# autorizador, que lo deriva del token validado.
#
# NOTA DE PORTABILIDAD: se usa un Lambda Authorizer porque en AWS existe. GCP
# API Gateway no admite autorizadores de codigo arbitrario, asi que la logica de
# autorizacion debe vivir en el nucleo y este autorizador debe ser una capa
# delgada que la invoque. Si la logica se cablea aqui, el adaptador de GCP
# queda sin equivalente.
# ---------------------------------------------------------------------------

data "aws_region" "current" {}
data "aws_partition" "current" {}

locals {
  name      = "og-${var.env}"
  partition = data.aws_partition.current.partition
  region    = data.aws_region.current.name
}

resource "aws_api_gateway_rest_api" "this" {
  name        = "${local.name}-api"
  description = "API del middleware de onboarding y eKYC (${var.env})."

  endpoint_configuration {
    types = var.endpoint_type == "PRIVATE" ? ["PRIVATE"] : [var.endpoint_type]
  }

  # Las imagenes no pasan por el gateway: se suben con URL prefirmada a S3.
  # Este limite existe solo para payloads JSON de metadatos.
  minimum_compression_size = 1024

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Autorizador
# ---------------------------------------------------------------------------

resource "aws_iam_role" "authorizer_invocation" {
  name = "${local.name}-apigw-authorizer"

  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "sts:AssumeRole"
        Principal = { Service = "apigateway.amazonaws.com" }
      }
    ]
  })

  tags = var.tags
}

resource "aws_iam_role_policy" "authorizer_invocation" {
  name = "${local.name}-apigw-authorizer-policy"
  role = aws_iam_role.authorizer_invocation.id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["lambda:InvokeFunction"]
        Resource = [var.authorizer_function_arn]
      }
    ]
  })
}

resource "aws_api_gateway_authorizer" "tenant" {
  name        = "${local.name}-tenant-authorizer"
  rest_api_id = aws_api_gateway_rest_api.this.id
  type        = "REQUEST"

  authorizer_uri         = "arn:${local.partition}:apigateway:${local.region}:lambda:path/2015-03-31/functions/${var.authorizer_function_arn}/invocations"
  authorizer_credentials = aws_iam_role.authorizer_invocation.arn
  identity_source        = "method.request.header.Authorization"

  # La cache del autorizador ahorra invocaciones, pero retrasa la revocacion:
  # un token revocado sigue siendo aceptado hasta que expire la entrada. En eKYC
  # conviene un TTL corto. Cero desactiva la cache.
  authorizer_result_ttl_in_seconds = var.authorizer_cache_ttl_seconds
}

# ---------------------------------------------------------------------------
# Recurso: POST /v1/onboarding/cases -> StartExecution
# ---------------------------------------------------------------------------

resource "aws_api_gateway_resource" "v1" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_rest_api.this.root_resource_id
  path_part   = "v1"
}

resource "aws_api_gateway_resource" "onboarding" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "onboarding"
}

resource "aws_api_gateway_resource" "cases" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_resource.onboarding.id
  path_part   = "cases"
}

resource "aws_api_gateway_model" "start_case" {
  rest_api_id  = aws_api_gateway_rest_api.this.id
  name         = "StartCaseRequest"
  content_type = "application/json"

  schema = jsonencode({
    "$schema" = "http://json-schema.org/draft-04/schema#"
    title     = "StartCaseRequest"
    type      = "object"
    required  = ["countryCode", "documentType", "documentUri"]
    properties = {
      countryCode  = { type = "string", pattern = "^[A-Z]{2}$" }
      documentType = { type = "string" }
      documentUri  = { type = "string" }
      selfieUri    = { type = "string" }
      callbackUrl  = { type = "string" }
    }
    # El tenant no se acepta en el cuerpo: se toma del autorizador.
    additionalProperties = false
  })
}

resource "aws_api_gateway_request_validator" "body" {
  name                        = "${local.name}-validate-body"
  rest_api_id                 = aws_api_gateway_rest_api.this.id
  validate_request_body       = true
  validate_request_parameters = true
}

resource "aws_api_gateway_method" "start_case" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  resource_id   = aws_api_gateway_resource.cases.id
  http_method   = "POST"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.tenant.id

  api_key_required     = true # habilita el throttling por usage plan de tenant
  request_validator_id = aws_api_gateway_request_validator.body.id

  request_models = {
    "application/json" = aws_api_gateway_model.start_case.name
  }
}

resource "aws_api_gateway_integration" "start_case" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.cases.id
  http_method = aws_api_gateway_method.start_case.http_method

  type                    = "AWS"
  integration_http_method = "POST"
  uri                     = "arn:${local.partition}:apigateway:${local.region}:states:action/StartExecution"
  credentials             = var.start_execution_role_arn
  passthrough_behavior    = "NEVER"

  request_templates = {
    "application/json" = var.start_execution_request_template
  }
}

resource "aws_api_gateway_method_response" "start_case_202" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.cases.id
  http_method = aws_api_gateway_method.start_case.http_method
  status_code = "202"
}

resource "aws_api_gateway_integration_response" "start_case_202" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.cases.id
  http_method = aws_api_gateway_method.start_case.http_method
  status_code = aws_api_gateway_method_response.start_case_202.status_code

  # Se devuelve el identificador de ejecucion, no el estado interno.
  response_templates = {
    "application/json" = <<-VTL
      #set($body = $input.path('$'))
      {
        "caseId": "$context.requestId",
        "status": "ACCEPTED",
        "startedAt": "$body.startDate"
      }
    VTL
  }

  depends_on = [aws_api_gateway_integration.start_case]
}

# ---------------------------------------------------------------------------
# Recurso: ANY /v1/{proxy+} -> Lambda de consulta y administracion
# ---------------------------------------------------------------------------

resource "aws_api_gateway_resource" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  parent_id   = aws_api_gateway_resource.v1.id
  path_part   = "{proxy+}"
}

resource "aws_api_gateway_method" "proxy" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  resource_id   = aws_api_gateway_resource.proxy.id
  http_method   = "ANY"
  authorization = "CUSTOM"
  authorizer_id = aws_api_gateway_authorizer.tenant.id

  api_key_required = true

  request_parameters = {
    "method.request.path.proxy" = true
  }
}

resource "aws_api_gateway_integration" "proxy" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  resource_id = aws_api_gateway_resource.proxy.id
  http_method = aws_api_gateway_method.proxy.http_method

  type                    = "AWS_PROXY"
  integration_http_method = "POST"
  uri                     = var.api_function_invoke_arn
}

resource "aws_lambda_permission" "api" {
  statement_id  = "AllowApiGatewayInvokeApiFunction"
  action        = "lambda:InvokeFunction"
  function_name = var.api_function_arn
  principal     = "apigateway.amazonaws.com"
  source_arn    = "${aws_api_gateway_rest_api.this.execution_arn}/*/*"
}

# ---------------------------------------------------------------------------
# Despliegue y etapa
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "access" {
  name              = "/aws/apigateway/${local.name}-api/access"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.log_kms_key_arn

  tags = var.tags
}

resource "aws_api_gateway_deployment" "this" {
  rest_api_id = aws_api_gateway_rest_api.this.id

  # Fuerza un despliegue nuevo cuando cambia cualquier pieza de la definicion.
  triggers = {
    redeployment = sha1(jsonencode([
      aws_api_gateway_method.start_case,
      aws_api_gateway_integration.start_case,
      aws_api_gateway_method.proxy,
      aws_api_gateway_integration.proxy,
      aws_api_gateway_authorizer.tenant,
    ]))
  }

  lifecycle {
    create_before_destroy = true
  }
}

resource "aws_api_gateway_stage" "this" {
  rest_api_id   = aws_api_gateway_rest_api.this.id
  deployment_id = aws_api_gateway_deployment.this.id
  stage_name    = var.stage_name

  xray_tracing_enabled = var.enable_xray

  access_log_settings {
    destination_arn = aws_cloudwatch_log_group.access.arn

    # El tenant se registra en cada peticion: la tenancy debe ser observable en
    # todo log, metrica y traza de auditoria.
    format = jsonencode({
      requestId          = "$context.requestId"
      tenantId           = "$context.authorizer.tenantId"
      ip                 = "$context.identity.sourceIp"
      requestTime        = "$context.requestTime"
      httpMethod         = "$context.httpMethod"
      resourcePath       = "$context.resourcePath"
      status             = "$context.status"
      protocol           = "$context.protocol"
      responseLength     = "$context.responseLength"
      integrationLatency = "$context.integrationLatency"
      apiKeyId           = "$context.identity.apiKeyId"
    })
  }

  tags = var.tags
}

resource "aws_api_gateway_method_settings" "all" {
  rest_api_id = aws_api_gateway_rest_api.this.id
  stage_name  = aws_api_gateway_stage.this.stage_name
  method_path = "*/*"

  settings {
    metrics_enabled        = true
    logging_level          = var.execution_log_level
    data_trace_enabled     = false # volcaria cuerpos con PII a CloudWatch
    throttling_rate_limit  = var.stage_throttle_rate_limit
    throttling_burst_limit = var.stage_throttle_burst_limit
  }
}

# ---------------------------------------------------------------------------
# Planes de uso por tenant
#
# Un plan por tenant permite cuotas y throttling diferenciados por tier y evita
# que un tenant ruidoso consuma la capacidad de los demas.
# ---------------------------------------------------------------------------

resource "aws_api_gateway_api_key" "tenant" {
  for_each = var.tenant_usage_plans

  name        = "${local.name}-key-${each.key}"
  description = "Clave de API del tenant ${each.key}."
  enabled     = true

  tags = merge(var.tags, { "tenant-id" = each.key })
}

resource "aws_api_gateway_usage_plan" "tenant" {
  for_each = var.tenant_usage_plans

  name        = "${local.name}-plan-${each.key}"
  description = "Plan de uso del tenant ${each.key} (tier ${each.value.tier})."

  api_stages {
    api_id = aws_api_gateway_rest_api.this.id
    stage  = aws_api_gateway_stage.this.stage_name
  }

  throttle_settings {
    rate_limit  = each.value.rate_limit
    burst_limit = each.value.burst_limit
  }

  dynamic "quota_settings" {
    for_each = each.value.quota_limit == null ? [] : [1]
    content {
      limit  = each.value.quota_limit
      period = each.value.quota_period
    }
  }

  tags = merge(var.tags, { "tenant-id" = each.key })
}

resource "aws_api_gateway_usage_plan_key" "tenant" {
  for_each = var.tenant_usage_plans

  key_id        = aws_api_gateway_api_key.tenant[each.key].id
  key_type      = "API_KEY"
  usage_plan_id = aws_api_gateway_usage_plan.tenant[each.key].id
}

# ---------------------------------------------------------------------------
# WAF opcional
# ---------------------------------------------------------------------------

resource "aws_wafv2_web_acl" "this" {
  count = var.enable_waf ? 1 : 0

  name        = "${local.name}-api-waf"
  description = "Proteccion perimetral de la API de onboarding."
  scope       = "REGIONAL"

  default_action {
    allow {}
  }

  rule {
    name     = "AWSManagedRulesCommonRuleSet"
    priority = 1

    override_action {
      none {}
    }

    statement {
      managed_rule_group_statement {
        vendor_name = "AWS"
        name        = "AWSManagedRulesCommonRuleSet"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "CommonRuleSet"
      sampled_requests_enabled   = false # evita capturar cuerpos con PII
    }
  }

  rule {
    name     = "RateLimitPerIp"
    priority = 2

    action {
      block {}
    }

    statement {
      rate_based_statement {
        limit              = var.waf_rate_limit
        aggregate_key_type = "IP"
      }
    }

    visibility_config {
      cloudwatch_metrics_enabled = true
      metric_name                = "RateLimitPerIp"
      sampled_requests_enabled   = false
    }
  }

  visibility_config {
    cloudwatch_metrics_enabled = true
    metric_name                = "${local.name}-api-waf"
    sampled_requests_enabled   = false
  }

  tags = var.tags
}

resource "aws_wafv2_web_acl_association" "this" {
  count = var.enable_waf ? 1 : 0

  resource_arn = aws_api_gateway_stage.this.arn
  web_acl_arn  = aws_wafv2_web_acl.this[0].arn
}
