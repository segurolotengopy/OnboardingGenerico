# ---------------------------------------------------------------------------
# API Gateway de GCP.
#
# BRECHA FUNCIONAL CENTRAL
# ------------------------
# GCP API Gateway NO tiene equivalente al Lambda Authorizer: no hay forma de
# ejecutar codigo arbitrario por peticion en el gateway. Solo admite
# autenticacion DECLARATIVA: claves de API, cuentas de servicio con JWT firmado,
# y validacion de JWT contra emisores configurados mediante `x-google-issuer` y
# `x-google-jwks_uri` en el documento OpenAPI.
#
# Consecuencia de diseno: la autorizacion (resolver tenant, aplicar politicas,
# comprobar tier) vive como MIDDLEWARE DENTRO DEL CLOUD RUN, no en el gateway.
# Esto es en realidad mas portable, porque saca la autorizacion del adaptador de
# infraestructura y la lleva al nucleo. El gateway solo verifica que el token
# esta firmado por el emisor correcto y tiene la audiencia correcta.
#
# PROVIDER: los recursos google_api_gateway_* han vivido historicamente solo en
# el provider `google-beta`. Este modulo los declara con `provider =
# google-beta` de forma explicita. Verifique la version de su provider antes de
# asumir que estan en el estable.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"

  # OpenAPI 2.0 (Swagger): es el unico formato que acepta API Gateway de GCP.
  # Se construye con yamlencode para que las URLs de backend y el emisor sean
  # variables y no cadenas cableadas.
  openapi_document = yamlencode({
    swagger = "2.0"
    info = {
      title       = "${local.name}-api"
      version     = "1.0.0"
      description = "API del middleware de onboarding y eKYC."
    }
    schemes  = ["https"]
    produces = ["application/json"]
    consumes = ["application/json"]

    # Validacion declarativa del JWT. Es todo lo que el gateway puede hacer: la
    # resolucion de tenant y las politicas se aplican dentro del Cloud Run.
    securityDefinitions = {
      tenant_jwt = {
        authorizationUrl     = ""
        flow                 = "implicit"
        type                 = "oauth2"
        "x-google-issuer"    = var.jwt_issuer
        "x-google-jwks_uri"  = var.jwt_jwks_uri
        "x-google-audiences" = var.jwt_audience
      }
      api_key = {
        type = "apiKey"
        name = "x-api-key"
        in   = "header"
      }
    }

    paths = {
      "/v1/onboarding/cases" = {
        post = {
          summary     = "Inicia un caso de onboarding"
          operationId = "startCase"
          security = [
            { tenant_jwt = [] },
            { api_key = [] },
          ]
          "x-google-backend" = {
            address = "${var.composer_service_url}/v1/onboarding/cases"
            # El deadline del backend debe ser menor que el timeout del servicio
            # de Cloud Run, o el gateway cortara antes de que el servicio
            # responda.
            deadline         = var.backend_deadline_seconds
            path_translation = "APPEND_PATH_TO_ADDRESS"
          }
          responses = {
            "202" = { description = "Caso aceptado" }
            "400" = { description = "Peticion invalida" }
            "401" = { description = "Token ausente o invalido" }
            "429" = { description = "Cuota del tenant excedida" }
          }
        }
      }

      "/v1/onboarding/cases/{caseId}" = {
        get = {
          summary     = "Consulta el estado de un caso"
          operationId = "getCase"
          security    = [{ tenant_jwt = [] }]
          parameters = [
            {
              name     = "caseId"
              in       = "path"
              required = true
              type     = "string"
            }
          ]
          "x-google-backend" = {
            address          = "${var.composer_service_url}/v1/onboarding/cases"
            deadline         = var.backend_deadline_seconds
            path_translation = "APPEND_PATH_TO_ADDRESS"
          }
          responses = {
            "200" = { description = "Estado del caso" }
            "404" = { description = "Caso no encontrado o fuera del alcance del tenant" }
          }
        }
      }

      # Las imagenes NO pasan por el gateway: el cliente pide una URL firmada de
      # Cloud Storage y sube directamente. Ademas de esquivar el limite de 32 MB
      # por peticion, saca los binarios del camino critico.
      "/v1/onboarding/uploads" = {
        post = {
          summary     = "Solicita una URL firmada para subir un documento"
          operationId = "createUploadUrl"
          security    = [{ tenant_jwt = [] }]
          "x-google-backend" = {
            address          = "${var.composer_service_url}/v1/onboarding/uploads"
            deadline         = 30
            path_translation = "APPEND_PATH_TO_ADDRESS"
          }
          responses = {
            "201" = { description = "URL firmada emitida" }
          }
        }
      }

      "/v1/healthz" = {
        get = {
          summary     = "Sonda de salud"
          operationId = "healthz"
          "x-google-backend" = {
            address          = "${var.composer_service_url}/healthz"
            deadline         = 10
            path_translation = "APPEND_PATH_TO_ADDRESS"
          }
          responses = {
            "200" = { description = "Servicio disponible" }
          }
        }
      }
    }
  })
}

resource "google_api_gateway_api" "this" {
  provider = google-beta

  project      = var.project_id
  api_id       = "${local.name}-api"
  display_name = "Middleware de onboarding (${var.env})"

  labels = var.labels
}

resource "google_api_gateway_api_config" "this" {
  provider = google-beta

  project = var.project_id
  api     = google_api_gateway_api.this.api_id
  # El sufijo es un prefijo: la API genera el identificador final. Cada cambio
  # del documento crea una configuracion nueva, hasta 100 por API.
  api_config_id_prefix = "${local.name}-cfg-"

  openapi_documents {
    document {
      path     = "openapi.yaml"
      contents = base64encode(local.openapi_document)
    }
  }

  gateway_config {
    backend_config {
      # Cuenta de servicio con la que el gateway firma los tokens OIDC hacia
      # Cloud Run. Debe tener roles/run.invoker sobre el servicio.
      google_service_account = var.gateway_service_account_email
    }
  }

  labels = var.labels

  lifecycle {
    create_before_destroy = true
  }
}

resource "google_api_gateway_gateway" "this" {
  provider = google-beta

  project      = var.project_id
  region       = var.region
  gateway_id   = "${local.name}-gw"
  api_config   = google_api_gateway_api_config.this.id
  display_name = "Pasarela del middleware (${var.env})"

  labels = var.labels

  depends_on = [google_api_gateway_api_config.this]
}

# ---------------------------------------------------------------------------
# Cuotas por tenant
#
# API Gateway de GCP no tiene planes de uso como los de AWS. La cuota se
# gestiona con Service Management sobre el servicio gestionado, y el control
# fino por tenant acaba viviendo en el propio middleware.
# PENDIENTE DE VERIFICAR: no existe un recurso de Terraform que configure
# cuotas por consumidor sobre un API Gateway gestionado. El limite global del
# servicio es de 10.000.000 unidades de cuota por cada 100 segundos.
# ---------------------------------------------------------------------------

resource "google_project_service" "required" {
  for_each = toset(var.required_services)

  project = var.project_id
  service = each.value

  disable_on_destroy = false
}
