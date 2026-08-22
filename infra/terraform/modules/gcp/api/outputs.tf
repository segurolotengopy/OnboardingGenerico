output "gateway_id" {
  description = "Identificador de la pasarela."
  value       = google_api_gateway_gateway.this.gateway_id
}

output "gateway_url" {
  description = "Nombre de host por defecto de la pasarela. Es el punto de entrada de los sistemas requirentes."
  value       = google_api_gateway_gateway.this.default_hostname
}

output "api_id" {
  description = "Identificador de la API gestionada."
  value       = google_api_gateway_api.this.api_id
}

output "api_config_id" {
  description = "Identificador de la configuracion desplegada. Cambia con cada modificacion del documento OpenAPI."
  value       = google_api_gateway_api_config.this.api_config_id
}

output "managed_service_name" {
  description = "Nombre del servicio gestionado subyacente, necesario para configurar cuotas con Service Management."
  value       = google_api_gateway_api.this.managed_service
}
