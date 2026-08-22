"""Conjunto canónico de atributos de identidad y su normalización.

El middleware recibe atributos de fuentes heterogéneas (OCR, MRZ, LLM
multimodal, registro oficial) y necesita compararlas entre sí. Sin una forma
canónica, la comparación cruzada produce falsos positivos por acentos,
apellidos compuestos, ceros a la izquierda o formatos de fecha distintos.

`IdentityClaimSet` es esa forma canónica. Es **PII**: nunca se registra en
logs y siempre se persiste cifrado.
"""

from __future__ import annotations

import unicodedata
from dataclasses import dataclass, field, replace
from datetime import date
from typing import Any, Iterable, Mapping

from ..errors import ValidationError
from .enums import DocumentType, Sex

#: Campos que participan en la comparación cruzada MRZ ↔ OCR ↔ registro.
COMPARABLE_FIELDS: tuple[str, ...] = (
    "first_name",
    "last_name",
    "id_number",
    "birth_date",
    "expiry_date",
    "issuing_state",
    "nationality",
    "sex",
    "document_type",
)

#: Partículas de apellido que se conservan pero no aportan a la comparación.
NAME_PARTICLES: frozenset[str] = frozenset({"DE", "DEL", "LA", "LAS", "LOS", "DA", "DOS", "VAN", "VON", "DI"})


def normalize_text(value: str) -> str:
    """Mayúsculas ASCII sin diacríticos y con espacios colapsados.

    La MRZ es ASCII de 37 símbolos (A-Z, 0-9, `<`), así que comparar con OCR
    exige llevar ambos lados al mismo alfabeto. `Ñ` se transcribe a `N`, que
    es lo que hace la propia MRZ.
    """
    decomposed = unicodedata.normalize("NFKD", value)
    stripped = "".join(ch for ch in decomposed if not unicodedata.combining(ch))
    upper = stripped.upper()
    cleaned = "".join(ch if ch.isalnum() or ch in " -'" else " " for ch in upper)
    return " ".join(cleaned.split())


def normalize_name(value: str) -> str:
    """Normaliza un nombre y sustituye los separadores MRZ `<` por espacios."""
    return normalize_text(value.replace("<", " "))


def normalize_id_number(value: str) -> str:
    """Normaliza un número de documento: sin separadores ni relleno MRZ."""
    text = normalize_text(value).replace("<", "")
    return "".join(ch for ch in text if ch.isalnum())


def parse_mrz_date(yymmdd: str, *, pivot: int = 30) -> date:
    """Convierte `YYMMDD` de la MRZ a fecha.

    ICAO no codifica el siglo. Se aplica la convención habitual de pivote:
    con `pivot=30`, `YY <= 30` se interpreta como 20YY y el resto como 19YY.
    El pivote es un parámetro porque la elección correcta depende de si el
    campo es fecha de nacimiento o de expiración.
    """
    if len(yymmdd) != 6 or not yymmdd.isdigit():
        raise ValidationError("fecha MRZ inválida: se esperan 6 dígitos YYMMDD", field="mrz_date")
    yy, mm, dd = int(yymmdd[0:2]), int(yymmdd[2:4]), int(yymmdd[4:6])
    year = 2000 + yy if yy <= pivot else 1900 + yy
    try:
        return date(year, mm, dd)
    except ValueError as exc:
        raise ValidationError("fecha MRZ inválida: día o mes fuera de rango", field="mrz_date") from exc


def format_mrz_date(value: date) -> str:
    """Serializa una fecha al formato `YYMMDD` de la MRZ."""
    return f"{value.year % 100:02d}{value.month:02d}{value.day:02d}"


