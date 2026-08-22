# ---------------------------------------------------------------------------
# Declaracion unica de versiones para todo el arbol de Terraform / OpenTofu.
#
# Los modulos de este repositorio NO declaran su propio bloque `required_providers`
# de forma deliberada: heredan la configuracion del modulo raiz (cada entorno de
# `envs/`). Este archivo sirve como referencia canonica de las versiones probadas
# y se copia (o se referencia) desde cada entorno.
#
# Compatibilidad: las restricciones usan sintaxis aceptada tanto por Terraform
# como por OpenTofu. No se usan funciones exclusivas de ninguna de las dos
# implementaciones.
# ---------------------------------------------------------------------------

terraform {
  # OpenTofu 1.6 y Terraform 1.6 comparten el mismo lenguaje base.
  required_version = ">= 1.6.0"

  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.60"
    }

    # El provider estable de Google cubre casi todos los recursos usados.
    google = {
      source  = "hashicorp/google"
      version = "~> 6.10"
    }

    # ADVERTENCIA: los recursos `google_api_gateway_*` han vivido historicamente
    # solo en el provider beta. El modulo `modules/gcp/api` los declara con
    # `provider = google-beta`, por lo que este provider es obligatorio si se
    # despliega el arbol de GCP.
    google-beta = {
      source  = "hashicorp/google-beta"
      version = "~> 7.45"
    }

    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.6"
    }

    random = {
      source  = "hashicorp/random"
      version = "~> 3.6"
    }
  }
}
