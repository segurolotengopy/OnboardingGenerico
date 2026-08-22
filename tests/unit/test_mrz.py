"""Pruebas de ICAO Doc 9303: dígito 7-3-1, layouts y dígito compuesto."""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest

from onboarding_generico.domain.enums import DocumentType, MrzFormat, Sex
from onboarding_generico.domain.identity import IdentityClaimSet
from onboarding_generico.domain.mrz import (
    FILLER,
    character_value,
    check_digit,
    composite_payload,
    cross_check,
    detect_format,
    normalize_lines,
    parse_mrz,
    verify_check_digit,
)
from onboarding_generico.errors import MrzCheckDigitError, MrzParseError

# --------------------------------------------------------------------------
# Algoritmo del dígito de control
# --------------------------------------------------------------------------


def test_character_value_table() -> None:
    """Tabla normativa: dígitos su valor, A-Z de 10 a 35, `<` vale 0."""
    assert character_value("0") == 0
    assert character_value("9") == 9
    assert character_value("A") == 10
    assert character_value("D") == 13
    assert character_value("Z") == 35
    assert character_value(FILLER) == 0


def test_character_value_rejects_unknown() -> None:
    """Un carácter fuera del alfabeto no puede valer 0 por defecto."""
    with pytest.raises(MrzParseError):
        character_value("ñ")
    with pytest.raises(MrzParseError):
        character_value(" ")


def test_check_digit_worked_example() -> None:
    """Ejemplo trabajado de la referencia: D23145890 -> 7."""
    assert check_digit("D23145890") == 7


def test_check_digit_weights_restart_per_string() -> None:
    """Los pesos 7-3-1 se reinician al principio de cada cadena."""
    # 1*7 + 0*3 + 0*1 = 7 -> 7
    assert check_digit("100") == 7
    # Si los pesos no se reiniciaran, este resultado cambiaría.
    assert check_digit("1") == 7
    assert check_digit("0") == 0
    assert check_digit("") == 0


@pytest.mark.parametrize(
    ("data", "expected"),
    [
        ("740812", 2),
        ("120415", 9),
        ("L898902C3", 6),
        ("ZE184226B<<<<<", 1),
        ("<<<<<<<<<<<<<<", 0),
    ],
)
def test_check_digit_vectors(data: str, expected: int) -> None:
    assert check_digit(data) == expected


def test_check_digit_vectors_from_fixture(mrz_samples: dict[str, Any]) -> None:
    for vector in mrz_samples["check_digit_vectors"]:
        assert check_digit(vector["data"]) == vector["expected"], vector["note"]


def test_verify_check_digit_rejects_filler_by_default() -> None:
    assert verify_check_digit("740812", "2") is True
    assert verify_check_digit("740812", "3") is False
    assert verify_check_digit("740812", FILLER) is False


def test_verify_check_digit_accepts_filler_for_empty_personal_number() -> None:
    """Excepción ICAO del número personal vacío en TD3: `<` vale como CD."""
    empty = FILLER * 14
    assert verify_check_digit(empty, FILLER, allow_filler=True) is True
    assert verify_check_digit(empty, "0", allow_filler=True) is True
    # Con contenido real, `<` deja de ser aceptable.
    assert verify_check_digit("ZE184226B<<<<<", FILLER, allow_filler=True) is False


# --------------------------------------------------------------------------
# Ejemplos canónicos: los tres formatos
# --------------------------------------------------------------------------