@dataclass(frozen=True, slots=True)
class IdentityClaimSet:
    """Atributos de identidad ya normalizados.

    Se construye siempre con `create()` o `from_mapping()`, que aplican la
    normalización. El constructor directo asume que los valores ya vienen
    canónicos (lo usa `replace()` internamente).
    """

    first_name: str = ""
    last_name: str = ""
    id_number: str = ""
    birth_date: date | None = None
    expiry_date: date | None = None
    issuing_state: str = ""
    nationality: str = ""
    sex: Sex = Sex.UNSPECIFIED
    document_type: DocumentType = DocumentType.UNKNOWN
    #: Confianza por campo, cuando la fuente la proporciona (OCR, LLM).
    field_confidence: Mapping[str, float] = field(default_factory=dict)
    #: Identificador de la fuente: `mrz`, `ocr`, `llm`, `registry`, `subject`.
    source: str = "unknown"

    @classmethod
    def create(
        cls,
        *,
        first_name: str = "",
        last_name: str = "",
        id_number: str = "",
        birth_date: date | None = None,
        expiry_date: date | None = None,
        issuing_state: str = "",
        nationality: str = "",
        sex: Sex | str = Sex.UNSPECIFIED,
        document_type: DocumentType | str = DocumentType.UNKNOWN,
        field_confidence: Mapping[str, float] | None = None,
        source: str = "unknown",
    ) -> IdentityClaimSet:
        """Construye el conjunto aplicando la normalización canónica."""
        return cls(
            first_name=normalize_name(first_name),
            last_name=normalize_name(last_name),
            id_number=normalize_id_number(id_number),
            birth_date=birth_date,
            expiry_date=expiry_date,
            issuing_state=normalize_text(issuing_state).replace(" ", ""),
            nationality=normalize_text(nationality).replace(" ", ""),
            sex=_coerce_sex(sex),
            document_type=_coerce_document_type(document_type),
            field_confidence=dict(field_confidence or {}),
            source=source,
        )

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any], *, source: str = "unknown") -> IdentityClaimSet:
        """Construye desde un diccionario (salida de OCR o del LLM).

        Las fechas se aceptan como `date`, como ISO `YYYY-MM-DD` o como
        `YYMMDD` de MRZ.
        """
        return cls.create(
            first_name=str(data.get("first_name", "") or ""),
            last_name=str(data.get("last_name", "") or ""),
            id_number=str(data.get("id_number", "") or ""),
            birth_date=_coerce_date(data.get("birth_date"), pivot=99),
            expiry_date=_coerce_date(data.get("expiry_date"), pivot=99),
            issuing_state=str(data.get("issuing_state", "") or ""),
            nationality=str(data.get("nationality", "") or ""),
            sex=data.get("sex", Sex.UNSPECIFIED) or Sex.UNSPECIFIED,
            document_type=data.get("document_type", DocumentType.UNKNOWN) or DocumentType.UNKNOWN,
            field_confidence=data.get("field_confidence") or {},
            source=str(data.get("source", source)),
        )

    @property
    def full_name(self) -> str:
        return " ".join(part for part in (self.first_name, self.last_name) if part)

    def is_expired(self, *, as_of: date) -> bool:
        """`True` si el documento está caducado en la fecha indicada."""
        return self.expiry_date is not None and self.expiry_date < as_of

    def age_at(self, as_of: date) -> int | None:
        """Edad cumplida en la fecha indicada, o `None` si falta la fecha."""
        if self.birth_date is None:
            return None
        years = as_of.year - self.birth_date.year
        if (as_of.month, as_of.day) < (self.birth_date.month, self.birth_date.day):
            years -= 1
        return years

    def with_source(self, source: str) -> IdentityClaimSet:
        return replace(self, source=source)

    def as_dict(self) -> dict[str, Any]:
        """Diccionario serializable. **Contiene PII**: nunca va a un log."""
        return {
            "first_name": self.first_name,
            "last_name": self.last_name,
            "id_number": self.id_number,
            "birth_date": self.birth_date.isoformat() if self.birth_date else None,
            "expiry_date": self.expiry_date.isoformat() if self.expiry_date else None,
            "issuing_state": self.issuing_state,
            "nationality": self.nationality,
            "sex": str(self.sex),
            "document_type": str(self.document_type),
            "source": self.source,
        }

    def merged_with(self, other: IdentityClaimSet) -> IdentityClaimSet:
        """Completa los campos vacíos con los de `other`, sin sobrescribir."""
        return IdentityClaimSet(
            first_name=self.first_name or other.first_name,
            last_name=self.last_name or other.last_name,
            id_number=self.id_number or other.id_number,
            birth_date=self.birth_date or other.birth_date,
            expiry_date=self.expiry_date or other.expiry_date,
            issuing_state=self.issuing_state or other.issuing_state,
            nationality=self.nationality or other.nationality,
            sex=self.sex if self.sex is not Sex.UNSPECIFIED else other.sex,
            document_type=(
                self.document_type
                if self.document_type is not DocumentType.UNKNOWN
                else other.document_type
            ),
            field_confidence={**dict(other.field_confidence), **dict(self.field_confidence)},
            source=f"{self.source}+{other.source}",
        )


