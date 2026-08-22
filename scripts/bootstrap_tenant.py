#!/usr/bin/env python3
"""Genera el plan de alta de un inquilino nuevo.

El alta de un inquilino toca cinco sistemas que deben quedar coherentes entre
sí: la clave de cifrado, el proveedor de identidad, el rol con etiquetas de
sesión, el Registro de Capacidades y el plan de uso del gateway. Hacerlo a mano
es la vía más corta a un inquilino que existe a medias.

Este script **no ejecuta nada**: emite el plan, los fragmentos de configuración
y la lista de verificación. La ejecución pasa por Terraform y por revisión, como
cualquier otro cambio de infraestructura.

Uso:
    python scripts/bootstrap_tenant.py --tenant-id BANCO_X --nombre "Banco X" \\
        --entorno dev --nube aws --paises BO,PY --tier pool
"""

from __future__ import annotations

import argparse
import json
import re
import sys

PATRON_TENANT = re.compile(r"^[A-Z][A-Z0-9_]{2,63}$")


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("--tenant-id", required=True, help="Identificador en MAYÚSCULAS.")
    analizador.add_argument("--nombre", required=True, help="Razón social del cliente.")
    analizador.add_argument("--entorno", default="dev", choices=["dev", "stg", "prd"])
    analizador.add_argument("--nube", default="aws", choices=["aws", "gcp"])
    analizador.add_argument("--paises", default="", help="Códigos ISO separados por coma, p. ej. BO,PY,MX")
    analizador.add_argument(
        "--tier",
        default="pool",
        choices=["pool", "bridge", "silo"],
        help=(
            "pool: recursos compartidos con aislamiento lógico y criptográfico. "
            "bridge: datos compartidos, clave dedicada. "
            "silo: base de datos o proyecto dedicado, para clientes que lo exigen por contrato."
        ),
    )
    argumentos = analizador.parse_args()

    if not PATRON_TENANT.match(argumentos.tenant_id):
        print(
            "El identificador debe ir en MAYÚSCULAS, empezar por letra y usar solo "
            "letras, dígitos y guion bajo (3 a 64 caracteres)."
        )
        return 2

    tenant = argumentos.tenant_id
    entorno = argumentos.entorno
    paises = [p.strip().upper() for p in argumentos.paises.split(",") if p.strip()]

    print(f"Plan de alta — inquilino {tenant} ({argumentos.nombre})")
    print(f"Entorno: {entorno} | Nube: {argumentos.nube} | Modelo de aislamiento: {argumentos.tier}")
    print("=" * 78)

    print("\n1. Clave de cifrado dedicada")
    if argumentos.nube == "aws":
        print(f"   Alias esperado: alias/og-{entorno}-tenant-{tenant.lower()}")
        print("   Rotación anual habilitada. La ventana de borrado determina el plazo real")
        print("   de la destrucción criptográfica: acuérdela con el cliente antes de crearla.")
    else:
        print(f"   Clave esperada: og-{entorno}/tenant-{tenant.lower()} en el llavero regional")
        print("   Cloud KMS no permite destrucción inmediata: la duración programada de")
        print("   destrucción fija el plazo mínimo del compromiso de borrado.")

    print("\n2. Añadir el inquilino al mapa de Terraform")
    bloque = {
        tenant: {
            "display_name": argumentos.nombre,
            "isolation_tier": argumentos.tier,
            "countries": paises,
            "rate_limit_rps": 25 if entorno != "prd" else 100,
            "burst_limit": 50 if entorno != "prd" else 200,
        }
    }
    print("   En infra/terraform/envs/%s/terraform.tfvars, dentro de `tenants`:" % entorno)
    print("   " + json.dumps(bloque, indent=2, ensure_ascii=False).replace("\n", "\n   "))

    print("\n3. Proveedor de identidad")
    if argumentos.nube == "aws":
        print(f"   Grupo de Cognito: og-{entorno}-{tenant.lower()}")
        print(f"   El disparador de pre-generación de token debe emitir TenantID={tenant}")
        print("   Verificación obligatoria: un token sin asignación de inquilino NO debe emitirse.")
    else:
        print(f"   Inquilino de Identity Platform: og-{entorno}-{tenant.lower()}")
        print(f"   Reclamo personalizado: tenant_id={tenant}")

    print("\n4. Registro de Capacidades")
    print("   Habilite las capacidades contratadas para este inquilino. Recuerde que una")
    print("   capacidad no listada en `allowedTenants` se rechaza en la resolución del")
    print("   flujo, no en tiempo de ejecución: el fallo es temprano y explícito.")
    for pais in paises or ["<país>"]:
        print(f"     - Especificación de flujo para {pais}")
        if pais == "BO":
            print("       decisionIssuer debe ser SIGNALS_ONLY (art. 32(II) del Instructivo UIF).")

    print("\n5. Verificación posterior al alta")
    verificaciones = [
        "Un token del inquilino nuevo lee y escribe únicamente sus propios registros.",
        f"Un token de otro inquilino recibe 404 al pedir un recurso de {tenant}.",
        "Un descifrado con el identificador de otro inquilino como dato asociado FALLA.",
        "El plan de uso aplica el límite de tasa acordado.",
        "Una sesión de prueba de extremo a extremo llega a decisión.",
        "La cadena de auditoría de esa sesión verifica correctamente.",
    ]
    for indice, verificacion in enumerate(verificaciones, start=1):
        print(f"   [ ] {indice}. {verificacion}")

    print(
        "\nLa segunda y la tercera verificación no son opcionales: son las únicas que "
        "\ndemuestran que el aislamiento funciona. Un inquilino que 'parece' funcionar "
        "\nporque sus propias consultas devuelven datos no prueba absolutamente nada."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
