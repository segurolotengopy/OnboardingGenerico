variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "aws_region" {
  description = "Region de AWS del user pool. Forma parte del emisor OIDC."
  type        = string
}

variable "pre_token_generation_lambda_arn" {
  description = "ARN de la funcion Lambda del trigger de generacion de token (evento V2.0) que inyecta principal_tags. Si es nulo, el trigger no se configura y el ABAC no funcionara."
  type        = string
  default     = null
}

variable "tenant_table_arns" {
  description = "ARNs de las tablas de DynamoDB sobre las que se aplica dynamodb:LeadingKeys. No incluya los ARNs de indice: el modulo agrega /index/* automaticamente."
  type        = list(string)
  default     = []
}

variable "tenant_bucket_arns" {
  description = "ARNs de los buckets S3 cuyo acceso se restringe al prefijo del tenant."
  type        = list(string)
  default     = []
}

variable "tenant_kms_key_arns" {
  description = "ARNs de las llaves KMS usables por la sesion de tenant, siempre condicionadas por el encryption context kms:EncryptionContext:tenant."
  type        = list(string)
  default     = []
}

variable "tenant_session_duration_seconds" {
  description = "Duracion maxima de la sesion asumida por tenant, en segundos. Sesiones cortas reducen la ventana de uso de credenciales filtradas."
  type        = number
  default     = 3600
}

variable "mfa_configuration" {
  description = "Configuracion de MFA del user pool: OFF, ON u OPTIONAL. Se recomienda ON en produccion para operadores de revision manual."
  type        = string
  default     = "OPTIONAL"

  validation {
    condition     = contains(["OFF", "ON", "OPTIONAL"], var.mfa_configuration)
    error_message = "mfa_configuration debe ser OFF, ON u OPTIONAL."
  }
}

variable "advanced_security_mode" {
  description = "Modo de seguridad avanzada de Cognito: OFF, AUDIT o ENFORCED. Tiene coste por usuario activo mensual."
  type        = string
  default     = "AUDIT"
}

variable "access_token_validity_minutes" {
  description = "Vigencia del access token en minutos."
  type        = number
  default     = 60
}

variable "id_token_validity_minutes" {
  description = "Vigencia del id token en minutos."
  type        = number
  default     = 60
}

variable "refresh_token_validity_days" {
  description = "Vigencia del refresh token en dias."
  type        = number
  default     = 7
}

variable "oidc_thumbprints" {
  description = "Huellas digitales del certificado del emisor OIDC de Cognito. AWS ya no las valida para emisores propios, pero el recurso las sigue exigiendo."
  type        = list(string)
  default     = ["9e99a48a9960b14926bb7f3b02e22da2b0ab7280"]
}

variable "platform_role_trusted_principals" {
  description = "Principals de AWS autorizados a asumir el rol de plataforma (operaciones sin scoping de tenant). Lista vacia significa que el rol no se crea."
  type        = list(string)
  default     = []
}

variable "enable_deletion_protection" {
  description = "Activa la proteccion contra borrado del user pool. Debe estar activa en produccion."
  type        = bool
  default     = false
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo."
  type        = map(string)
  default     = {}
}
