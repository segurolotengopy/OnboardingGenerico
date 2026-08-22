"""Zona de lectura mecánica (MRZ) según ICAO Doc 9303.

Implementación real, no simulada, de:

- El **dígito de control módulo 10 con pesos 7-3-1** (Doc 9303 Parte 3, §4.9).
- Los **layouts TD1, TD2 y TD3** con sus posiciones exactas.
- El **dígito de control compuesto** con el rango propio de cada formato.
- La aceptación de `<` como dígito de control válido del número personal
  vacío en TD3.
- La **validación cruzada** contra un `IdentityClaimSet` de otra fuente.

Tabla de valores de carácter (Doc 9303 Parte 3, §4.9):

===========  =====================================
Carácter     Valor
===========  =====================================
``0``-``9``  valor nominal
``A``-``Z``  10-35 consecutivos (``A``=10 … ``Z``=35)
``<``        0 (relleno)
===========  =====================================

Rangos del dígito compuesto:

======  =========================================================  ==========
Formato Rangos cubiertos                                           Posición
======  =========================================================  ==========
TD1     L1 pos. 6-30 + L2 pos. 1-7, 9-15, 19-29                    L2 pos. 30
TD2     L2 pos. 1-10 + 14-20 + 22-35                               L2 pos. 36
TD3     L2 pos. 1-10 + 14-20 + 22-43                               L2 pos. 44
======  =========================================================  ==========

En TD1 el compuesto **sí incluye** los datos opcionales de la línea 1
(pos. 16-30). Omitir ese tramo es el error de implementación más frecuente.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

from ..errors import MrzCheckDigitError, MrzParseError
from .enums import DocumentType, MrzFormat, Sex
from .identity import IdentityClaimSet, compare_claims, normalize_name, parse_mrz_date

#: Pesos cíclicos del algoritmo, reiniciados al principio de cada cadena.
WEIGHTS: Final[tuple[int, int, int]] = (7, 3, 1)

#: Carácter de relleno de la MRZ.
FILLER: Final[str] = "<"

#: Alfabeto admitido por la MRZ: 26 letras, 10 dígitos y el relleno.
MRZ_ALPHABET: Final[frozenset[str]] = frozenset("ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789<")

#: Longitud de línea por formato.
LINE_LENGTHS: Final[dict[MrzFormat, tuple[int, ...]]] = {
    MrzFormat.TD1: (30, 30, 30),
    MrzFormat.TD2: (36, 36),
    MrzFormat.TD3: (44, 44),
}

#: Pivote de siglo para la fecha de nacimiento: `YY` > 30 se lee como 19YY.
BIRTH_DATE_PIVOT: Final[int] = 30

#: Pivote para la fecha de expiración: siempre en el siglo XXI.
EXPIRY_DATE_PIVOT: Final[int] = 99


def character_value(char: str) -> int:
    """Valor numérico de un carácter MRZ.

    Lanza `MrzParseError` ante cualquier carácter fuera del alfabeto: aceptar
    un carácter desconocido como 0 haría cuadrar dígitos de control que no
    deberían cuadrar.
    """
    if "0" <= char <= "9":
        return ord(char) - 48
    if "A" <= char <= "Z":
        return ord(char) - 55  # 'A' -> 10
    if char == FILLER:
        return 0
    raise MrzParseError("carácter inválido en la MRZ", position_char=repr(char))


def check_digit(data: str) -> int:
    """Dígito de control módulo 10 con pesos 7-3-1 reiniciados desde el inicio.

    Procedimiento normativo (Doc 9303 Parte 3, §4.9):

    1. Multiplicar cada carácter por el peso de su posición (7, 3, 1, 7, 3, 1…).
    2. Sumar los productos.
    3. Dividir la suma entre 10.
    4. El resto es el dígito de control.

    Ejemplo canónico: ``check_digit("D23145890") == 7`` (documento
    ``D231458907`` del ejemplo ICAO).
    """
    total = 0
    for index, char in enumerate(data):
        total += character_value(char) * WEIGHTS[index % 3]
    return total % 10


def verify_check_digit(data: str, expected: str, *, allow_filler: bool = False) -> bool:
    """Comprueba un dígito de control declarado en la MRZ.

    `allow_filler` habilita la excepción documentada de ICAO para el número
    personal vacío de TD3: cuando el campo son todos `<`, el dígito de la
    posición 43 puede ser `<` en lugar de `0`. Un parser robusto debe aceptar
    ambos.
    """
    if expected == FILLER:
        if not allow_filler:
            return False
        return set(data) <= {FILLER}
    if not expected.isdigit():
        return False
    return check_digit(data) == int(expected)


@dataclass(frozen=True, slots=True)
class MrzField:
    """Campo de la MRZ con su dígito de control declarado y su verificación."""

    name: str
    raw: str
    check_digit_declared: str | None = None
    check_digit_valid: bool | None = None

    @property
    def value(self) -> str:
        """Valor sin el relleno de cola."""
        return self.raw.rstrip(FILLER)


@dataclass(frozen=True, slots=True)
class MrzRecord:
    """Resultado del parseo de una MRZ.

    Es un objeto de valor: no se muta. Contiene PII (nombre, número de
    documento, fechas), de modo que se persiste cifrado y nunca se registra.
    """

    mrz_format: MrzFormat
    lines: tuple[str, ...]
    document_code: str
    issuing_state: str
    document_number: str
    document_number_check: str
    birth_date_raw: str
    birth_date_check: str
    sex_raw: str
    expiry_date_raw: str
    expiry_date_check: str
    nationality: str
    surname: str
    given_names: str
    optional_data_1: str = ""
    optional_data_2: str = ""
    personal_number: str = ""
    personal_number_check: str = ""
    composite_check: str = ""
    check_results: Mapping[str, bool] = field(default_factory=dict)

    # -- Propiedades derivadas -------------------------------------------

    @property
    def is_valid(self) -> bool:
        """`True` si todos los dígitos de control declarados cuadran."""
        return all(self.check_results.values())

    @property
    def failed_checks(self) -> tuple[str, ...]:
        return tuple(sorted(name for name, ok in self.check_results.items() if not ok))

    @property
    def birth_date(self) -> date:
        return parse_mrz_date(self.birth_date_raw, pivot=BIRTH_DATE_PIVOT)

    @property
    def expiry_date(self) -> date:
        return parse_mrz_date(self.expiry_date_raw, pivot=EXPIRY_DATE_PIVOT)

    @property
    def sex(self) -> Sex:
        if self.sex_raw == "M":
            return Sex.MALE
        if self.sex_raw == "F":
            return Sex.FEMALE
        return Sex.UNSPECIFIED

    @property
    def document_type(self) -> DocumentType:
        """Traduce el código de documento de la posición 1 al tipo del catálogo."""
        first = self.document_code[:1]
        if first == "P":
            return DocumentType.PASSPORT
        if first == "I" or first == "A":
            return DocumentType.ID_CARD
        if first == "C":
            return DocumentType.RESIDENCE_PERMIT
        return DocumentType.UNKNOWN

    def to_claims(self) -> IdentityClaimSet:
        """Proyecta la MRZ al conjunto canónico de atributos de identidad."""
        return IdentityClaimSet.create(
            first_name=normalize_name(self.given_names),
            last_name=normalize_name(self.surname),
            id_number=self.document_number,
            birth_date=self.birth_date,
            expiry_date=self.expiry_date,
            issuing_state=self.issuing_state,
            nationality=self.nationality,
            sex=self.sex,
            document_type=self.document_type,
            source="mrz",
        )

    def audit_summary(self) -> dict[str, Any]:
        """Resumen **sin PII**, apto para el log de auditoría y las métricas."""
        return {
            "mrz_format": str(self.mrz_format),
            "document_code": self.document_code,
            "issuing_state": self.issuing_state,
            "nationality": self.nationality,
            "checks_passed": sum(1 for ok in self.check_results.values() if ok),
            "checks_total": len(self.check_results),
            "failed_checks": list(self.failed_checks),
            "is_valid": self.is_valid,
        }


# --------------------------------------------------------------------------
# Normalización de la entrada
# --------------------------------------------------------------------------


def normalize_lines(raw: str | Sequence[str]) -> tuple[str, ...]:
    """Limpia la entrada del OCR y devuelve las líneas de la MRZ.

    Acepta una cadena con saltos de línea o una secuencia de líneas. Elimina
    espacios (el OCR suele meter separaciones falsas), convierte a mayúsculas
    y descarta líneas vacías.
    """
    candidates = raw.replace("\r", "\n").split("\n") if isinstance(raw, str) else list(raw)
    lines = []
    for candidate in candidates:
        cleaned = "".join(str(candidate).split()).upper()
        if cleaned:
            lines.append(cleaned)
    if not lines:
        raise MrzParseError("la MRZ está vacía")
    return tuple(lines)


def detect_format(lines: Sequence[str]) -> MrzFormat:
    """Deduce el formato por número de líneas y longitud."""
    shape = (len(lines), tuple(len(line) for line in lines))
    for mrz_format, lengths in LINE_LENGTHS.items():
        if shape == (len(lengths), lengths):
            return mrz_format
    raise MrzParseError(
        "geometría de MRZ no reconocida: se esperan 3x30 (TD1), 2x36 (TD2) o 2x44 (TD3)",
        line_count=len(lines),
        line_lengths=[len(line) for line in lines],
    )


def _assert_alphabet(lines: Sequence[str]) -> None:
    for index, line in enumerate(lines):
        invalid = sorted(set(line) - MRZ_ALPHABET)
        if invalid:
            raise MrzParseError(
                "caracteres fuera del alfabeto MRZ",
                line_index=index,
                invalid_characters=invalid,
            )


def _split_names(name_field: str) -> tuple[str, str]:
    """Separa el campo de nombre en apellido y nombres.

    El separador normativo es `<<`. Si no aparece (MRZ truncada o mal leída),
    todo el campo se toma como apellido: es preferible a inventar un corte.
    """
    trimmed = name_field.rstrip(FILLER)
    if "<<" in trimmed:
        surname_raw, given_raw = trimmed.split("<<", 1)
    else:
        surname_raw, given_raw = trimmed, ""
    surname = surname_raw.replace(FILLER, " ").strip()
    given = given_raw.replace(FILLER, " ").strip()
    return surname, " ".join(given.split())


# --------------------------------------------------------------------------
# Cálculo del dígito compuesto
# --------------------------------------------------------------------------


def composite_payload(mrz_format: MrzFormat, lines: Sequence[str]) -> str:
    """Concatenación exacta sobre la que se calcula el dígito compuesto.

    Las subcadenas se concatenan **incluyendo sus propios dígitos de control**
    y el esquema 7-3-1 se reinicia desde el peso 7 al inicio de la
    concatenación (no se continúa la secuencia de cada campo por separado).
    """
    if mrz_format is MrzFormat.TD1:
        line1, line2 = lines[0], lines[1]
        # L1 pos. 6-30 (número de documento + su CD + datos opcionales 1),
        # L2 pos. 1-7 (nacimiento + CD), 9-15 (expiración + CD), 19-29 (opcionales 2).
        return line1[5:30] + line2[0:7] + line2[8:15] + line2[18:29]
    if mrz_format is MrzFormat.TD2:
        line2 = lines[1]
        # L2 pos. 1-10 + 14-20 + 22-35.
        return line2[0:10] + line2[13:20] + line2[21:35]
    if mrz_format is MrzFormat.TD3:
        line2 = lines[1]
        # L2 pos. 1-10 + 14-20 + 22-43.
        return line2[0:10] + line2[13:20] + line2[21:43]
    raise MrzParseError("formato de MRZ no soportado", mrz_format=str(mrz_format))


def composite_check_position(mrz_format: MrzFormat) -> tuple[int, int]:
    """Índices (línea, columna) base 0 del dígito compuesto."""
    if mrz_format is MrzFormat.TD1:
        return (1, 29)
    if mrz_format is MrzFormat.TD2:
        return (1, 35)
    return (1, 43)


# --------------------------------------------------------------------------
# Parseo por formato
# --------------------------------------------------------------------------


def _parse_td1(lines: Sequence[str]) -> dict[str, Any]:
    line1, line2, line3 = lines
    surname, given = _split_names(line3)
    return {
        "document_code": line1[0:2],
        "issuing_state": line1[2:5].rstrip(FILLER),
        "document_number": line1[5:14].rstrip(FILLER),
        "document_number_check": line1[14],
        "optional_data_1": line1[15:30].rstrip(FILLER),
        "birth_date_raw": line2[0:6],
        "birth_date_check": line2[6],
        "sex_raw": line2[7],
        "expiry_date_raw": line2[8:14],
        "expiry_date_check": line2[14],
        "nationality": line2[15:18].rstrip(FILLER),
        "optional_data_2": line2[18:29].rstrip(FILLER),
        "composite_check": line2[29],
        "surname": surname,
        "given_names": given,
    }


def _parse_td2(lines: Sequence[str]) -> dict[str, Any]:
    line1, line2 = lines
    surname, given = _split_names(line1[5:36])
    return {
        "document_code": line1[0:2],
        "issuing_state": line1[2:5].rstrip(FILLER),
        "document_number": line2[0:9].rstrip(FILLER),
        "document_number_check": line2[9],
        "nationality": line2[10:13].rstrip(FILLER),
        "birth_date_raw": line2[13:19],
        "birth_date_check": line2[19],
        "sex_raw": line2[20],
        "expiry_date_raw": line2[21:27],
        "expiry_date_check": line2[27],
        "optional_data_1": line2[28:35].rstrip(FILLER),
        "composite_check": line2[35],
        "surname": surname,
        "given_names": given,
    }


def _parse_td3(lines: Sequence[str]) -> dict[str, Any]:
    line1, line2 = lines
    surname, given = _split_names(line1[5:44])
    return {
        "document_code": line1[0:2],
        "issuing_state": line1[2:5].rstrip(FILLER),
        "document_number": line2[0:9].rstrip(FILLER),
        "document_number_check": line2[9],
        "nationality": line2[10:13].rstrip(FILLER),
        "birth_date_raw": line2[13:19],
        "birth_date_check": line2[19],
        "sex_raw": line2[20],
        "expiry_date_raw": line2[21:27],
        "expiry_date_check": line2[27],
        "personal_number": line2[28:42].rstrip(FILLER),
        "personal_number_check": line2[42],
        "composite_check": line2[43],
        "surname": surname,
        "given_names": given,
    }


_PARSERS = {
    MrzFormat.TD1: _parse_td1,
    MrzFormat.TD2: _parse_td2,
    MrzFormat.TD3: _parse_td3,
}


def parse_mrz(
    raw: str | Sequence[str],
    *,
    expected_format: MrzFormat | None = None,
    strict: bool = False,
) -> MrzRecord:
    """Parsea una MRZ y verifica todos sus dígitos de control.

    :param raw: texto de la MRZ, con saltos de línea o como secuencia.
    :param expected_format: si se indica, se exige ese formato.
    :param strict: si es `True`, un dígito de control incorrecto lanza
        `MrzCheckDigitError` en vez de devolver el registro con
        `is_valid == False`. El modo no estricto es el útil en producción:
        permite derivar a revisión humana con el detalle de qué campo falló,
        en vez de perder el resto de los datos leídos.
    """
    lines = normalize_lines(raw)
    _assert_alphabet(lines)
    detected = detect_format(lines)
    if expected_format is not None and detected is not expected_format:
        raise MrzParseError(
            "el formato detectado no coincide con el esperado",
            expected=str(expected_format),
            detected=str(detected),
        )

    fields = _PARSERS[detected](lines)
    checks: dict[str, bool] = {
        "document_number": verify_check_digit(
            _padded_document_number(detected, lines), fields["document_number_check"]
        ),
        "birth_date": verify_check_digit(fields["birth_date_raw"], fields["birth_date_check"]),
        "expiry_date": verify_check_digit(fields["expiry_date_raw"], fields["expiry_date_check"]),
    }

    if detected is MrzFormat.TD3:
        # Excepción ICAO: con número personal vacío, el CD puede ser '<' o '0'.
        personal_raw = lines[1][28:42]
        checks["personal_number"] = verify_check_digit(
            personal_raw, fields["personal_number_check"], allow_filler=True
        )

    checks["composite"] = verify_check_digit(
        composite_payload(detected, lines), fields["composite_check"]
    )

    record = MrzRecord(
        mrz_format=detected,
        lines=lines,
        check_results=checks,
        **fields,
    )

    if strict and not record.is_valid:
        raise MrzCheckDigitError(
            "dígitos de control de la MRZ incorrectos",
            failures=dict.fromkeys(record.failed_checks, "mismatch"),
        )
    return record


def _padded_document_number(mrz_format: MrzFormat, lines: Sequence[str]) -> str:
    """Devuelve el campo de número de documento **con su relleno**.

    El dígito de control se calcula sobre los 9 caracteres del campo,
    incluidos los `<` de relleno, no sobre el valor recortado.
    """
    if mrz_format is MrzFormat.TD1:
        return lines[0][5:14]
    return lines[1][0:9]


# --------------------------------------------------------------------------
# Generación (útil para pruebas y para el emisor de fixtures)
# --------------------------------------------------------------------------


def build_check_digit_string(data: str) -> str:
    """Devuelve el dígito de control como carácter, listo para concatenar."""
    return str(check_digit(data))


# --------------------------------------------------------------------------
# Validación cruzada
# --------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class MrzCrossCheckResult:
    """Resultado de contrastar la MRZ con otra fuente de atributos."""

    mrz_valid: bool
    failed_check_digits: tuple[str, ...]
    discrepancies: tuple[str, ...]
    minor_discrepancies: tuple[str, ...]

    @property
    def is_consistent(self) -> bool:
        """Coherente si la MRZ cuadra y no hay discrepancias mayores."""
        return self.mrz_valid and not self.discrepancies

    def as_dict(self) -> dict[str, Any]:
        """Resumen sin PII: solo nombres de campo, nunca valores."""
        return {
            "mrz_valid": self.mrz_valid,
            "failed_check_digits": list(self.failed_check_digits),
            "discrepancies": list(self.discrepancies),
            "minor_discrepancies": list(self.minor_discrepancies),
            "is_consistent": self.is_consistent,
        }


def cross_check(record: MrzRecord, claims: IdentityClaimSet) -> MrzCrossCheckResult:
    """Contrasta la MRZ con los atributos extraídos por otra vía (OCR o LLM).

    La MRZ es la fuente más fiable porque lleva dígitos de control; una
    discrepancia con el OCR frontal normalmente significa error de OCR, pero
    también puede significar documento alterado. El motor de decisión decide
    qué hacer; aquí solo se reportan los hechos.
    """
    discrepancies = compare_claims(record.to_claims(), claims)
    major = tuple(d.field_name for d in discrepancies if not d.is_minor)
    minor = tuple(d.field_name for d in discrepancies if d.is_minor)
    return MrzCrossCheckResult(
        mrz_valid=record.is_valid,
        failed_check_digits=record.failed_checks,
        discrepancies=major,
        minor_discrepancies=minor,
    )


__all__ = [
    "BIRTH_DATE_PIVOT",
    "EXPIRY_DATE_PIVOT",
    "FILLER",
    "LINE_LENGTHS",
    "MRZ_ALPHABET",
    "WEIGHTS",
    "MrzCrossCheckResult",
    "MrzField",
    "MrzRecord",
    "build_check_digit_string",
    "character_value",
    "check_digit",
    "composite_check_position",
    "composite_payload",
    "cross_check",
    "detect_format",
    "normalize_lines",
    "parse_mrz",
    "verify_check_digit",
]
