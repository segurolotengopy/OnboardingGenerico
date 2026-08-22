"""Adaptadores de proveedores de capacidad.

Cada módulo lleva su **nota de licencia** en el docstring. Resumen de lo que
es y no es utilizable, según la investigación del repositorio:

Utilizables sin fricción
    `@openeudi/*` (Apache-2.0), `minivision-ai/Silent-Face-Anti-Spoofing`
    (Apache-2.0, pero modelo de 2020), `fbieberly/document_warp` y
    `joellijo32/Document-Scanner-using-OpenCV` (MIT, como referencia),
    `team-idswyft/idswyft-community` (MIT), OpenCV (Apache-2.0),
    Tesseract y `pytesseract` (Apache-2.0).

No utilizables
    `fastmrz` (AGPL-3.0: copyleft de red), `Laligence-Dev/ekyc-system` y
    `YegorCherov/document-scanner` (sin licencia), `OmniMRZ` (contradicción
    entre LICENSE Apache-2.0 y badge AGPL-3.0), backend de Ballerine
    (Elastic License 2.0: prohíbe el servicio gestionado a terceros).

Atención aparte
    Varios **pesos de modelos** (InsightFace `buffalo_l`, TruFor) arrastran
    restricciones de uso no comercial **independientes** de la licencia del
    código que los ejecuta.
"""

from __future__ import annotations

from .cv_providers import InsightFaceMatch, OpenCvAlignment, TesseractOcr, TruForForgery
from .local_mrz import LocalMrzReader, extract_mrz_lines
from .saas_liveness_client import SaasLivenessClient

__all__ = [
    "InsightFaceMatch",
    "LocalMrzReader",
    "OpenCvAlignment",
    "SaasLivenessClient",
    "TesseractOcr",
    "TruForForgery",
    "extract_mrz_lines",
]
