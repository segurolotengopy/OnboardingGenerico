#!/usr/bin/env python3
"""Valida una especificación de flujo antes de publicarla en el Registro de Capacidades.

Publicar una especificación inválida no rompe el despliegue: rompe las
transacciones de un inquilino en producción, y lo hace en el peor momento. Este
control se ejecuta antes de escribir en el registro, no después.

Verifica tres cosas distintas:

1. Conformidad con `api/schemas/flow-spec.schema.json` (estructura).
2. Coherencia del grafo de pasos: identificadores únicos, dependencias
   existentes y ausencia de ciclos.
3. Coherencia semántica: que los artefactos exigidos por cada paso puedan
   haberse aportado, y que un flujo que declara IAL2 incluya al menos una
   verificación biométrica con detección de vivacidad.

La tercera verificación es la que más errores atrapa en la práctica, y es la
única que ninguna herramienta genérica de esquemas puede hacer por usted.

Uso:
    python scripts/validate_flow_spec.py tests/fixtures/flow_standard_ekyc_latam.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

RAIZ = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RAIZ / "src"))

ARTEFACTOS_VALIDOS = {
    "DOC_FRONT",
    "DOC_BACK",
    "SELFIE",
    "LIVENESS_VIDEO",
    "PROOF_OF_ADDRESS",
}


def validar_grafo(pasos: list[dict]) -> list[str]:
    """Comprueba unicidad de identificadores, dependencias y aciclicidad."""
    errores: list[str] = []
    identificadores = [p.get("id") for p in pasos]

    duplicados = {i for i in identificadores if identificadores.count(i) > 1}
    for duplicado in sorted(d for d in duplicados if d):
        errores.append(f"El identificador de paso '{duplicado}' está repetido.")

    conocidos = set(identificadores)
    aristas: dict[str, list[str]] = {}
    for paso in pasos:
        origen = paso.get("id", "")
        dependencias = paso.get("depends_on", []) or []
        aristas[origen] = list(dependencias)
        for dependencia in dependencias:
            if dependencia not in conocidos:
                errores.append(
                    f"El paso '{origen}' depende de '{dependencia}', que no existe en el flujo."
                )

    # Detección de ciclos por recorrido en profundidad con marcado tricolor.
    BLANCO, GRIS, NEGRO = 0, 1, 2
    color = dict.fromkeys(aristas, BLANCO)

    def visitar(nodo: str, camino: tuple[str, ...]) -> None:
        color[nodo] = GRIS
        for vecino in aristas.get(nodo, []):
            if vecino not in color:
                continue
            if color[vecino] == GRIS:
                ciclo = " -> ".join([*camino, nodo, vecino])
                errores.append(f"Ciclo de dependencias detectado: {ciclo}")
            elif color[vecino] == BLANCO:
                visitar(vecino, (*camino, nodo))
        color[nodo] = NEGRO

    for nodo in list(aristas):
        if color[nodo] == BLANCO:
            visitar(nodo, ())

    return errores


def validar_semantica(spec: dict) -> list[str]:
    """Verificaciones que dependen del significado del flujo, no de su forma."""
    errores: list[str] = []
    pasos = spec.get("steps", [])
    capacidades = {p.get("capability", "") for p in pasos}
    declarados = {a.get("slot") for a in spec.get("required_artifacts", [])}

    for paso in pasos:
        for referencia in (paso.get("inputs", {}) or {}).values():
            if not isinstance(referencia, str):
                continue
            for slot in re.findall(r"\$\{artifacts\.([A-Z_]+)\.", referencia):
                if slot not in ARTEFACTOS_VALIDOS:
                    errores.append(
                        f"El paso '{paso.get('id')}' referencia el artefacto desconocido '{slot}'."
                    )
                elif slot not in declarados:
                    errores.append(
                        f"El paso '{paso.get('id')}' usa el artefacto '{slot}', que no figura "
                        "en required_artifacts: nunca llegará a estar disponible."
                    )

    niveles = set(spec.get("resolution", {}).get("tiers", []))
    if niveles & {"IAL2", "IAL3"}:
        tiene_facematch = any(c.startswith("biometrics.facematch") for c in capacidades)
        tiene_liveness = any(c.startswith("biometrics.liveness") for c in capacidades)
        if not (tiene_facematch and tiene_liveness):
            errores.append(
                f"El flujo declara {sorted(niveles)} pero no incluye emparejamiento "
                "facial con detección de vivacidad. Declarar un nivel de aseguramiento que "
                "los pasos no sustentan es una afirmación falsa ante el regulador."
            )

    if spec.get("decision_policy", {}).get("issuer") == "MIDDLEWARE":
        paises = set(spec.get("resolution", {}).get("countries", []))
        if "BO" in paises:
            errores.append(
                "El flujo cubre Bolivia con decisionIssuer=MIDDLEWARE. El art. 32(II) del "
                "Instructivo UIF prohíbe delegar la debida diligencia: use SIGNALS_ONLY."
            )

    retencion = spec.get("retention", {})
    if retencion.get("biometric_retention_days", 0) > retencion.get("kyc_file_retention_days", 0):
        errores.append(
            "La retención biométrica supera la del expediente KYC. Los datos biométricos "
            "deben minimizarse: no están cubiertos por la obligación de conservación AML."
        )

    return errores


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("archivo", type=Path, help="Especificación de flujo en JSON.")
    argumentos = analizador.parse_args()

    try:
        spec = json.loads(argumentos.archivo.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"No se pudo leer la especificación: {error}")
        return 2

    errores: list[str] = []

    # 1. Estructura. Se usa el validador del propio núcleo, que es el mismo que
    #    correrá en producción, en lugar de una biblioteca externa: así el
    #    resultado de este script y el del middleware nunca divergen.
    try:
        from onboarding_generico.composer.spec import FlowSpec

        parsed = FlowSpec.parse(spec)
    except ImportError:
        print("AVISO: no se pudo importar el validador del núcleo; se omite la verificación estructural.")
    except Exception as error:  # noqa: BLE001 - se reporta al usuario
        errores.append(f"Estructura inválida: {error}")

    # 2 y 3. Grafo y semántica.
    errores.extend(validar_grafo(spec.get("steps", [])))
    errores.extend(validar_semantica(spec))

    nombre = spec.get("metadata", {}).get("name", "(sin nombre)")
    version = spec.get("metadata", {}).get("version", "?")

    if errores:
        print(f"Especificación '{nombre}' versión {version}: {len(errores)} problema(s)\n")
        for error in errores:
            print(f"  - {error}")
        return 1

    print(
        f"Especificación '{nombre}' versión {version}: válida.\n"
        f"  Pasos: {len(spec.get('steps', []))}\n"
        f"  Emisor de la decisión: {spec.get('decision_policy', {}).get('issuer')}\n"
        f"  Niveles declarados: {spec.get('resolution', {}).get('tiers') or 'no declarado'}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
