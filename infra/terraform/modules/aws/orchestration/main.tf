# ---------------------------------------------------------------------------
# Orquestacion hibrida: Standard padre + Express hijos anidados.
#
# POR QUE HIBRIDA
# ---------------
# El flujo de onboarding necesita esperas largas (revision manual, respuesta de
# un proveedor externo) y semantica exactly-once sobre acciones no idempotentes
# (crear la cuenta, notificar al buro). Eso obliga a Standard en el orquestador.
# Los pasos automatizados de alto volumen (OCR, biometria) caben de sobra en los
# 5 minutos de Express y son idempotentes, asi que van en hijos Express.
#
# El ahorro del patron anidado depende del numero de transiciones y de la
# duracion media: NO existe un porcentaje universal. Calculelo con las
# transiciones reales de su flujo antes de citarlo en ningun documento.
#
# LIMITES QUE CONDICIONAN EL DISENO
# ---------------------------------
#   - Payload de entrada/salida: 256 KiB. Por eso el estado solo transporta
#     PUNTEROS s3:// y nunca imagenes ni respuestas de OCR completas.
#   - Historial de Standard: 25.000 eventos por ejecucion. Un bucle sobre N
#     documentos con reintentos lo agota; si eso ocurre, encadene ejecuciones
#     nuevas en lugar de alargar la misma.
#   - Duracion maxima de Standard: 1 anio. Express: 5 minutos.
#   - Express NO soporta .waitForTaskToken, .sync ni Distributed Map. Cualquier
#     integracion con revision humana vive en el padre.
#   - Express es at-least-once: todo Task invocado desde un hijo Express debe
#     ser idempotente (clave de idempotencia derivada de caseId + stepId).
# ---------------------------------------------------------------------------

data "aws_region" "current" {}
data "aws_caller_identity" "current" {}
data "aws_partition" "current" {}

