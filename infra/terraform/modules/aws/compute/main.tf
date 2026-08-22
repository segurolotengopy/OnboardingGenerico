# ---------------------------------------------------------------------------
# Computo serverless: funciones Lambda en dos formatos.
#
#   - zip      : logica de negocio ligera (resolucion de plan, scoring,
#                despacho de revision, purga). Arranque rapido, artefacto
#                pequeno.
#   - contenedor: inferencia (ONNX de calidad de imagen, embeddings faciales,
#                preprocesado con OpenCV). Imagen de hasta 10 GB
#                descomprimida.
#
# DIMENSIONADO DE MEMORIA
# -----------------------
# El rango real de Lambda es 128 MB - 10.240 MB en incrementos de 1 MB. No
# existe ningun requisito de memoria ligado a extensiones vectoriales: la
# documentacion de Lambda cubre AVX2 y arm64 usa NEON. `inference_memory_mb`
# tiene un valor por defecto razonable, NO un valor recomendado: en Lambda la
# vCPU asignada es proporcional a la memoria, asi que el punto optimo de
# coste-latencia solo se encuentra PERFILANDO la funcion real con su modelo
# real. Empiece por el valor por defecto, mida, y ajuste.
# ---------------------------------------------------------------------------

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name      = "og-${var.env}"
  partition = data.aws_partition.current.partition

  # Variables de entorno comunes a todas las funciones. El limite agregado de
  # variables de entorno es 4 KB: no meta aqui configuracion voluminosa.
  common_environment = merge(
    {
      ENV                     = var.env
      LOG_LEVEL               = var.log_level
      POWERTOOLS_SERVICE_NAME = "onboarding-generico"
      CORE_TABLE_NAME         = var.core_table_name
      CAPABILITIES_TABLE_NAME = var.capabilities_table_name
      LOCKS_TABLE_NAME        = var.locks_table_name
      KEYSTORE_TABLE_NAME     = var.keystore_table_name == null ? "" : var.keystore_table_name
      DOCUMENTS_BUCKET        = var.documents_bucket_name
      BIOMETRICS_BUCKET       = var.biometrics_bucket_name
      STAGING_BUCKET          = var.staging_bucket_name
      EVIDENCE_BUCKET         = var.evidence_bucket_name
      PLATFORM_KMS_KEY_ARN    = var.platform_kms_key_arn
    },
    var.extra_environment,
  )
}

# ---------------------------------------------------------------------------
# Repositorios ECR para las funciones basadas en imagen
# ---------------------------------------------------------------------------

resource "aws_ecr_repository" "this" {
  for_each = var.container_functions

  name                 = "${local.name}/${each.key}"
  image_tag_mutability = "IMMUTABLE" # un tag nunca cambia de digest: reproducibilidad

  image_scanning_configuration {
    scan_on_push = true
  }

  encryption_configuration {
    encryption_type = "KMS"
    kms_key         = var.platform_kms_key_arn
  }

  tags = var.tags
}

resource "aws_ecr_lifecycle_policy" "this" {
  for_each = aws_ecr_repository.this

  repository = each.value.name

  policy = jsonencode({
    rules = [
      {
        rulePriority = 1
        description  = "Conservar solo las ultimas imagenes etiquetadas para release"
        selection = {
          tagStatus     = "tagged"
          tagPrefixList = ["v"]
          countType     = "imageCountMoreThan"
          countNumber   = var.ecr_retained_image_count
        }
        action = { type = "expire" }
      },
      {
        rulePriority = 2
        description  = "Purgar imagenes sin etiqueta a los 7 dias"
        selection = {
          tagStatus   = "untagged"
          countType   = "sinceImagePushed"
          countUnit   = "days"
          countNumber = 7
        }
        action = { type = "expire" }
      },
    ]
  })
}

# ---------------------------------------------------------------------------
# Capa compartida (solo para funciones zip)
# ---------------------------------------------------------------------------

resource "aws_lambda_layer_version" "shared" {
  count = var.shared_layer_s3_key == null ? 0 : 1

  layer_name          = "${local.name}-shared"
  description         = "Nucleo hexagonal compartido: dominio, puertos y utilidades de cifrado de sobre."
  s3_bucket           = var.artifacts_bucket_name
  s3_key              = var.shared_layer_s3_key
  compatible_runtimes = [var.python_runtime]

  compatible_architectures = [var.zip_architecture]
}