@dataclass(frozen=True, slots=True)
class FieldDiscrepancy:
    """Diferencia detectada en un campo entre dos fuentes.

    No lleva los valores en claro: lleva su longitud y un indicador de si la
    diferencia es de solo un carácter, lo que basta para triar el caso sin
    exponer PII en el expediente de auditoría.
    """

    field_name: str
    left_source: str
    right_source: str
    left_present: bool
    right_present: bool
    edit_distance: int

    @property
    def is_minor(self) -> bool:
        """Diferencia de un solo carácter: típico error de OCR (`0`/`O`, `1`/`I`)."""
        return self.edit_distance == 1


def _levenshtein(left: str, right: str, *, cap: int = 8) -> int:
    """Distancia de edición acotada; `cap` evita coste cuadrático en cadenas largas."""
    if left == right:
        return 0
    if abs(len(left) - len(right)) > cap:
        return cap
    previous = list(range(len(right) + 1))
    for i, lch in enumerate(left, start=1):
        current = [i]
        for j, rch in enumerate(right, start=1):
            current.append(
                min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (lch != rch))
            )
        previous = current
    return min(previous[-1], cap)


def compare_claims(
    left: IdentityClaimSet,
    right: IdentityClaimSet,
    *,
    fields: Iterable[str] = COMPARABLE_FIELDS,
) -> tuple[FieldDiscrepancy, ...]:
    """Compara dos conjuntos de atributos y devuelve las discrepancias.

    Un campo ausente en una de las fuentes **no** es discrepancia: la MRZ no
    lleva domicilio y el OCR frontal no siempre lleva nacionalidad. Solo se
    comparan campos presentes en ambos lados.
    """
    discrepancies: list[FieldDiscrepancy] = []
    for name in fields:
        left_value = _comparable_value(left, name)
        right_value = _comparable_value(right, name)
        left_present = bool(left_value)
        right_present = bool(right_value)
        if not (left_present and right_present):
            continue
        if left_value == right_value:
            continue
        discrepancies.append(
            FieldDiscrepancy(
                field_name=name,
                left_source=left.source,
                right_source=right.source,
                left_present=left_present,
                right_present=right_present,
                edit_distance=_levenshtein(left_value, right_value),
            )
        )
    return tuple(discrepancies)


def _comparable_value(claims: IdentityClaimSet, name: str) -> str:
    value = getattr(claims, name, None)
    if value is None:
        return ""
    if isinstance(value, date):
        return value.isoformat()
    if name in {"first_name", "last_name"}:
        # Se ignoran las partículas para no marcar "DE LA CRUZ" vs "DELACRUZ".
        parts = [p for p in str(value).split() if p not in NAME_PARTICLES]
        return " ".join(parts)
    if name == "sex" and value is Sex.UNSPECIFIED:
        return ""
    if name == "document_type" and value is DocumentType.UNKNOWN:
        return ""
    return str(value)


def _coerce_sex(value: Sex | str) -> Sex:
    if isinstance(value, Sex):
        return value
    token = str(value).strip().upper()
    if token in {"M", "MALE", "H"}:
        return Sex.MALE
    if token in {"F", "FEMALE"}:
        return Sex.FEMALE
    return Sex.UNSPECIFIED


def _coerce_document_type(value: DocumentType | str) -> DocumentType:
    if isinstance(value, DocumentType):
        return value
    token = str(value).strip().upper()
    try:
        return DocumentType(token)
    except ValueError:
        return DocumentType.UNKNOWN


def _coerce_date(value: Any, *, pivot: int) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if len(text) == 6 and text.isdigit():
        return parse_mrz_date(text, pivot=pivot)
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise ValidationError("fecha inválida: se espera ISO YYYY-MM-DD o YYMMDD", field="date") from exc


__all__ = [
    "COMPARABLE_FIELDS",
    "FieldDiscrepancy",
    "IdentityClaimSet",
    "compare_claims",
    "format_mrz_date",
    "normalize_id_number",
    "normalize_name",
    "normalize_text",
    "parse_mrz_date",
]