locals {
  name      = "og-${var.env}"
  partition = data.aws_partition.current.partition
  region    = data.aws_region.current.name
  account   = data.aws_caller_identity.current.account_id

  # -------------------------------------------------------------------------
  # Hijo Express: extraccion documental (OCR + LLM multimodal)
  # -------------------------------------------------------------------------
  ocr_definition = {
    Comment       = "Extraccion documental: OCR generico mas extraccion estructurada por LLM. Solo punteros S3 en el estado."
    QueryLanguage = "JSONPath"
    StartAt       = "PreprocessImage"
    States        = {
      PreprocessImage = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.preprocess_function_arn
          Payload      = {
            "tenantId.$"     = "$.tenantId"
            "caseId.$"       = "$.caseId"
            "documentUri.$"  = "$.documentUri"
            "idempotencyKey.$" = "States.Format('{}#{}#preprocess', $.caseId, $.documentId)"
          }
        }
        # ResultSelector recorta la respuesta de Lambda para no arrastrar
        # metadatos innecesarios hacia el limite de 256 KiB.
        ResultSelector = {
          "normalizedUri.$" = "$.Payload.normalizedUri"
          "quality.$"       = "$.Payload.quality"
        }
        ResultPath = "$.preprocess"
        Retry      = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException", "Lambda.SdkClientException"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "ExtractionFailed"
          }
        ]
        Next = "RunOcr"
      }

      RunOcr = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.ocr_function_arn
          Payload      = {
            "tenantId.$"    = "$.tenantId"
            "caseId.$"      = "$.caseId"
            "imageUri.$"    = "$.preprocess.normalizedUri"
            "countryCode.$" = "$.countryCode"
            "documentType.$" = "$.documentType"
          }
        }
        ResultSelector = {
          "ocrResultUri.$" = "$.Payload.ocrResultUri"
          "confidence.$"   = "$.Payload.confidence"
        }
        ResultPath = "$.ocr"
        Retry      = [
          {
            ErrorEquals     = ["States.TaskFailed"]
            IntervalSeconds = 2
            MaxAttempts     = 2
            BackoffRate     = 2
          }
        ]
        Catch = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "ExtractionFailed"
          }
        ]
        Next = "StructureFields"
      }

      # Los procesadores gestionados de documentos de identidad cubren
      # esencialmente EE. UU. Para LATAM el patron portable es OCR generico mas
      # un LLM multimodal con prompt por pais y tipo de documento.
      StructureFields = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.field_extraction_function_arn
          Payload      = {
            "tenantId.$"     = "$.tenantId"
            "caseId.$"       = "$.caseId"
            "ocrResultUri.$" = "$.ocr.ocrResultUri"
            "countryCode.$"  = "$.countryCode"
            "documentType.$" = "$.documentType"
          }
        }
        ResultSelector = {
          "fieldsUri.$"   = "$.Payload.fieldsUri"
          "mrzValid.$"    = "$.Payload.mrzValid"
          "fieldScore.$"  = "$.Payload.fieldScore"
        }
        ResultPath = "$.extraction"
        End        = true
      }

      ExtractionFailed = {
        Type  = "Fail"
        Error = "ExtractionFailed"
        Cause = "No fue posible extraer los campos del documento."
      }
    }
  }

  # -------------------------------------------------------------------------
  # Hijo Express: biometria (face match + liveness)
  # -------------------------------------------------------------------------
  biometrics_definition = {
    Comment       = "Comparacion facial y vivacidad. El proveedor de liveness es intercambiable por el Registro de Capacidades."
    QueryLanguage = "JSONPath"
    StartAt       = "ParallelChecks"
    States        = {
      ParallelChecks = {
        Type     = "Parallel"
        Branches = [
          {
            StartAt = "FaceMatch"
            States  = {
              FaceMatch = {
                Type       = "Task"
                Resource   = "arn:${local.partition}:states:::lambda:invoke"
                Parameters = {
                  FunctionName = var.face_match_function_arn
                  Payload      = {
                    "tenantId.$"     = "$.tenantId"
                    "caseId.$"       = "$.caseId"
                    "portraitUri.$"  = "$.portraitUri"
                    "selfieUri.$"    = "$.selfieUri"
                  }
                }
                ResultSelector = {
                  "similarity.$" = "$.Payload.similarity"
                  "matched.$"    = "$.Payload.matched"
                }
                Retry = [
                  {
                    ErrorEquals     = ["States.TaskFailed"]
                    IntervalSeconds = 2
                    MaxAttempts     = 2
                    BackoffRate     = 2
                  }
                ]
                End = true
              }
            }
          },
          {
            StartAt = "Liveness"
            States  = {
              Liveness = {
                Type       = "Task"
                Resource   = "arn:${local.partition}:states:::lambda:invoke"
                Parameters = {
                  FunctionName = var.liveness_function_arn
                  Payload      = {
                    "tenantId.$"        = "$.tenantId"
                    "caseId.$"          = "$.caseId"
                    "livenessSessionId.$" = "$.livenessSessionId"
                  }
                }
                ResultSelector = {
                  "livenessScore.$" = "$.Payload.livenessScore"
                  "passed.$"        = "$.Payload.passed"
                }
                Retry = [
                  {
                    ErrorEquals     = ["States.TaskFailed"]
                    IntervalSeconds = 2
                    MaxAttempts     = 2
                    BackoffRate     = 2
                  }
                ]
                End = true
              }
            }
          },
        ]
        ResultSelector = {
          "faceMatch.$" = "$.[0]"
          "liveness.$"  = "$.[1]"
        }
        End = true
      }
    }
  }

  # -------------------------------------------------------------------------
  # Padre Standard
  # -------------------------------------------------------------------------
  parent_definition = {
    Comment        = "Saga de onboarding. Compone los pasos segun el Registro de Capacidades y espera la decision humana con waitForTaskToken."
    QueryLanguage  = "JSONPath"
    StartAt        = "ResolveCapabilityPlan"
    TimeoutSeconds = var.parent_timeout_seconds
    States         = {
      # El plan de pasos NO esta cableado en la ASL: se resuelve en tiempo de
      # ejecucion contra el Registro de Capacidades segun tenant, pais y tipo de
      # documento.
      ResolveCapabilityPlan = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.plan_resolver_function_arn
          Payload      = {
            "tenantId.$"     = "$.tenantId"
            "caseId.$"       = "$.caseId"
            "countryCode.$"  = "$.countryCode"
            "documentType.$" = "$.documentType"
          }
        }
        ResultSelector = {
          "steps.$"           = "$.Payload.steps"
          "requiresBiometry.$" = "$.Payload.requiresBiometry"
          "riskThreshold.$"   = "$.Payload.riskThreshold"
        }
        ResultPath = "$.plan"
        Retry      = [
          {
            ErrorEquals     = ["Lambda.ServiceException", "Lambda.TooManyRequestsException"]
            IntervalSeconds = 1
            MaxAttempts     = 3
            BackoffRate     = 2
          }
        ]
        Next = "RunAutomatedChecks"
      }

      # Los dos hijos Express corren en paralelo. Arrancar un workflow anidado
      # no consume transicion facturada adicional.
      RunAutomatedChecks = {
        Type     = "Parallel"
        Branches = [
          {
            StartAt = "InvokeExtraction"
            States  = {
              InvokeExtraction = {
                Type       = "Task"
                Resource   = "arn:${local.partition}:states:::states:startExecution.sync:2"
                Parameters = {
                  StateMachineArn = aws_sfn_state_machine.ocr_express.arn
                  Input           = {
                    "tenantId.$"     = "$.tenantId"
                    "caseId.$"       = "$.caseId"
                    "documentId.$"   = "$.documentId"
                    "documentUri.$"  = "$.documentUri"
                    "countryCode.$"  = "$.countryCode"
                    "documentType.$" = "$.documentType"
                    "AWS_STEP_FUNCTIONS_STARTED_BY_EXECUTION_ID.$" = "$$.Execution.Id"
                  }
                }
                # .sync:2 devuelve Output ya deserializado.
                ResultSelector = {
                  "extraction.$" = "$.Output.extraction"
                  "ocr.$"        = "$.Output.ocr"
                }
                Retry = [
                  {
                    ErrorEquals     = ["States.TaskFailed"]
                    IntervalSeconds = 5
                    MaxAttempts     = 2
                    BackoffRate     = 2
                  }
                ]
                End = true
              }
            }
          },
          {
            StartAt = "BiometryRequired"
            States  = {
              BiometryRequired = {
                Type    = "Choice"
                Choices = [
                  {
                    Variable      = "$.plan.requiresBiometry"
                    BooleanEquals = true
                    Next          = "InvokeBiometrics"
                  }
                ]
                Default = "BiometrySkipped"
              }

              InvokeBiometrics = {
                Type       = "Task"
                Resource   = "arn:${local.partition}:states:::states:startExecution.sync:2"
                Parameters = {
                  StateMachineArn = aws_sfn_state_machine.biometrics_express.arn
                  Input           = {
                    "tenantId.$"          = "$.tenantId"
                    "caseId.$"            = "$.caseId"
                    "portraitUri.$"       = "$.portraitUri"
                    "selfieUri.$"         = "$.selfieUri"
                    "livenessSessionId.$" = "$.livenessSessionId"
                    "AWS_STEP_FUNCTIONS_STARTED_BY_EXECUTION_ID.$" = "$$.Execution.Id"
                  }
                }
                ResultSelector = {
                  "biometrics.$" = "$.Output"
                }
                End = true
              }

              BiometrySkipped = {
                Type   = "Pass"
                Result = { biometrics = null }
                End    = true
              }
            }
          },
        ]
        ResultPath = "$.checks"
        Catch      = [
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "RecordFailure"
          }
        ]
        Next = "ScoreRisk"
      }

      ScoreRisk = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.risk_scoring_function_arn
          Payload      = {
            "tenantId.$" = "$.tenantId"
            "caseId.$"   = "$.caseId"
            "checks.$"   = "$.checks"
            "plan.$"     = "$.plan"
          }
        }
        ResultSelector = {
          "score.$"    = "$.Payload.score"
          "decision.$" = "$.Payload.decision"
          "reasons.$"  = "$.Payload.reasons"
        }
        ResultPath = "$.risk"
        Next       = "NeedsManualReview"
      }

      NeedsManualReview = {
        Type    = "Choice"
        Choices = [
          {
            Variable     = "$.risk.decision"
            StringEquals = "AUTO_APPROVE"
            Next         = "RecordApproval"
          },
          {
            Variable     = "$.risk.decision"
            StringEquals = "AUTO_REJECT"
            Next         = "RecordRejection"
          }
        ]
        Default = "AwaitHumanDecision"
      }

      # Revision humana con callback. El tiempo de espera NO se factura: solo se
      # paga la transicion. La tarea publica el caso en la cola de revision junto
      # con el task token y se queda esperando SendTaskSuccess/SendTaskFailure.
      AwaitHumanDecision = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke.waitForTaskToken"
        Parameters = {
          FunctionName = var.human_review_dispatch_function_arn
          Payload      = {
            "tenantId.$"  = "$.tenantId"
            "caseId.$"    = "$.caseId"
            "risk.$"      = "$.risk"
            "checks.$"    = "$.checks"
            "taskToken.$" = "$$.Task.Token"
          }
        }
        # Cubre fin de semana y escalado a compliance sin agotar el plazo.
        TimeoutSeconds   = var.human_review_timeout_seconds
        HeartbeatSeconds = var.human_review_heartbeat_seconds
        ResultPath       = "$.humanDecision"
        Catch            = [
          {
            ErrorEquals = ["States.Timeout"]
            ResultPath  = "$.error"
            Next        = "EscalateExpiredReview"
          },
          {
            ErrorEquals = ["States.ALL"]
            ResultPath  = "$.error"
            Next        = "RecordFailure"
          }
        ]
        Next = "ApplyHumanDecision"
      }

      ApplyHumanDecision = {
        Type    = "Choice"
        Choices = [
          {
            Variable     = "$.humanDecision.outcome"
            StringEquals = "APPROVED"
            Next         = "RecordApproval"
          }
        ]
        Default = "RecordRejection"
      }

      EscalateExpiredReview = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::events:putEvents"
        Parameters = {
          Entries = [
            {
              EventBusName = var.event_bus_name
              Source       = "onboarding.saga"
              DetailType   = "ManualReviewExpired"
              Detail       = {
                "tenantId.$" = "$.tenantId"
                "caseId.$"   = "$.caseId"
              }
            }
          ]
        }
        ResultPath = null
        Next       = "RecordFailure"
      }

      # La escritura de evidencia es la accion no idempotente que justifica
      # Standard: se ejecuta exactamente una vez.
      RecordApproval = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.decision_recorder_function_arn
          Payload      = {
            "tenantId.$" = "$.tenantId"
            "caseId.$"   = "$.caseId"
            outcome = "APPROVED"
            "risk.$"     = "$.risk"
          }
        }
        ResultPath = "$.record"
        End        = true
      }

      RecordRejection = {
        Type       = "Task"
        Resource   = "arn:${local.partition}:states:::lambda:invoke"
        Parameters = {
          FunctionName = var.decision_recorder_function_arn
          Payload      = {
            "tenantId.$" = "$.tenantId"
            "caseId.$"   = "$.caseId"
            outcome = "REJECTED"
            "risk.$"     = "$.risk"
          }
        }
        ResultPath = "$.record"
        End        = true
      }

      RecordFailure = {
        Type  = "Fail"
        Error = "OnboardingSagaFailed"
        Cause = "La saga de onboarding termino en error. Revise el detalle en $.error."
      }
    }
  }

  # Plantilla VTL de la integracion directa API Gateway -> StartExecution.
  # Evita una Lambda intermedia: el gateway habla con Step Functions
  # directamente. El contexto del autorizador aporta el tenant, que NUNCA se
  # toma del cuerpo de la peticion.
  start_execution_request_template = <<-VTL
    #set($tenantId = $context.authorizer.tenantId)
    #set($caseId = $context.requestId)
    {
      "stateMachineArn": "${aws_sfn_state_machine.parent.arn}",
      "name": "$caseId",
      "input": "{\"tenantId\":\"$tenantId\",\"caseId\":\"$caseId\",\"requestBody\":$util.escapeJavaScript($input.json('$')).replaceAll("\\\\'","'")}"
    }
  VTL
}

