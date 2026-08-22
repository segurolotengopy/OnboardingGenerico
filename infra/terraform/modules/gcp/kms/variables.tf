variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "location" {
  description = "Ubicacion del keyring. Debe coincidir con la de los recursos que cifra; una llave regional no puede cifrar un recurso de otra region."
  type        = string
  default     = "us-central1"
}

variable "tenants" {
  description = "Mapa de tenant_id a sus atributos. Se crea una llave por entrada. La clave del mapa es el valor que viaja como Associated Data del cifrado de sobre."
  type = map(object({
    tier             = optional(string, "standard")
    protection_level = optional(string, null)
  }))
  default = {}
}

variable "rotation_period" {
  description = "Periodo de rotacion automatica de la llave, en segundos con sufijo s. El valor por defecto equivale a 365 dias."
  type        = string
  default     = "31536000s"
}

variable "destroy_scheduled_duration" {
  description = "Ventana durante la que una version programada para destruccion puede restaurarse. El valor por defecto de Cloud KMS son 30 dias. PENDIENTE DE VERIFICAR: el minimo configurable no esta documentado en la pagina de destruccion y restauracion; verifiquelo antes de comprometer un SLA de borrado. La organizacion puede ademas imponer un minimo con la restriccion constraints/cloudkms.minimumDestroyScheduledDuration."
  type        = string
  default     = "2592000s"
}

variable "protection_level" {
  description = "Nivel de proteccion de las versiones: SOFTWARE o HSM. HSM tiene mayor coste por operacion y no esta disponible en todas las ubicaciones."
  type        = string
  default     = "SOFTWARE"

  validation {
    condition     = contains(["SOFTWARE", "HSM"], var.protection_level)
    error_message = "protection_level debe ser SOFTWARE o HSM."
  }
}

variable "platform_key_service_agents" {
  description = "Miembros de IAM (agentes de servicio) que necesitan usar la llave de plataforma como CMEK. Cada servicio gestionado tiene su propio agente, con formato serviceAccount:service-{numero}@gs-project-accounts.iam.gserviceaccount.com y equivalentes."
  type        = list(string)
  default     = []
}

variable "tenant_service_account_emails" {
  description = "Mapa de tenant_id a correo de su cuenta de servicio dedicada. Solo los tenants con entrada aqui reciben un binding exclusivo sobre su llave."
  type        = map(string)
  default     = {}
}

variable "runtime_service_account_email" {
  description = "Correo de la cuenta de servicio del runtime compartido. Puede usar todas las llaves de tenant: la separacion real la aporta el Associated Data del cifrado de sobre, no IAM."
  type        = string
  default     = null
}

variable "shredding_operator_member" {
  description = "Miembro de IAM autorizado a programar la destruccion de llaves de tenant. Debe ser distinto de la identidad del runtime: el crypto-shredding no debe estar al alcance del camino de ejecucion normal."
  type        = string
  default     = null
}

variable "enable_autokey" {
  description = "Habilita Cloud KMS Autokey. Requiere una carpeta y ubicaciones con Cloud HSM. Firestore no esta entre los servicios soportados."
  type        = bool
  default     = false
}

variable "autokey_folder_id" {
  description = "Identificador de la carpeta donde se configura Autokey, en formato folders/{id}."
  type        = string
  default     = ""
}

variable "labels" {
  description = "Etiquetas adicionales aplicadas a las llaves."
  type        = map(string)
  default     = {}
}
