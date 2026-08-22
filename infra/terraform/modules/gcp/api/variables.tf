variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "region" {
  description = "Region de la pasarela. API Gateway admite hasta 50 pasarelas por region."
  type        = string
}

variable "composer_service_url" {
  description = "URL base del servicio de Cloud Run que atiende las rutas de la API."
  type        = string
}

variable "gateway_service_account_email" {
  description = "Cuenta de servicio con la que la pasarela firma los tokens OIDC hacia el backend. Debe tener roles/run.invoker sobre el servicio de destino."
  type        = string
}

variable "jwt_issuer" {
  description = "Emisor esperado del token de los sistemas requirentes. La validacion del JWT es lo unico que el gateway puede hacer: la autorizacion vive dentro del Cloud Run."
  type        = string
}

variable "jwt_jwks_uri" {
  description = "URI del conjunto de claves publicas del emisor, usado por el gateway para verificar la firma."
  type        = string
}

variable "jwt_audience" {
  description = "Audiencia esperada en el token."
  type        = string
}

variable "backend_deadline_seconds" {
  description = "Plazo del backend en segundos. Debe ser menor que el timeout del servicio de Cloud Run, o el gateway cortara antes de que el servicio responda."
  type        = number
  default     = 60
}

variable "required_services" {
  description = "APIs de Google Cloud que deben estar habilitadas para que la pasarela funcione."
  type        = list(string)
  default = [
    "apigateway.googleapis.com",
    "servicemanagement.googleapis.com",
    "servicecontrol.googleapis.com",
  ]
}

variable "labels" {
  description = "Etiquetas adicionales aplicadas a los recursos de este modulo."
  type        = map(string)
  default     = {}
}