# ---------------------------------------------------------------------------
# Log groups
# ---------------------------------------------------------------------------

resource "aws_cloudwatch_log_group" "parent" {
  name              = "/aws/vendedlogs/states/${local.name}-onboarding-saga"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.log_kms_key_arn

  tags = var.tags
}

# Los hijos Express NO tienen historial consultable: sin CloudWatch Logs no hay
# forma de inspeccionar que paso. Para trazabilidad KYC/AML esto no es opcional.
resource "aws_cloudwatch_log_group" "ocr_express" {
  name              = "/aws/vendedlogs/states/${local.name}-extraction-express"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.log_kms_key_arn

  tags = var.tags
}

resource "aws_cloudwatch_log_group" "biometrics_express" {
  name              = "/aws/vendedlogs/states/${local.name}-biometrics-express"
  retention_in_days = var.log_retention_days
  kms_key_id        = var.log_kms_key_arn

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Roles de ejecucion
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "sfn_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["states.amazonaws.com"]
    }

    condition {
      test     = "StringEquals"
      variable = "aws:SourceAccount"
      values   = [local.account]
    }
  }
}

resource "aws_iam_role" "express" {
  name               = "${local.name}-sfn-express"
  description        = "Rol de ejecucion de las maquinas de estado Express anidadas."
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = var.tags
}