@pytest.mark.parametrize("key", ["td1", "td2", "td3"])
def test_canonical_examples_all_check_digits_pass(mrz_samples: dict[str, Any], key: str) -> None:
    """Los tres ejemplos ICAO de ERIKSSON ANNA MARIA cuadran por completo."""
    sample = mrz_samples["canonical"][key]
    record = parse_mrz(sample["lines"])
    expected = sample["expected"]

    assert str(record.mrz_format) == expected["format"]
    assert record.is_valid is expected["all_checks_pass"]
    assert record.failed_checks == ()
    assert all(record.check_results.values())

    assert record.document_code == expected["document_code"]
    assert record.issuing_state == expected["issuing_state"]
    assert record.document_number == expected["document_number"]
    assert record.document_number_check == expected["document_number_check"]
    assert record.birth_date_check == expected["birth_date_check"]
    assert record.expiry_date_check == expected["expiry_date_check"]
    assert record.composite_check == expected["composite_check"]
    assert record.nationality == expected["nationality"]
    assert record.surname == expected["surname"]
    assert record.given_names == expected["given_names"]
    assert record.birth_date == date.fromisoformat(expected["birth_date"])
    assert record.expiry_date == date.fromisoformat(expected["expiry_date"])
    assert record.sex is Sex.FEMALE


def test_td3_personal_number_check(mrz_samples: dict[str, Any]) -> None:
    sample = mrz_samples["canonical"]["td3"]["expected"]
    record = parse_mrz(mrz_samples["canonical"]["td3"]["lines"])
    assert record.personal_number == sample["personal_number"]
    assert record.personal_number_check == sample["personal_number_check"]
    assert record.check_results["personal_number"] is True


def test_composite_covers_td1_optional_data_of_line_one() -> None:
    """En TD1 el compuesto incluye los datos opcionales de la línea 1 (pos. 16-30).

    Es el error de implementación más frecuente: omitir ese tramo hace que el
    compuesto cuadre con el ejemplo canónico (relleno) pero falle en cuanto el
    documento lleva datos opcionales reales.
    """
    lines = normalize_lines(
        "I<UTOD231458907ABC123XYZ<<<<<<\n"
        "7408122F1204159UTO<<<<<<<<<<<0\n"
        "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"
    )
    payload = composite_payload(MrzFormat.TD1, lines)
    assert "ABC123XYZ" in payload, "el compuesto TD1 debe cubrir la posición 16-30 de la línea 1"
    assert len(payload) == 50


def test_composite_payload_lengths(mrz_samples: dict[str, Any]) -> None:
    for key, expected_length in (("td1", 50), ("td2", 31), ("td3", 39)):
        lines = normalize_lines(mrz_samples["canonical"][key]["lines"])
        payload = composite_payload(MrzFormat(key.upper()), lines)
        assert len(payload) == expected_length


def test_td3_accepts_filler_check_digit_for_empty_personal_number() -> None:
    """Un TD3 sin número personal se acepta con `<` o con `0` en la posición 43."""
    line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
    body = "L898902C36UTO7408122F1204159" + FILLER * 14

    for personal_check in (FILLER, "0"):
        partial = body + personal_check
        composite = str(check_digit(partial[0:10] + partial[13:20] + partial[21:43]))
        record = parse_mrz([line1, partial + composite])
        assert record.check_results["personal_number"] is True, personal_check
        assert record.is_valid is True
        assert record.personal_number == ""


# --------------------------------------------------------------------------
# Detección de formato y errores
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("key", "expected"),
    [("td1", MrzFormat.TD1), ("td2", MrzFormat.TD2), ("td3", MrzFormat.TD3)],
)
def test_detect_format(mrz_samples: dict[str, Any], key: str, expected: MrzFormat) -> None:
    assert detect_format(normalize_lines(mrz_samples["canonical"][key]["lines"])) is expected


def test_detect_format_rejects_unknown_geometry(mrz_samples: dict[str, Any]) -> None:
    with pytest.raises(MrzParseError) as excinfo:
        parse_mrz(mrz_samples["invalid_geometry"]["lines"])
    assert excinfo.value.code == "OG_MRZ_PARSE"


def test_normalize_lines_strips_ocr_spaces() -> None:
    """El OCR mete espacios espurios; la MRZ no los tiene."""
    lines = normalize_lines(
        "P<UTO ERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
        " L898902C36UTO7408122F1204159ZE184226B<<<<<10"
    )
    assert len(lines[0]) == 44
    assert len(lines[1]) == 44