# ---------------------------------------------------------------------------
# Rol de ejecucion compartido
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "lambda_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["lambda.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "execution" {
  name               = "${local.name}-lambda-execution"
  description        = "Rol de ejecucion de las funciones del middleware. NO lleva scoping de tenant: el aislamiento lo aplica el rol tenant-scoped que la funcion asume por peticion."
  assume_role_policy = data.aws_iam_policy_document.lambda_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy_attachment" "basic" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}

resource "aws_iam_role_policy_attachment" "vpc" {
  count = var.vpc_config == null ? 0 : 1

  role       = aws_iam_role.execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/service-role/AWSLambdaVPCAccessExecutionRole"
}

resource "aws_iam_role_policy_attachment" "xray" {
  role       = aws_iam_role.execution.name
  policy_arn = "arn:${local.partition}:iam::aws:policy/AWSXRayDaemonWriteAccess"
}

data "aws_iam_policy_document" "execution" {
  # La funcion no lee datos de tenant con su propio rol: asume el rol
  # tenant-scoped por peticion. Esta sentencia es la unica puerta a ese rol.
  dynamic "statement" {
    for_each = var.tenant_scoped_role_arn == null ? [] : [1]
    content {
      sid       = "AssumeTenantScopedRole"
      effect    = "Allow"
      actions   = ["sts:AssumeRole", "sts:TagSession"]
      resources = [var.tenant_scoped_role_arn]
    }
  }

  statement {
    sid    = "PlatformCatalogAccess"
    effect = "Allow"
    actions = [
      "dynamodb:GetItem",
      "dynamodb:Query",
    ]
    resources = [
      var.capabilities_table_arn,
      "${var.capabilities_table_arn}/index/*",
    ]
  }

  statement {
    sid    = "DistributedLock"
    effect = "Allow"
    actions = [
      "dynamodb:PutItem",
      "dynamodb:GetItem",
      "dynamodb:UpdateItem",
      "dynamodb:DeleteItem",
    ]
    resources = [var.locks_table_arn]
  }

  dynamic "statement" {
    for_each = var.keystore_table_arn == null ? [] : [1]
    content {
      sid    = "HierarchicalKeyringBranchKeys"
      effect = "Allow"
      actions = [
        "dynamodb:GetItem",
        "dynamodb:Query",
        "dynamodb:PutItem",
      ]
      resources = [var.keystore_table_arn]
    }
  }

  statement {
    sid       = "ReportTaskOutcome"
    effect    = "Allow"
    actions   = ["states:SendTaskSuccess", "states:SendTaskFailure", "states:SendTaskHeartbeat"]
    resources = ["*"] # las acciones de task token no admiten ARN de recurso
  }

  statement {
    sid       = "ReadSecrets"
    effect    = "Allow"
    actions   = ["secretsmanager:GetSecretValue"]
    resources = var.readable_secret_arns
  }

  statement {
    sid       = "PlatformKeyUsage"
    effect    = "Allow"
    actions   = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"]
    resources = [var.platform_kms_key_arn]
  }

  statement {
    sid    = "StagingObjects"
    effect = "Allow"
    actions = [
      "s3:GetObject",
      "s3:PutObject",
      "s3:DeleteObject",
    ]
    resources = ["${var.staging_bucket_arn}/*"]
  }

  # La evidencia se escribe una vez y no se borra: WORM. Sin DeleteObject.
  statement {
    sid       = "WriteAuditEvidence"
    effect    = "Allow"
    actions   = ["s3:PutObject", "s3:PutObjectRetention", "s3:GetObject"]
    resources = ["${var.evidence_bucket_arn}/*"]
  }
}

resource "aws_iam_role_policy" "execution" {
  name   = "${local.name}-lambda-execution-policy"
  role   = aws_iam_role.execution.id
  policy = data.aws_iam_policy_document.execution.json
}

# ---------------------------------------------------------------------------
# Log groups: se crean explicitamente para controlar retencion y cifrado.
# Si se deja que Lambda los cree, quedan con retencion indefinida.
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "functions" {
  for_each = merge(var.zip_functions, var.container_functions)

  name              = "/aws/lambda/${local.name}-${each.key}"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.log_kms_key_arn

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Funciones empaquetadas como zip
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "zip" {
  # checkov:skip=CKV_AWS_116:Estas funciones se invocan de forma sincrona, desde la
  # integracion de API Gateway y desde `arn:aws:states:::lambda:invoke`.
  # `dead_letter_config` solo actua en invocaciones asincronas, asi que la cola
  # nunca recibiria nada; los fallos los maneja el `Catch` de la maquina de estados.
  # CKV_AWS_272 (firma de codigo) NO se suprime: es un hallazgo real, ver issue #14.
  for_each = var.zip_functions

  function_name = "${local.name}-${each.key}"
  description   = each.value.description
  role          = aws_iam_role.execution.arn

  s3_bucket = var.artifacts_bucket_name
  s3_key    = each.value.s3_key

  handler       = each.value.handler
  runtime       = var.python_runtime
  architectures = [var.zip_architecture]

  # Publicar version es requisito de los alias y de la concurrencia
  # aprovisionada: no se puede fijar sobre $LATEST.
  publish = true

  memory_size = each.value.memory_mb
  timeout     = each.value.timeout_seconds

  # Concurrencia reservada: acota el gasto de una funcion y, mas importante,
  # impide que un pico en un paso agote la concurrencia de toda la cuenta.
  # -1 significa sin reserva.
  reserved_concurrent_executions = each.value.reserved_concurrency

  layers = var.shared_layer_s3_key == null ? [] : [aws_lambda_layer_version.shared[0].arn]

  environment {
    variables = merge(local.common_environment, each.value.environment)
  }

  dynamic "vpc_config" {
    for_each = each.value.in_vpc && var.vpc_config != null ? [var.vpc_config] : []
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }

  tracing_config {
    mode = var.enable_xray ? "Active" : "PassThrough"
  }

  kms_key_arn = var.platform_kms_key_arn

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.functions]
}

# ---------------------------------------------------------------------------
# Funciones empaquetadas como imagen de contenedor
# ---------------------------------------------------------------------------

resource "aws_lambda_function" "container" {
  # checkov:skip=CKV_AWS_116:Estas funciones se invocan de forma sincrona, desde la
  # integracion de API Gateway y desde `arn:aws:states:::lambda:invoke`.
  # `dead_letter_config` solo actua en invocaciones asincronas, asi que la cola
  # nunca recibiria nada; los fallos los maneja el `Catch` de la maquina de estados.
  # CKV_AWS_272 (firma de codigo) NO se suprime: es un hallazgo real, ver issue #14.
  for_each = var.container_functions

  function_name = "${local.name}-${each.key}"
  description   = each.value.description
  role          = aws_iam_role.execution.arn

  package_type = "Image"
  image_uri    = "${aws_ecr_repository.this[each.key].repository_url}:${each.value.image_tag}"

  # x86_64 explicito cuando la inferencia depende de AVX2. arm64 usa NEON y
  # suele salir mas barato, pero exige recompilar las dependencias nativas.
  architectures = [each.value.architecture]

  publish = true

  # Valor de partida, no recomendacion: perfile la funcion real. La vCPU
  # asignada es proporcional a la memoria.
  memory_size = coalesce(each.value.memory_mb, var.inference_memory_mb)
  timeout     = each.value.timeout_seconds

  reserved_concurrent_executions = each.value.reserved_concurrency

  # /tmp es disco real en Lambda, no tmpfs: no descuenta de la memoria.
  ephemeral_storage {
    size = each.value.ephemeral_storage_mb
  }

  environment {
    variables = merge(local.common_environment, each.value.environment)
  }

  dynamic "vpc_config" {
    for_each = each.value.in_vpc && var.vpc_config != null ? [var.vpc_config] : []
    content {
      subnet_ids         = vpc_config.value.subnet_ids
      security_group_ids = vpc_config.value.security_group_ids
    }
  }

  tracing_config {
    mode = var.enable_xray ? "Active" : "PassThrough"
  }

  kms_key_arn = var.platform_kms_key_arn

  tags = var.tags

  depends_on = [aws_cloudwatch_log_group.functions]
}

# ---------------------------------------------------------------------------
# Alias y concurrencia aprovisionada
#
# La concurrencia aprovisionada solo puede fijarse sobre un alias o una version
# publicada, nunca sobre $LATEST. Se factura de forma continua, este o no
# atendiendo peticiones: en dev suele valer cero.
# ---------------------------------------------------------------------------

resource "aws_lambda_alias" "live" {
  for_each = merge(
    { for k, v in var.zip_functions : k => v if v.provisioned_concurrency > 0 },
    { for k, v in var.container_functions : k => v if v.provisioned_concurrency > 0 },
  )

  name             = "live"
  function_name    = try(aws_lambda_function.zip[each.key].function_name, aws_lambda_function.container[each.key].function_name)
  function_version = try(aws_lambda_function.zip[each.key].version, aws_lambda_function.container[each.key].version)
}

resource "aws_lambda_provisioned_concurrency_config" "live" {
  for_each = aws_lambda_alias.live

  function_name = each.value.function_name
  qualifier     = each.value.name
  provisioned_concurrent_executions = try(
    var.zip_functions[each.key].provisioned_concurrency,
    var.container_functions[each.key].provisioned_concurrency,
  )
}