resource "aws_iam_role" "parent" {
  name               = "${local.name}-sfn-parent"
  description        = "Rol de ejecucion de la maquina de estado Standard padre."
  assume_role_policy = data.aws_iam_policy_document.sfn_assume.json
  tags               = var.tags
}

data "aws_iam_policy_document" "express_permissions" {
  statement {
    sid       = "InvokeTaskFunctions"
    effect    = "Allow"
    actions   = ["lambda:InvokeFunction"]
    resources = var.invokable_function_arns
  }

  # La entrega de logs de Step Functions exige estos permisos sobre "*": el
  # servicio los evalua a nivel de cuenta, no de log group.
  statement {
    sid     = "DeliverLogs"
    effect  = "Allow"
    actions = [
      "logs:CreateLogDelivery",
      "logs:GetLogDelivery",
      "logs:UpdateLogDelivery",
      "logs:DeleteLogDelivery",
      "logs:ListLogDeliveries",
      "logs:PutResourcePolicy",
      "logs:DescribeResourcePolicies",
      "logs:DescribeLogGroups",
    ]
    resources = ["*"]
  }

  statement {
    sid       = "Tracing"
    effect    = "Allow"
    actions   = ["xray:PutTraceSegments", "xray:PutTelemetryRecords", "xray:GetSamplingRules", "xray:GetSamplingTargets"]
    resources = ["*"]
  }
}

