variable "env" {
  description = "Identificador del entorno (dev, stg, prd). Se usa como parte del prefijo de nombres og-{env}-*."
  type        = string
}

variable "aws_region" {
  description = "Region de AWS donde se crean la VPC y los endpoints de servicio."
  type        = string
}

variable "vpc_cidr" {
  description = "Bloque CIDR de la VPC. Debe dejar espacio para las subredes privadas y la subred de NAT."
  type        = string
  default     = "10.60.0.0/16"
}

variable "private_subnets" {
  description = "Mapa de zona de disponibilidad a bloque CIDR de subred privada. Se recomienda un minimo de dos zonas."
  type        = map(string)
}

variable "enable_interface_endpoints" {
  description = "Crea los VPC endpoints de tipo Interface (KMS, Secrets Manager, ECR, Logs, Step Functions, STS). Tienen coste por hora y por ENI; conviene desactivarlos en entornos efimeros."
  type        = bool
  default     = true
}

variable "enable_nat_gateway" {
  description = "Crea Internet Gateway, subred de NAT y NAT Gateway para permitir egreso a Internet desde las subredes privadas. Solo necesario si algun adaptador llama a proveedores SaaS externos."
  type        = bool
  default     = false
}

variable "nat_subnet_cidr" {
  description = "Bloque CIDR de la subred que aloja el NAT Gateway. Solo se usa cuando enable_nat_gateway es verdadero."
  type        = string
  default     = "10.60.240.0/24"
}

variable "tags" {
  description = "Etiquetas adicionales especificas de este modulo. Las etiquetas obligatorias del proyecto se aplican con default_tags en el provider."
  type        = map(string)
  default     = {}
}
