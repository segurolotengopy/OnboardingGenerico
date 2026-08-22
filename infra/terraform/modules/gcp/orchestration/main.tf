# ---------------------------------------------------------------------------
# Orquestacion en GCP.
#
# NO ES UN PORTE MECANICO DE STEP FUNCTIONS.
#
#   - Cloud Workflows tiene un unico tier: no existe la distincion
#     Standard/Express. El equivalente a los hijos Express de baja latencia se
#     construye con Cloud Tasks (cola con reintentos y despacho HTTP) y
#     Pub/Sub + Eventarc.
#   - El lenguaje es YAML con expresiones CEL, no ASL. La traduccion no es
#     mecanica: prevea reescribir el orquestador, no portarlo.
#   - No hay intrinsic functions ni catalogo de integraciones optimizadas de
#     SDK. Todo se hace con http.post o conectores.
#   - No hay Distributed Map. Para fan-out masivo se usan jobs de Cloud Run con
#     task_count.
#
# LIMITE QUE MANDA SOBRE TODO EL DISENO
# -------------------------------------
# Cloud Workflows acumula un maximo de 512 KB de datos POR EJECUCION (variables
# mas argumentos mas eventos). No es por paso: es acumulado. Step Functions
# permite 256 KiB por payload sin acumulado. Por eso el workflow de este modulo
# transporta EXCLUSIVAMENTE punteros gs:// y nunca resultados de OCR.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"

  # El codigo fuente del workflow tiene un tope de 128 KB y las expresiones un
  # tope de 400 caracteres, lo que obliga a partir la logica en pasos `assign`.
  workflow_source = yamlencode({
    main = {
      params = ["args"]
      steps  = [
        {
          init = {
            assign = [
              { tenantId = "$${args.tenantId}" },
              { caseId = "$${args.caseId}" },
              { documentUri = "$${args.documentUri}" },
              { countryCode = "$${args.countryCode}" },
              { documentType = "$${args.documentType}" },
            ]
          }
        },
        {
          # El plan de pasos se resuelve en tiempo de ejecucion contra el
          # Registro de Capacidades. Solo se devuelve el plan, nunca datos.
          resolve_plan = {
            call = "http.post"
            args = {
              url  = "$${sys.get_env(\"COMPOSER_URL\") + \"/internal/plan\"}"
              auth = { type = "OIDC" }
              body = {
                tenantId     = "$${tenantId}"
                caseId       = "$${caseId}"
                countryCode  = "$${countryCode}"
                documentType = "$${documentType}"
              }
            }
            result = "planResponse"
          }
        },
        {
          assign_plan = {
            assign = [
              { plan = "$${planResponse.body}" },
            ]
          }
        },
        {
          # Las verificaciones automaticas corren en paralelo. LIMITE: maximo 10
          # ramas por paso parallel y 2 niveles de anidamiento.
          automated_checks = {
            parallel = {
              shared   = ["extraction", "biometrics"]
              branches = [
                {
                  extraction_branch = {
                    steps = [
                      {
                        call_extraction = {
                          call = "http.post"
                          args = {
                            url     = "$${sys.get_env(\"EXTRACTION_URL\") + \"/extract\"}"
                            auth    = { type = "OIDC" }
                            timeout = 540
                            body    = {
                              tenantId     = "$${tenantId}"
                              caseId       = "$${caseId}"
                              documentUri  = "$${documentUri}"
                              countryCode  = "$${countryCode}"
                              documentType = "$${documentType}"
                            }
                          }
                          result = "extractionResponse"
                        }
                      },
                      {
                        # Solo el puntero al resultado, nunca el resultado.
                        keep_pointer = {
                          assign = [
                            { extraction = "$${extractionResponse.body.fieldsUri}" },
                          ]
                        }
                      },
                    ]
                  }
                },
                {
                  biometrics_branch = {
                    steps = [
                      {
                        check_required = {
                          switch = [
                            {
                              condition = "$${plan.requiresBiometry}"
                              next      = "call_biometrics"
                            },
                          ]
                          next = "skip_biometrics"
                        }
                      },
                      {
                        call_biometrics = {
                          call = "http.post"
                          args = {
                            url     = "$${sys.get_env(\"BIOMETRICS_URL\") + \"/verify\"}"
                            auth    = { type = "OIDC" }
                            timeout = 300
                            body    = {
                              tenantId          = "$${tenantId}"
                              caseId            = "$${caseId}"
                              livenessSessionId = "$${args.livenessSessionId}"
                            }
                          }
                          result = "biometricsResponse"
                        }
                      },
                      {
                        assign_biometrics = {
                          assign = [
                            { biometrics = "$${biometricsResponse.body.resultUri}" },
                          ]
                          next = "end"
                        }
                      },
                      {
                        skip_biometrics = {
                          assign = [
                            { biometrics = "" },
                          ]
                        }
                      },
                    ]
                  }
                },
              ]
            }
          }
        },
        {
          score_risk = {
            call = "http.post"
            args = {
              url  = "$${sys.get_env(\"COMPOSER_URL\") + \"/internal/score\"}"
              auth = { type = "OIDC" }
              body = {
                tenantId      = "$${tenantId}"
                caseId        = "$${caseId}"
                extractionUri = "$${extraction}"
                biometricsUri = "$${biometrics}"
              }
            }
            result = "riskResponse"
          }
        },
        {
          decide = {
            switch = [
              {
                condition = "$${riskResponse.body.decision == \"AUTO_APPROVE\"}"
                next      = "record_decision"
              },
              {
                condition = "$${riskResponse.body.decision == \"AUTO_REJECT\"}"
                next      = "record_decision"
              },
            ]
            next = "await_human_decision"
          }
        },
        {
          # ADVERTENCIA CRITICA: el callback tiene un tiempo de espera por
          # defecto de 43.200 s (12 h) y SOLO UN SLOT pendiente por endpoint (un
          # segundo callback recibe HTTP 429). No hay heartbeat. Para revisiones
          # que puedan cruzar un fin de semana, use el patron alternativo:
          # persistir el estado en Firestore, terminar el workflow, y lanzar una
          # ejecucion nueva con executions.run cuando llegue la decision.
          await_human_decision = {
            steps = [
              {
                create_callback = {
                  call   = "events.create_callback_endpoint"
                  args   = { http_callback_method = "POST" }
                  result = "callbackDetails"
                }
              },
              {
                enqueue_review = {
                  call = "http.post"
                  args = {
                    url  = "$${sys.get_env(\"REVIEW_URL\") + \"/queue\"}"
                    auth = { type = "OIDC" }
                    body = {
                      tenantId    = "$${tenantId}"
                      caseId      = "$${caseId}"
                      callbackUrl = "$${callbackDetails.url}"
                      riskUri     = "$${riskResponse.body.riskUri}"
                    }
                  }
                }
              },
              {
                wait_for_reviewer = {
                  call = "events.await_callback"
                  args = {
                    callback = "$${callbackDetails}"
                    timeout  = "$${sys.get_env(\"CALLBACK_TIMEOUT_SECONDS\")}"
                  }
                  result = "callbackRequest"
                }
              },
              {
                apply_human_decision = {
                  assign = [
                    { humanOutcome = "$${callbackRequest.http_request.body.outcome}" },
                  ]
                }
              },
            ]
          }
        },
        {
          record_decision = {
            call = "http.post"
            args = {
              url  = "$${sys.get_env(\"COMPOSER_URL\") + \"/internal/decision\"}"
              auth = { type = "OIDC" }
              body = {
                tenantId = "$${tenantId}"
                caseId   = "$${caseId}"
                riskUri  = "$${riskResponse.body.riskUri}"
              }
            }
            result = "decisionResponse"
          }
        },
        {
          done = {
            return = {
              caseId = "$${caseId}"
              status = "$${decisionResponse.body.status}"
            }
          }
        },
      ]
    }
  })
}