data "aws_iam_policy_document" "parent_permissions" {
  source_policy_documents = [data.aws_iam_policy_document.express_permissions.json]

  statement {
    sid       = "StartNestedExpressExecutions"
    effect    = "Allow"
    actions   = ["states:StartExecution", "states:StartSyncExecution"]
    resources = [aws_sfn_state_machine.ocr_express.arn, aws_sfn_state_machine.biometrics_express.arn]
  }

  statement {
    sid       = "ManageNestedExecutions"
    effect    = "Allow"
    actions   = ["states:DescribeExecution", "states:StopExecution"]
    resources = ["arn:${local.partition}:states:${local.region}:${local.account}:execution:${local.name}-*"]
  }

  # El patron .sync se implementa internamente con una regla gestionada de
  # EventBridge. Sin estos permisos el estado se queda colgado sin error claro.
  statement {
    sid       = "SyncPatternEventBridgeRule"
    effect    = "Allow"
    actions   = ["events:PutTargets", "events:PutRule", "events:DescribeRule"]
    resources = ["arn:${local.partition}:events:${local.region}:${local.account}:rule/StepFunctionsGetEventsForStepFunctionsExecutionRule"]
  }

  statement {
    sid       = "PublishDomainEvents"
    effect    = "Allow"
    actions   = ["events:PutEvents"]
    resources = [var.event_bus_arn]
  }
}

