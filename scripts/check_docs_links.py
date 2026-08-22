#!/usr/bin/env python3
"""Verifica que ningún enlace relativo de la documentación esté roto.

Un enlace roto en la documentación de arquitectura no es un detalle cosmético:
es la ruta por la que alguien buscaba la justificación de una decisión y no la
encontró. Este control corre en integración continua sobre cada cambio a `docs/`.

Uso:
    python scripts/check_docs_links.py [--raiz .]

Salida:
    0 si todos los enlaces relativos resuelven; 1 en caso contrario, con el
    listado de archivo, línea y destino no encontrado.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

# Captura enlaces markdown en línea: [texto](destino)
PATRON_ENLACE = re.compile(r"\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")

# Los enlaces que empiezan por estos prefijos son externos o intra-documento y
# no se resuelven contra el sistema de archivos.
PREFIJOS_IGNORADOS = ("http://", "https://", "mailto:", "#", "tel:", "data:")

# Directorios que no se recorren.
DIRECTORIOS_EXCLUIDOS = {".git", ".venv", "node_modules", "__pycache__", ".terraform"}


def archivos_markdown(raiz: Path) -> list[Path]:
    """Devuelve todos los archivos markdown del repositorio, en orden estable."""
    resultado = [
        ruta
        for ruta in raiz.rglob("*.md")
        if not any(parte in DIRECTORIOS_EXCLUIDOS for parte in ruta.parts)
    ]
    return sorted(resultado)


def destino_existe(origen: Path, destino: str, raiz: Path) -> bool:
    """Resuelve un destino relativo y decide si apunta a algo real.

    Se descarta el fragmento (`#seccion`) porque no se verifica la existencia de
    anclas: hacerlo requeriría interpretar la generación de identificadores de
    encabezado de cada renderizador, que difiere entre GitHub y otros visores.
    """
    ruta_limpia = destino.split("#", 1)[0]
    if not ruta_limpia:
        return True

    if ruta_limpia.startswith("/"):
        candidato = raiz / ruta_limpia.lstrip("/")
    else:
        candidato = (origen.parent / ruta_limpia).resolve()

    return candidato.exists()


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument(
        "--raiz",
        type=Path,
        default=Path(__file__).resolve().parent.parent,
        help="Raíz del repositorio.",
    )
    argumentos = analizador.parse_args()
    raiz: Path = argumentos.raiz.resolve()

    rotos: list[tuple[Path, int, str]] = []
    total_enlaces = 0

    for archivo in archivos_markdown(raiz):
        try:
            lineas = archivo.read_text(encoding="utf-8").splitlines()
        except UnicodeDecodeError:
            print(f"AVISO: no se pudo leer {archivo.relative_to(raiz)} como UTF-8")
            continue

        dentro_de_bloque = False
        for numero, linea in enumerate(lineas, start=1):
            # Los bloques de código contienen ejemplos de rutas que no deben resolverse.
            if linea.lstrip().startswith("```"):
                dentro_de_bloque = not dentro_de_bloque
                continue
            if dentro_de_bloque:
                continue

            for destino in PATRON_ENLACE.findall(linea):
                if destino.startswith(PREFIJOS_IGNORADOS):
                    continue
                total_enlaces += 1
                if not destino_existe(archivo, destino, raiz):
                    rotos.append((archivo.relative_to(raiz), numero, destino))

    if rotos:
        print(f"Enlaces relativos rotos: {len(rotos)} de {total_enlaces} verificados\n")
        for archivo, numero, destino in rotos:
            # Formato reconocido por las anotaciones de GitHub Actions.
            print(f"::error file={archivo},line={numero}::Enlace roto: {destino}")
        return 1

    print(f"Correcto: {total_enlaces} enlaces relativos resuelven.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
