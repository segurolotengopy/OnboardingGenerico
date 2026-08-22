variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "location_id" {
  description = "Ubicacion de las bases de datos de Firestore. Puede ser multirregion (nam5, eur3) o una region concreta. Es inmutable una vez creada la base de datos."
  type        = string
  default     = "nam5"
}

variable "shared_database_name" {
  description = "Nombre de la base de datos compartida. El valor (default) crea la base de datos por defecto del proyecto, que no puede eliminarse."
  type        = string
  default     = "(default)"
}

variable "tenants" {
  description = "Mapa de tenant_id a sus atributos. Los tenants con tier premium reciben una base de datos Firestore dedicada."
  type        = map(object({
    tier         = optional(string, "standard")
    jurisdiction = optional(string, "")
  }))
  default = {}
}

variable "tenant_service_account_emails" {
  description = "Mapa de tenant_id a correo de su cuenta de servicio dedicada. Lo produce el modulo gcp/identity."
  type        = map(string)
  default     = {}
}

variable "cmek_key_name" {
  description = "Nombre completo de la llave de Cloud KMS que cifra la base de datos compartida. Cloud KMS Autokey no soporta Firestore, asi que debe declararse de forma explicita. Nulo usa el cifrado gestionado por Google."
  type        = string
  default     = null
}

variable "tenant_cmek_key_names" {
  description = "Mapa de tenant_id a nombre de llave de Cloud KMS para su base de datos dedicada. Si falta una entrada se usa cmek_key_name."
  type        = map(string)
  default     = {}
}

variable "enable_point_in_time_recovery" {
  description = "Habilita la recuperacion a un punto en el tiempo. Obligatorio en produccion."
  type        = bool
  default     = false
}

variable "enable_delete_protection" {
  description = "Impide el borrado de la base de datos desde la API. Debe estar activo en produccion."
  type        = bool
  default     = false
}

variable "cases_collection" {
  description = "Nombre del grupo de colecciones de casos de onboarding."
  type        = string
  default     = "cases"
}

variable "reviews_collection" {
  description = "Nombre del grupo de colecciones de la cola de revision manual."
  type        = string
  default     = "reviews"
}

variable "capabilities_collection" {
  description = "Nombre del grupo de colecciones del Registro de Capacidades."
  type        = string
  default     = "capabilities"
}

variable "locks_collection" {
  description = "Nombre del grupo de colecciones del mutex distribuido."
  type        = string
  default     = "locks"
}

variable "ephemeral_collection" {
  description = "Nombre del grupo de colecciones de artefactos de trabajo efimeros, unico con politica de TTL sobre expires_at."
  type        = string
  default     = "ephemeral"
}
