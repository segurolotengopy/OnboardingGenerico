variable "project_id" {
  description = "Identificador del proyecto de Google Cloud."
  type        = string
}

variable "env" {
  description = "Identificador del entorno (dev, stg, prd)."
  type        = string
}

variable "region" {
  description = "Region donde se crean las subredes y el conector."
  type        = string
}

variable "compute_subnet_cidr" {
  description = "Rango CIDR de la subred del computo. Debe ser /26 o mayor para Direct VPC egress. Sobredimensione: los servicios consumen del orden de dos direcciones por instancia en ejecucion."
  type        = string
  default     = "10.70.0.0/24"
}

variable "enable_vpc_connector" {
  description = "Crea un conector de Serverless VPC Access. Es una alternativa a Direct VPC egress: tiene coste fijo por instancia del conector pero no sufre el limite de 100 a 200 instancias del egreso directo."
  type        = bool
  default     = false
}

variable "connector_subnet_cidr" {
  description = "Rango CIDR de la subred dedicada del conector. Debe ser exactamente /28 y no puede compartirse con otros recursos."
  type        = string
  default     = "10.70.240.0/28"
}

variable "connector_min_instances" {
  description = "Numero minimo de instancias del conector. Se facturan siempre, esten o no cursando trafico."
  type        = number
  default     = 2
}

variable "connector_max_instances" {
  description = "Numero maximo de instancias del conector."
  type        = number
  default     = 3
}

variable "connector_machine_type" {
  description = "Tipo de maquina de las instancias del conector."
  type        = string
  default     = "e2-micro"
}

variable "enable_cloud_nat" {
  description = "Crea Cloud Router y Cloud NAT para el egreso a Internet. Solo necesario si algun adaptador llama a proveedores SaaS externos."
  type        = bool
  default     = false
}

variable "enable_psc_google_apis" {
  description = "Crea el endpoint de Private Service Connect hacia las APIs de Google. Es el equivalente funcional de los VPC endpoints de tipo Interface de AWS."
  type        = bool
  default     = true
}

variable "psc_endpoint_address" {
  description = "Direccion IP interna reservada para el endpoint de Private Service Connect. Debe quedar fuera de los rangos de las subredes."
  type        = string
  default     = "10.70.255.250"
}

variable "psc_target" {
  description = "Conjunto de APIs alcanzables por el endpoint: all-apis abarca la mayoria de las APIs de Google; vpc-sc restringe a los servicios compatibles con VPC Service Controls."
  type        = string
  default     = "all-apis"

  validation {
    condition     = contains(["all-apis", "vpc-sc"], var.psc_target)
    error_message = "psc_target debe ser all-apis o vpc-sc."
  }
}

variable "compute_service_accounts" {
  description = "Correos de las cuentas de servicio del computo. Se usan como selector de las reglas de firewall, en lugar de etiquetas de red."
  type        = list(string)
  default     = []
}

variable "allowed_egress_cidrs" {
  description = "Rangos de destino permitidos para el egreso HTTPS. Restrinjalos a los rangos de las APIs de Google y a los proveedores externos autorizados."
  type        = list(string)
  default     = ["0.0.0.0/0"]
}

variable "flow_log_sampling" {
  description = "Proporcion de flujos registrados en los logs de la subred, entre cero y uno. Los flow logs tienen coste por volumen."
  type        = number
  default     = 0.1
}
