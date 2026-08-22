# ---------------------------------------------------------------------------
# Computo en Cloud Run.
#
# VENTAJAS REALES SOBRE LAMBDA
#   - Memoria hasta 32 GiB y 8 vCPU (Lambda: 10.240 MB, 6 vCPU).
#   - Timeout de 60 min en servicios y hasta 7 dias en jobs (Lambda: 15 min).
#   - Sin limite documentado de tamano de imagen (Lambda: 10 GB). Permite
#     hornear ONNX Runtime y varios modelos en una sola imagen.
#   - GPU disponible, con arranque en frio de unos 5 segundos.
#
# TRAMPAS QUE ROMPEN UN PORTE DIRECTO DESDE LAMBDA
#   1. El sistema de archivos escribible es TMPFS y CONSUME MEMORIA. Un
#      adaptador que en Lambda escribe imagenes intermedias en /tmp asumiendo
#      disco, en Cloud Run le esta quitando memoria al modelo.
#   2. La concurrencia por defecto NO es 1. Lambda garantiza una peticion por
#      instancia; Cloud Run admite hasta 1.000. ONNX Runtime con concurrencia
#      alta necesita sesiones seguras entre hilos y control de hilos intra-op, o
#      satura la CPU. Para inferencia pesada, fije concurrencia entre 1 y 4.
#   3. Existe una relacion obligatoria entre vCPU y memoria que no existe en
#      Lambda: 1 vCPU admite hasta 4 GiB; 4 vCPU, de 2 a 16 GiB; 8 vCPU, de 4 a
#      32 GiB.
# ---------------------------------------------------------------------------

locals {
  name = "og-${var.env}"

  common_env = merge(
    {
      ENV                     = var.env
      LOG_LEVEL               = var.log_level
      FIRESTORE_DATABASE      = var.firestore_database_name
      DOCUMENTS_BUCKET        = var.documents_bucket_name
      BIOMETRICS_BUCKET       = var.biometrics_bucket_name
      STAGING_BUCKET          = var.staging_bucket_name
      EVIDENCE_BUCKET         = var.evidence_bucket_name
      PLATFORM_KMS_KEY        = var.platform_kms_key_id
      CAPABILITIES_COLLECTION = var.capabilities_collection
    },
    var.extra_environment,
  )
}

# ---------------------------------------------------------------------------
# Artifact Registry
# ---------------------------------------------------------------------------

resource "google_artifact_registry_repository" "containers" {
  project       = var.project_id
  location      = var.region
  repository_id = "${local.name}-containers"
  description   = "Imagenes de contenedor del middleware de onboarding (${var.env})."
  format        = "DOCKER"

  kms_key_name = var.platform_kms_key_id

  docker_config {
    immutable_tags = true # un tag nunca cambia de digest
  }

  cleanup_policies {
    id     = "keep-recent-releases"
    action = "KEEP"

    most_recent_versions {
      package_name_prefixes = var.image_names
      keep_count            = var.retained_image_count
    }
  }

  cleanup_policies {
    id     = "delete-untagged"
    action = "DELETE"

    condition {
      tag_state  = "UNTAGGED"
      older_than = "604800s" # 7 dias
    }
  }

  labels = var.labels
}