resource "aws_iam_role_policy" "express" {
  name   = "${local.name}-sfn-express-policy"
  role   = aws_iam_role.express.id
  policy = data.aws_iam_policy_document.express_permissions.json
}

resource "aws_iam_role_policy" "parent" {
  name   = "${local.name}-sfn-parent-policy"
  role   = aws_iam_role.parent.id
  policy = data.aws_iam_policy_document.parent_permissions.json
}

# ---------------------------------------------------------------------------
# Maquinas de estado
# ---------------------------------------------------------------------------

resource "aws_sfn_state_machine" "ocr_express" {
  name     = "${local.name}-extraction-express"
  type     = "EXPRESS"
  role_arn = aws_iam_role.express.arn

  definition = jsonencode(local.ocr_definition)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.ocr_express.arn}:*"
    include_execution_data = var.include_execution_data
    level                  = var.log_level
  }

  tracing_configuration {
    enabled = var.enable_xray
  }

  tags = var.tags
}

resource "aws_sfn_state_machine" "biometrics_express" {
  name     = "${local.name}-biometrics-express"
  type     = "EXPRESS"
  role_arn = aws_iam_role.express.arn

  definition = jsonencode(local.biometrics_definition)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.biometrics_express.arn}:*"
    include_execution_data = var.include_execution_data
    level                  = var.log_level
  }

  tracing_configuration {
    enabled = var.enable_xray
  }

  tags = var.tags
}

resource "aws_sfn_state_machine" "parent" {
  name     = "${local.name}-onboarding-saga"
  type     = "STANDARD"
  role_arn = aws_iam_role.parent.arn

  definition = jsonencode(local.parent_definition)

  logging_configuration {
    log_destination        = "${aws_cloudwatch_log_group.parent.arn}:*"
    include_execution_data = var.include_execution_data
    level                  = var.log_level
  }

  tracing_configuration {
    enabled = var.enable_xray
  }

  tags = var.tags
}

# ---------------------------------------------------------------------------
# Rol que asume API Gateway para arrancar la saga sin Lambda intermedia
# ---------------------------------------------------------------------------

data "aws_iam_policy_document" "apigw_assume" {
  statement {
    effect  = "Allow"
    actions = ["sts:AssumeRole"]

    principals {
      type        = "Service"
      identifiers = ["apigateway.amazonaws.com"]
    }
  }
}

resource "aws_iam_role" "apigw_start_execution" {
  name               = "${local.name}-apigw-start-execution"
  description        = "Rol que usa API Gateway para llamar a StartExecution sin Lambda intermedia."
  assume_role_policy = data.aws_iam_policy_document.apigw_assume.json
  tags               = var.tags
}

resource "aws_iam_role_policy" "apigw_start_execution" {
  name = "${local.name}-apigw-start-execution-policy"
  role = aws_iam_role.apigw_start_execution.id

  policy = jsonencode({
    Version   = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = ["states:StartExecution"]
        Resource = [aws_sfn_state_machine.parent.arn]
      }
    ]
  })
}
