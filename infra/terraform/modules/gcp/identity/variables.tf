variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "tenants" {
  description = "Mapa de tenant_id a sus atributos. Los tenants con tier premium reciben cuenta de servicio dedicada, base de datos Firestore propia y vinculacion de federacion de identidades."
  type = map(object({
    tier                  = optional(string, "standard")
    jurisdiction          = optional(string, "")
    allow_password_signup = optional(bool, false)
  }))
  default = {}
}

variable "enable_workload_identity_federation" {
  description = "Crea el pool y el proveedor de federacion de identidades, y vincula cada tenant premium a su cuenta de servicio mediante attribute.tenant."
  type        = bool
  default     = true
}

variable "oidc_issuer_uri" {
  description = "URI del emisor OIDC que emite los tokens de los sistemas requirentes."
  type        = string
  default     = "https://issuer.example.invalid"
}

variable "oidc_audience" {
  description = "Audiencia esperada en el token. La condicion de atributo la exige de forma explicita: un token con otra audiencia nunca se intercambia por credenciales."
  type        = string
  default     = "onboarding-generico"
}

variable "tenant_scoped_bucket_names" {
  description = "Nombres de los buckets sobre los que se aplican condiciones de IAM por prefijo de tenant. Es el unico punto donde GCP se acerca al scoping por prefijo de S3."
  type        = list(string)
  default     = []
}

variable "data_access_audited_services" {
  description = "Servicios cuyos Data Access audit logs se habilitan. Estan apagados por defecto en GCP y sin ellos no hay traza de quien leyo datos de que tenant."
  type        = list(string)
  default = [
    "firestore.googleapis.com",
    "storage.googleapis.com",
    "cloudkms.googleapis.com",
    "secretmanager.googleapis.com",
  ]
}

variable "signup_quota_per_hour" {
  description = "Cuota de altas de cuenta por hora en Identity Platform. Nulo deja la cuota por defecto del servicio."
  type        = number
  default     = null
}

variable "signup_quota_start_time" {
  description = "Momento de inicio de la ventana de cuota de altas, en formato RFC 3339."
  type        = string
  default     = ""
}

variable "access_policy_name" {
  description = "Identificador numerico de la politica de acceso de la organizacion, necesario para VPC Service Controls. Solo se usa si se descomenta el perimetro; requiere permisos de organizacion."
  type        = string
  default     = ""
}

variable "project_number" {
  description = "Numero del proyecto, necesario para declarar el recurso dentro del perimetro de VPC Service Controls."
  type        = string
  default     = ""
}