# ---------------------------------------------------------------------------
# Servicios de Cloud Run
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_service" "this" {
  for_each = var.services

  name     = "${local.name}-${each.key}"
  project  = var.project_id
  location = var.region

  description = each.value.description
  ingress     = each.value.ingress

  deletion_protection = var.enable_deletion_protection

  template {
    service_account = var.runtime_service_account_email

    # min_instances mayor que cero elimina el arranque en frio a cambio de pagar
    # instancias inactivas. Para inferencia con modelos horneados en la imagen,
    # el arranque en frio es de segundos y en produccion suele compensar.
    scaling {
      min_instance_count = each.value.min_instances
      max_instance_count = each.value.max_instances
    }

    # Concurrencia: el parametro mas peligroso al portar desde Lambda.
    max_instance_request_concurrency = each.value.concurrency

    timeout = "${each.value.timeout_seconds}s"

    # El arranque en frio se reduce mucho con el impulso de CPU inicial, que
    # solo cuesta durante el arranque.
    dynamic "vpc_access" {
      for_each = each.value.use_direct_vpc_egress && var.vpc_subnet_name != null ? [1] : []
      content {
        # Direct VPC egress: sin recurso intermedio y escala a cero, pero limita
        # las instancias maximas a 100-200 segun region.
        network_interfaces {
          network    = var.vpc_network_name
          subnetwork = var.vpc_subnet_name
        }
        egress = each.value.vpc_egress
      }
    }

    containers {
      name  = each.key
      image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}/${each.value.image_name}:${each.value.image_tag}"

      resources {
        limits = {
          cpu    = each.value.cpu
          memory = each.value.memory
        }

        # Impulso de CPU durante el arranque: mejora mucho la carga de modelos.
        startup_cpu_boost = each.value.startup_cpu_boost

        # false significa CPU asignada solo mientras se procesa una peticion.
        # Para servicios que mantienen una sesion de ONNX viva conviene true.
        cpu_idle = !each.value.always_allocated_cpu
      }

      dynamic "env" {
        for_each = merge(local.common_env, each.value.environment)
        content {
          name  = env.key
          value = env.value
        }
      }

      # Los secretos se montan por referencia y con VERSION FIJA: `latest`
      # provoca cambios de configuracion no auditados.
      dynamic "env" {
        for_each = each.value.secret_environment
        content {
          name = env.key
          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }

      startup_probe {
        initial_delay_seconds = 5
        timeout_seconds       = 5
        period_seconds        = 10
        # El arranque tiene un tope de 4 minutos: un modelo que tarde mas en
        # cargar hara que la instancia se considere fallida.
        failure_threshold = 20

        tcp_socket {
          port = 8080
        }
      }

      liveness_probe {
        initial_delay_seconds = 30
        timeout_seconds       = 5
        period_seconds        = 30
        failure_threshold     = 3

        http_get {
          path = "/healthz"
          port = 8080
        }
      }
    }

    # GPU. La cuota inicial automatica es de 3 L4 (o 3.000 milliGPU) por
    # proyecto; mas requiere solicitud. Una GPU por instancia y facturacion
    # basada en instancia.
    dynamic "node_selector" {
      for_each = each.value.gpu_type == null ? [] : [1]
      content {
        accelerator = each.value.gpu_type
      }
    }
  }

  traffic {
    type    = "TRAFFIC_TARGET_ALLOCATION_TYPE_LATEST"
    percent = 100
  }

  labels = merge(var.labels, { "data-classification" = each.value.data_classification })
}

# Ningun servicio es publico: el acceso llega por API Gateway o por otro
# servicio, siempre con token OIDC.
resource "google_cloud_run_v2_service_iam_member" "invokers" {
  for_each = {
    for pair in flatten([
      for svc_key, svc in var.services : [
        for invoker in svc.invoker_members : {
          key     = "${svc_key}|${invoker}"
          service = svc_key
          member  = invoker
        }
      ]
    ]) : pair.key => pair
  }

  project  = var.project_id
  location = var.region
  name     = google_cloud_run_v2_service.this[each.value.service].name
  role     = "roles/run.invoker"
  member   = each.value.member
}

# ---------------------------------------------------------------------------
# Jobs de Cloud Run
#
# Para trabajo por lotes: reproceso masivo, migraciones, purga programada.
# Timeout de hasta 7 dias y task_count de hasta 10.000, que es como se hace el
# fan-out masivo en GCP al no existir Distributed Map.
# ---------------------------------------------------------------------------

resource "google_cloud_run_v2_job" "this" {
  for_each = var.jobs

  name     = "${local.name}-${each.key}"
  project  = var.project_id
  location = var.region

  deletion_protection = var.enable_deletion_protection

  template {
    parallelism = each.value.parallelism
    task_count  = each.value.task_count

    template {
      service_account = var.runtime_service_account_email
      timeout         = "${each.value.timeout_seconds}s"
      max_retries     = each.value.max_retries

      containers {
        image = "${var.region}-docker.pkg.dev/${var.project_id}/${google_artifact_registry_repository.containers.repository_id}/${each.value.image_name}:${each.value.image_tag}"

        resources {
          limits = {
            cpu    = each.value.cpu
            memory = each.value.memory
          }
        }

        dynamic "env" {
          for_each = merge(local.common_env, each.value.environment)
          content {
            name  = env.key
            value = env.value
          }
        }
      }

      dynamic "vpc_access" {
        for_each = each.value.use_direct_vpc_egress && var.vpc_subnet_name != null ? [1] : []
        content {
          network_interfaces {
            network    = var.vpc_network_name
            subnetwork = var.vpc_subnet_name
          }
          egress = "PRIVATE_RANGES_ONLY"
        }
      }
    }
  }

  labels = var.labels
}
