"""Puerto de lectura de MRZ.

La distinción importante: **localizar** la MRZ en la imagen es un problema de
visión por computador (proveedor), mientras que **parsearla y validarla** es
lógica de dominio pura, implementada en `domain.mrz` con el algoritmo 7-3-1 de
ICAO 9303. Este puerto cubre solo la primera mitad; el adaptador local
(`adapters.providers.local_mrz`) une ambas.

Nota de licencias: `fastmrz` es AGPL-3.0 (copyleft de red, incompatible con un
producto propietario expuesto por red) y `OmniMRZ` tiene una contradicción
entre su LICENSE (Apache-2.0) y el badge de su README (AGPL-3.0). El parser
propio de `domain.mrz` evita ambos problemas.
"""

from __future__ import annotations

import abc

from ..domain.enums import MrzFormat
from ..domain.mrz import MrzRecord
from ..domain.value_objects import ObjectRef, TenantId


class MrzReaderPort(abc.ABC):
    """Localiza y decodifica la zona de lectura mecánica."""

    @abc.abstractmethod
    def read(
        self,
        tenant_id: TenantId,
        ref: ObjectRef,
        *,
        expected_format: MrzFormat | None = None,
    ) -> MrzRecord:
        """Lee la MRZ de la imagen y devuelve el registro ya verificado.

        No lanza por dígitos de control incorrectos: devuelve el registro con
        `is_valid == False` y el detalle en `failed_checks`, para que el motor
        de decisión derive a revisión humana en vez de perder los datos.
        """

    @abc.abstractmethod
    def read_text(self, text: str, *, expected_format: MrzFormat | None = None) -> MrzRecord:
        """Parsea una MRZ ya extraída como texto por otro paso (OCR)."""


__all__ = ["MrzReaderPort"]
