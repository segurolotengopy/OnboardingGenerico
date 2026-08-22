# ---------------------------------------------------------------------------
# Red privada en GCP.
#
# Diferencias estructurales con AWS que condicionan este modulo:
#
#   - La VPC de GCP es GLOBAL; las subredes son regionales. No hay que crear una
#     VPC por region.
#   - No existe el concepto de security group como referencia mutua. El control
#     se hace con reglas de firewall que seleccionan por etiqueta de red o por
#     cuenta de servicio. Aqui se usa la CUENTA DE SERVICIO como selector,
#     porque una etiqueta de red la puede poner cualquiera con permiso de
#     computo, mientras que suplantar una cuenta de servicio requiere IAM.
#   - El equivalente a los VPC endpoints es Private Service Connect hacia las
#     APIs de Google, con una direccion IP interna propia.
#   - Para el egreso privado desde Cloud Run hay dos mecanismos incompatibles
#     entre si: Direct VPC egress (sin recurso intermedio, escala a cero) y
#     Serverless VPC Access connector (VMs gestionadas que se pagan siempre).
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"
}

resource "google_compute_network" "this" {
  name                    = "${local.name}-vpc"
  project                 = var.project_id
  auto_create_subnetworks = false
  routing_mode            = "REGIONAL"
  description             = "VPC del middleware de onboarding (${var.env})."
}

# Subred principal del computo.
#
# DIMENSIONADO: en estado estable, los servicios de Cloud Run consumen del orden
# de dos direcciones IP por instancia en ejecucion, y los jobs una por tarea mas
# unos minutos de retencion tras completarse. Un /26 (64 direcciones) soporta
# aproximadamente 30 instancias. Sobredimensione: ampliar una subred en uso es
# posible pero no es gratis operativamente.
resource "google_compute_subnetwork" "compute" {
  name          = "${local.name}-subnet-compute"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.this.id
  ip_cidr_range = var.compute_subnet_cidr

  # Permite alcanzar las APIs de Google sin IP externa.
  private_ip_google_access = true

  log_config {
    aggregation_interval = "INTERVAL_10_MIN"
    flow_sampling        = var.flow_log_sampling
    metadata             = "INCLUDE_ALL_METADATA"
  }
}

# Subred dedicada del conector de Serverless VPC Access. El conector exige una
# subred /28 exclusiva y no compartible.
resource "google_compute_subnetwork" "connector" {
  count = var.enable_vpc_connector ? 1 : 0

  name          = "${local.name}-subnet-connector"
  project       = var.project_id
  region        = var.region
  network       = google_compute_network.this.id
  ip_cidr_range = var.connector_subnet_cidr
}

resource "google_vpc_access_connector" "this" {
  count = var.enable_vpc_connector ? 1 : 0

  name    = "${local.name}-connector"
  project = var.project_id
  region  = var.region

  subnet {
    name = google_compute_subnetwork.connector[0].name
  }

  min_instances = var.connector_min_instances
  max_instances = var.connector_max_instances
  machine_type  = var.connector_machine_type
}

# ---------------------------------------------------------------------------
# Salida a Internet controlada
# ---------------------------------------------------------------------------

resource "google_compute_router" "this" {
  count = var.enable_cloud_nat ? 1 : 0

  name    = "${local.name}-router"
  project = var.project_id
  region  = var.region
  network = google_compute_network.this.id
}

resource "google_compute_router_nat" "this" {
  count = var.enable_cloud_nat ? 1 : 0

  name    = "${local.name}-nat"
  project = var.project_id
  region  = var.region
  router  = google_compute_router.this[0].name

  nat_ip_allocate_option             = "AUTO_ONLY"
  source_subnetwork_ip_ranges_to_nat = "LIST_OF_SUBNETWORKS"

  subnetwork {
    name                    = google_compute_subnetwork.compute.id
    source_ip_ranges_to_nat = ["ALL_IP_RANGES"]
  }

  log_config {
    enable = true
    filter = "ERRORS_ONLY"
  }
}

# ---------------------------------------------------------------------------
# Private Service Connect hacia las APIs de Google
#
# Equivalente funcional de los VPC endpoints de tipo Interface de AWS: permite
# alcanzar storage.googleapis.com, firestore.googleapis.com, etc. por una IP
# interna propia, sin salir a Internet.
# ---------------------------------------------------------------------------

resource "google_compute_global_address" "psc_google_apis" {
  count = var.enable_psc_google_apis ? 1 : 0

  name         = "${local.name}-psc-google-apis"
  project      = var.project_id
  purpose      = "PRIVATE_SERVICE_CONNECT"
  address_type = "INTERNAL"
  address      = var.psc_endpoint_address
  network      = google_compute_network.this.id
}

resource "google_compute_global_forwarding_rule" "psc_google_apis" {
  count = var.enable_psc_google_apis ? 1 : 0

  name                  = "${local.name}-psc-google-apis"
  project               = var.project_id
  network               = google_compute_network.this.id
  ip_address            = google_compute_global_address.psc_google_apis[0].id
  load_balancing_scheme = ""

  # "all-apis" alcanza la mayoria de las APIs de Google; "vpc-sc" restringe el
  # conjunto a los servicios compatibles con VPC Service Controls.
  target = var.psc_target
}

# ---------------------------------------------------------------------------
# Reglas de firewall
#
# Se selecciona por cuenta de servicio, no por etiqueta de red: una etiqueta la
# puede aplicar cualquiera con permiso de computo, mientras que actuar como una
# cuenta de servicio exige un permiso IAM explicito.
# ---------------------------------------------------------------------------

resource "google_compute_firewall" "deny_all_egress" {
  name        = "${local.name}-deny-all-egress"
  project     = var.project_id
  network     = google_compute_network.this.name
  description = "Denegacion por defecto del egreso. Las reglas de prioridad menor abren lo necesario."
  direction   = "EGRESS"
  priority    = 65000

  deny {
    protocol = "all"
  }

  destination_ranges = ["0.0.0.0/0"]

  target_service_accounts = var.compute_service_accounts

  log_config {
    metadata = "INCLUDE_ALL_METADATA"
  }
}

resource "google_compute_firewall" "allow_https_egress" {
  name        = "${local.name}-allow-https-egress"
  project     = var.project_id
  network     = google_compute_network.this.name
  description = "Egreso HTTPS del computo hacia APIs de Google y proveedores autorizados."
  direction   = "EGRESS"
  priority    = 1000

  allow {
    protocol = "tcp"
    ports    = ["443"]
  }

  destination_ranges = var.allowed_egress_cidrs

  target_service_accounts = var.compute_service_accounts
}

resource "google_compute_firewall" "allow_internal" {
  name        = "${local.name}-allow-internal"
  project     = var.project_id
  network     = google_compute_network.this.name
  description = "Trafico interno entre componentes del middleware."
  direction   = "INGRESS"
  priority    = 1000

  allow {
    protocol = "tcp"
    ports    = ["443", "8080"]
  }

  source_ranges = [var.compute_subnet_cidr]

  target_service_accounts = var.compute_service_accounts
}
