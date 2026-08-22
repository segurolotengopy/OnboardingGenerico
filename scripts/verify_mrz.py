#!/usr/bin/env python3
"""Valida una zona de lectura mecánica y explica cada dígito de control.

Cuando un documento se rechaza por MRZ, la pregunta operativa siempre es la
misma: ¿falló el reconocimiento óptico o el documento es inválido? Esta
herramienta separa ambos casos mostrando qué dígito concreto no cuadra.

Uso:
    python scripts/verify_mrz.py "LINEA1" "LINEA2" ["LINEA3"]
    python scripts/verify_mrz.py --ejemplo td3
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "src"))

from onboarding_generico.domain import mrz as mrz_mod  # noqa: E402

# Ejemplos canónicos del Doc 9303 de la OACI. Son ficticios por diseño: el
# titular "ERIKSSON, ANNA MARIA" y el Estado emisor "UTO" (Utopía) no existen.
EJEMPLOS: dict[str, list[str]] = {
    "td1": [
        "I<UTOD231458907<<<<<<<<<<<<<<<",
        "7408122F1204159UTO<<<<<<<<<<<6",
        "ERIKSSON<<ANNA<MARIA<<<<<<<<<<",
    ],
    "td2": [
        "I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<",
        "D231458907UTO7408122F1204159<<<<<<<6",
    ],
    "td3": [
        "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<",
        "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
    ],
}


def main() -> int:
    analizador = argparse.ArgumentParser(description=__doc__)
    analizador.add_argument("lineas", nargs="*", help="Líneas de la MRZ.")
    analizador.add_argument(
        "--ejemplo",
        choices=sorted(EJEMPLOS),
        help="Usa un ejemplo canónico de la OACI en lugar de líneas propias.",
    )
    argumentos = analizador.parse_args()

    lineas = EJEMPLOS[argumentos.ejemplo] if argumentos.ejemplo else argumentos.lineas
    if not lineas:
        analizador.error("Indique las líneas de la MRZ o use --ejemplo.")

    print("Líneas de entrada:")
    for indice, linea in enumerate(lineas, start=1):
        print(f"  {indice}: {linea!r}  ({len(linea)} caracteres)")
    print()

    try:
        registro = mrz_mod.parse_mrz(lineas)
    except Exception as error:  # noqa: BLE001 - herramienta de diagnóstico
        print(f"No se pudo interpretar la MRZ: {error}")
        return 2

    print(f"Formato detectado: {registro.mrz_format}")
    print(f"Estado emisor:     {registro.issuing_state}")
    print(f"Documento:         {registro.document_code} {registro.document_number}")
    print(f"Tipo del catálogo: {registro.document_type}")
    print(f"Titular:           {registro.surname}, {registro.given_names}")
    print(f"Nacimiento:        {registro.birth_date}")
    print(f"Expiración:        {registro.expiry_date}")
    print(f"Nacionalidad:      {registro.nationality}")
    print(f"Sexo:              {registro.sex}")
    print()

    print("Dígitos de control:")
    for nombre, valido in sorted(registro.check_results.items()):
        print(f"  {nombre:<20} {'correcto' if valido else 'INCORRECTO'}")
    todos_validos = registro.is_valid

    print()
    if todos_validos:
        print("Resultado: todos los dígitos de control cuadran.")
        return 0

    print(
        "Resultado: hay dígitos de control que no cuadran.\n"
        "Si el reconocimiento óptico es dudoso, vuelva a capturar antes de\n"
        "concluir que el documento es inválido: la confusión entre 0 y O y\n"
        "entre 1 y I es la causa más frecuente de este fallo."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