resource "google_workflows_workflow" "onboarding" {
  name            = "${local.name}-onboarding-saga"
  project         = var.project_id
  region          = var.region
  description     = "Saga de onboarding. Transporta exclusivamente punteros gs:// por el limite de 512 KB acumulados por ejecucion."
  service_account = var.workflow_service_account_email

  call_log_level = var.call_log_level

  user_env_vars = {
    COMPOSER_URL             = var.composer_service_url
    EXTRACTION_URL           = var.extraction_service_url
    BIOMETRICS_URL           = var.biometrics_service_url
    REVIEW_URL               = var.review_service_url
    CALLBACK_TIMEOUT_SECONDS = tostring(var.callback_timeout_seconds)
  }

  source_contents = local.workflow_source

  labels = var.labels
}

# ---------------------------------------------------------------------------
# Cloud Tasks: el sustituto de los hijos Express para pasos asincronos cortos
#
# Tamano de tarea 1 MiB, despacho de 500 tareas/s por cola, programacion hasta
# 30 dias en el futuro, retencion 31 dias, deduplicacion hasta 24 h.
# El deadline HTTP es de 10 minutos por defecto y 30 minutos como maximo.
# ---------------------------------------------------------------------------

resource "google_cloud_tasks_queue" "verification" {
  name     = "${local.name}-verification"
  project  = var.project_id
  location = var.region

  rate_limits {
    max_dispatches_per_second = var.task_max_dispatches_per_second
    max_concurrent_dispatches = var.task_max_concurrent_dispatches
  }

  retry_config {
    max_attempts       = var.task_max_attempts
    max_retry_duration = "${var.task_max_retry_duration_seconds}s"
    min_backoff        = "1s"
    max_backoff        = "60s"
    max_doublings      = 4
  }

  stackdriver_logging_config {
    sampling_ratio = var.task_log_sampling_ratio
  }
}

