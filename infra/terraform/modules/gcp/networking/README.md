# Modulo `gcp/networking`

## Que crea

- **VPC global** sin subredes automaticas, con `routing_mode = REGIONAL`.
- **Subred del computo** con `private_ip_google_access` y flow logs muestreados.
- **Conector de Serverless VPC Access** opcional, con su subred `/28` dedicada.
- **Cloud Router + Cloud NAT** opcionales para el egreso a Internet.
- **Endpoint de Private Service Connect** hacia las APIs de Google, con IP interna propia.
- **Reglas de firewall** que seleccionan por **cuenta de servicio**, no por etiqueta de red, con
  denegacion de egreso por defecto.

## Como se usa

```hcl
module "networking" {
  source     = "../../modules/gcp/networking"
  project_id = var.project_id
  env        = var.env
  region     = var.region

  compute_subnet_cidr      = "10.70.0.0/24"
  enable_psc_google_apis   = true
  compute_service_accounts = [module.identity.runtime_service_account_email]
}
```

Para Direct VPC egress, pase `module.networking.compute_subnet_name` al bloque
`vpc_access.network_interfaces` de `google_cloud_run_v2_service` (modulo `gcp/compute`).

## Advertencias

- 🔴 **Direct VPC egress limita a 100-200 instancias segun region.** Si el middleware necesita mas
  escala *y* red privada, hay que usar el conector (coste fijo) o repartir la carga en varios
  servicios. Revise esa cuota antes de comprometerse, no despues.
- 🔴 **Los tiempos de establecimiento de conexion pueden superar el minuto en el arranque de una
  instancia**, y los arranques en frio con Cloud NAT pueden pasar de 30 segundos. Es materialmente peor
  que Lambda en VPC. Para APIs sincronas de eKYC con SLA de latencia, **midalo antes de comprometerse**.
- **Direct VPC egress y el conector son mecanismos distintos y excluyentes.** El conector se paga
  siempre (VMs gestionadas), el egreso directo escala a cero pero tiene el techo de instancias.
- **Dimensionado de subred:** los servicios consumen del orden de **dos direcciones IP por instancia en
  ejecucion**; los jobs, una por tarea mas unos minutos de retencion tras completarse. Un `/26` soporta
  aproximadamente 30 instancias. La subred del conector debe ser **exactamente `/28`** y exclusiva.
- **GCP no tiene grupos de seguridad como referencia mutua.** No existe "permitir desde el SG X". Las
  reglas seleccionan por etiqueta de red o por cuenta de servicio; este modulo usa cuenta de servicio
  porque una etiqueta la puede poner cualquiera con permiso de computo.
- **Los jobs de Cloud Run que superen una hora pueden sufrir cortes de conexion** durante eventos de
  mantenimiento. Disenelos con reintentos idempotentes.
- **VPC Service Controls es la pieza que no existe en AWS** y que compensa parcialmente la ausencia de
  aislamiento a nivel de fila. No se crea aqui porque requiere permisos de Organizacion: el recurso
  esta comentado con instrucciones en `modules/gcp/identity/main.tf`.
- Los flow logs tienen coste por volumen. El muestreo por defecto es del 10 %; subalo solo durante una
  investigacion.
