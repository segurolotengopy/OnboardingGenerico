output "network_id" {
  description = "Identificador de la VPC. La VPC de Google Cloud es global, asi que sirve para cualquier region."
  value       = google_compute_network.this.id
}

output "network_name" {
  description = "Nombre de la VPC."
  value       = google_compute_network.this.name
}

output "compute_subnet_id" {
  description = "Identificador de la subred del computo. Es el valor que espera el bloque network_interfaces de Direct VPC egress en Cloud Run."
  value       = google_compute_subnetwork.compute.id
}

output "compute_subnet_name" {
  description = "Nombre de la subred del computo."
  value       = google_compute_subnetwork.compute.name
}

output "vpc_connector_id" {
  description = "Identificador del conector de Serverless VPC Access, o nulo si no se creo."
  value       = try(google_vpc_access_connector.this[0].id, null)
}

output "psc_google_apis_address" {
  description = "Direccion IP interna del endpoint de Private Service Connect hacia las APIs de Google, o nulo si no se creo."
  value       = try(google_compute_global_address.psc_google_apis[0].address, null)
}