# Cola separada para llamadas a proveedores externos facturables: se limita mas
# y se reintenta menos, porque cada intento cuesta dinero.
resource "google_cloud_tasks_queue" "external_providers" {
  name     = "${local.name}-external-providers"
  project  = var.project_id
  location = var.region

  rate_limits {
    max_dispatches_per_second = var.external_max_dispatches_per_second
    max_concurrent_dispatches = var.external_max_concurrent_dispatches
  }

  retry_config {
    max_attempts  = 2 # cada intento se factura al proveedor
    min_backoff   = "5s"
    max_backoff   = "300s"
    max_doublings = 3
  }
}

# ---------------------------------------------------------------------------
# Pub/Sub: eventos de dominio
#
# Mensaje hasta 10 MB, retencion de suscripcion de 7 dias por defecto y hasta 31
# dias, entrega exactamente una vez y claves de ordenacion (1 MBps por clave).
# ---------------------------------------------------------------------------

resource "google_pubsub_topic" "domain_events" {
  name    = "${local.name}-domain-events"
  project = var.project_id

  message_retention_duration = "${var.event_retention_days * 24 * 3600}s"

  # CMEK sobre el topico. Los mensajes tambien deberian llevar solo punteros.
  kms_key_name = var.cmek_key_name

  labels = var.labels
}

resource "google_pubsub_topic" "domain_events_dlq" {
  name    = "${local.name}-domain-events-dlq"
  project = var.project_id

  kms_key_name = var.cmek_key_name

  labels = var.labels
}

resource "google_pubsub_subscription" "domain_events" {
  name    = "${local.name}-domain-events-sub"
  project = var.project_id
  topic   = google_pubsub_topic.domain_events.id

  ack_deadline_seconds       = 60
  message_retention_duration = "${var.event_retention_days * 24 * 3600}s"
  retain_acked_messages      = false

  # Firestore mas Eventarc NO garantiza orden. Si la saga depende del orden por
  # caso, active la ordenacion y publique con el caseId como clave.
  enable_message_ordering = var.enable_message_ordering

  # Entrega exactamente una vez: reduce duplicados, pero no exime de disenar los
  # consumidores como idempotentes.
  enable_exactly_once_delivery = true

  expiration_policy {
    ttl = "" # la suscripcion no expira por inactividad
  }

  retry_policy {
    minimum_backoff = "10s"
    maximum_backoff = "600s"
  }

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.domain_events_dlq.id
    max_delivery_attempts = var.max_delivery_attempts
  }

  push_config {
    push_endpoint = "${var.composer_service_url}/internal/events"

    oidc_token {
      service_account_email = var.workflow_service_account_email
    }
  }
}

# ---------------------------------------------------------------------------
# Eventarc: cambios en Firestore hacia el composer
#
# Es el analogo mas cercano a DynamoDB Streams, con dos diferencias
# fundamentales: no hay garantia de orden estricto y no hay reproduccion del
# stream historico.
# ---------------------------------------------------------------------------

resource "google_eventarc_trigger" "firestore_case_written" {
  count = var.enable_firestore_trigger ? 1 : 0

  name     = "${local.name}-case-written"
  project  = var.project_id
  location = var.region

  matching_criteria {
    attribute = "type"
    value     = "google.cloud.firestore.document.v1.written"
  }

  matching_criteria {
    attribute = "database"
    value     = var.firestore_database_name
  }

  matching_criteria {
    attribute = "document"
    operator  = "match-path-pattern"
    value     = "${var.cases_collection}/{caseId}"
  }

  destination {
    cloud_run_service {
      service = var.composer_service_name
      region  = var.region
      path    = "/internal/case-changed"
    }
  }

  service_account = var.workflow_service_account_email

  labels = var.labels
}
