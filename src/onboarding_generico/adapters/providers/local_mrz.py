"""Lector de MRZ local, sin dependencias externas.

**Nota de licencia.** Este adaptador usa el parser propio de `domain.mrz`, que
implementa ICAO Doc 9303 desde cero. Es una decisión deliberada de licencia,
no de rendimiento:

- `fastmrz` es **AGPL-3.0**: copyleft de red, incompatible con un producto
  propietario expuesto por red.
- `OmniMRZ` tiene una **contradicción** entre su LICENSE (Apache-2.0) y el
  badge de su README (AGPL-3.0), lo que lo hace inutilizable sin aclaración
  del autor.
- `Laligence-Dev/ekyc-system` y `YegorCherov/document-scanner` **no tienen
  licencia**: todos los derechos reservados.
- El backend de Ballerine cae por defecto bajo **Elastic License 2.0**, que
  prohíbe ofrecerlo como servicio gestionado a terceros — exactamente el
  modelo de negocio de este middleware.

Este módulo es, por tanto, **código propio bajo la licencia del proyecto**.

La localización de la MRZ en la imagen sí necesita visión por computador; se
delega en el detector configurable, que por defecto usa el recorte de la
banda inferior según la geometría estándar del documento.
"""

from __future__ import annotations

from typing import Callable

from ...domain.enums import MrzFormat
from ...domain.mrz import MrzRecord, normalize_lines, parse_mrz
from ...domain.value_objects import ObjectRef, TenantId
from ...errors import MrzParseError
from ...ports.mrz_reader import MrzReaderPort
from ...ports.ocr import OcrPort

#: Proporción de la altura del documento ocupada por la banda de la MRZ.
MRZ_BAND_HEIGHT_RATIO: float = 0.22


class LocalMrzReader(MrzReaderPort):
    """Localiza la MRZ con OCR y la parsea con el algoritmo 7-3-1 del dominio.

    El parseo y la verificación de dígitos de control son **reales y
    completos**: es el mismo código que las pruebas ejercitan con los tres
    ejemplos canónicos de ICAO (ERIKSSON ANNA MARIA en TD1, TD2 y TD3).
    """

    __slots__ = ("_ocr", "_locator")

    PROVIDER_ID = "local_mrz"

    def __init__(
        self,
        ocr: OcrPort | None = None,
        locator: Callable[[TenantId, ObjectRef], str] | None = None,
    ) -> None:
        self._ocr = ocr
        self._locator = locator

    def read(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        expected_format: MrzFormat | None = None,
    ) -> MrzRecord:
        if self._locator is not None:
            return self.read_text(self._locator(tenant_id, ref), expected_format=expected_format)
        if self._ocr is None:
            raise MrzParseError(
                "el lector local necesita un puerto de OCR o un localizador configurado",
                provider_id=self.PROVIDER_ID,
            )
        result = self._ocr.detect_text(tenant_id, ref, page="BACK")
        candidate = extract_mrz_lines(result.text)
        if candidate is None:
            raise MrzParseError("no se localizó una MRZ en la imagen", key=ref.key)
        return self.read_text(candidate, expected_format=expected_format)

    def read_text(self, text: str, *, expected_format: MrzFormat | None = None) -> MrzRecord:
        # `strict=False` a propósito: un dígito de control incorrecto no
        # descarta la lectura. Se reporta en `failed_checks` para que el motor
        # de decisión derive a revisión humana en vez de perder los datos.
        return parse_mrz(normalize_lines(text), expected_format=expected_format, strict=False)


def extract_mrz_lines(text: str) -> str | None:
    """Aísla las líneas de MRZ de un volcado de OCR.

    Heurística: la MRZ es el único bloque de líneas consecutivas de longitud
    30, 36 o 44 formadas solo por `A-Z`, `0-9` y `<`. Se buscan grupos de esa
    forma y se devuelve el primero con geometría válida.
    """
    from ...domain.mrz import LINE_LENGTHS, MRZ_ALPHABET

    valid_lengths = {length for lengths in LINE_LENGTHS.values() for length in lengths}
    candidates: list[str] = []
    for raw_line in text.replace("\r", "\n").split("\n"):
        cleaned = "".join(raw_line.split()).upper()
        if not cleaned:
            continue
        if len(cleaned) in valid_lengths and set(cleaned) <= MRZ_ALPHABET:
            candidates.append(cleaned)
        elif candidates and len(candidates) in {2, 3}:
            break

    for size in (3, 2):
        for start in range(len(candidates) - size + 1):
            group = candidates[start : start + size]
            lengths = tuple(len(line) for line in group)
            if any(lengths == expected for expected in LINE_LENGTHS.values()):
                return "\n".join(group)
    return None


def band_locator(band_ratio: float = MRZ_BAND_HEIGHT_RATIO) -> Callable[[TenantId, ObjectRef], str]:
    """Localizador que recorta la banda inferior antes de aplicar OCR.

    Se devuelve como fábrica porque el recorte depende de la geometría del
    documento y esa geometría la fija el catálogo por país y tipo.
    """

    def _locate(tenant_id: TenantId, ref: ObjectRef) -> str:
        raise NotImplementedError(
            "Falta decidir la fuente de la geometría por tipo de documento. Recortar una banda "
            f"fija del {band_ratio:.0%} inferior funciona con pasaportes TD3 pero no con las "
            "tarjetas TD1 de varios emisores LATAM, donde la MRZ ocupa el reverso completo. La "
            "alternativa es un detector entrenado, que arrastra su propia licencia de pesos."
        )

    return _locate



__all__ = ["MRZ_BAND_HEIGHT_RATIO", "LocalMrzReader", "band_locator", "extract_mrz_lines"]