def test_expected_format_mismatch_raises() -> None:
    with pytest.raises(MrzParseError):
        parse_mrz(
            "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
            "L898902C36UTO7408122F1204159ZE184226B<<<<<10",
            expected_format=MrzFormat.TD1,
        )


def test_corrupted_check_digit_is_reported_not_fatal(mrz_samples: dict[str, Any]) -> None:
    """Modo no estricto: se conservan los datos y se reporta qué falló.

    Es lo correcto en producción: perder el resto de la lectura por un dígito
    obliga a recapturar cuando bastaría con derivar a revisión humana.
    """
    sample = mrz_samples["corrupted"]
    record = parse_mrz(sample["lines"])
    assert record.is_valid is False
    assert record.failed_checks == tuple(sample["expected_failed_checks"])
    assert record.surname == "ERIKSSON"


def test_strict_mode_raises_on_bad_check_digit(mrz_samples: dict[str, Any]) -> None:
    with pytest.raises(MrzCheckDigitError) as excinfo:
        parse_mrz(mrz_samples["corrupted"]["lines"], strict=True)
    assert excinfo.value.code == "OG_MRZ_CHECK_DIGIT"
    assert "document_number" in excinfo.value.details["failures"]


def test_invalid_alphabet_is_rejected() -> None:
    lines = [
        "I<UTOD23145890Ñ<<<<<<<<<<<<<<<",
        "7408122F1204159UTO<<<<<<<<<<<6",
        "ERIKSSON<<ANNA<MARIA<<<<<<<<<<",
    ]
    with pytest.raises(MrzParseError):
        parse_mrz(lines)


# --------------------------------------------------------------------------
# Proyección y validación cruzada
# --------------------------------------------------------------------------


def test_to_claims_projection(mrz_samples: dict[str, Any]) -> None:
    record = parse_mrz(mrz_samples["canonical"]["td3"]["lines"])
    claims = record.to_claims()
    assert claims.first_name == "ANNA MARIA"
    assert claims.last_name == "ERIKSSON"
    assert claims.id_number == "L898902C3"
    assert claims.document_type is DocumentType.PASSPORT
    assert claims.source == "mrz"


def test_document_type_from_code(mrz_samples: dict[str, Any]) -> None:
    assert parse_mrz(mrz_samples["canonical"]["td1"]["lines"]).document_type is DocumentType.ID_CARD
    assert (
        parse_mrz(mrz_samples["canonical"]["td3"]["lines"]).document_type is DocumentType.PASSPORT
    )


def test_audit_summary_has_no_pii(mrz_samples: dict[str, Any]) -> None:
    """El resumen del expediente no puede llevar nombre ni número de documento."""
    record = parse_mrz(mrz_samples["canonical"]["td1"]["lines"])
    summary = record.audit_summary()
    serialized = str(summary)
    assert "ERIKSSON" not in serialized
    assert "D23145890" not in serialized
    assert summary["checks_total"] == 4
    assert summary["is_valid"] is True


def test_cross_check_consistent(mrz_samples: dict[str, Any]) -> None:
    record = parse_mrz(mrz_samples["canonical"]["td1"]["lines"])
    claims = IdentityClaimSet.create(
        first_name="Anna María",
        last_name="Eriksson",
        id_number="D23145890",
        birth_date=date(1974, 8, 12),
        source="ocr",
    )
    result = cross_check(record, claims)
    assert result.is_consistent is True
    assert result.discrepancies == ()


def test_cross_check_detects_major_and_minor(mrz_samples: dict[str, Any]) -> None:
    record = parse_mrz(mrz_samples["canonical"]["td1"]["lines"])
    claims = IdentityClaimSet.create(
        first_name="ANNA MARIA",
        last_name="ERIKSSON",
        id_number="D23145891",  # una sola diferencia: típico error de OCR
        birth_date=date(1980, 1, 1),  # discrepancia mayor
        source="ocr",
    )
    result = cross_check(record, claims)
    assert result.is_consistent is False
    assert "birth_date" in result.discrepancies
    assert "id_number" in result.minor_discrepancies
    assert "D23145890" not in str(result.as_dict())
