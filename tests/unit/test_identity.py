"""Pruebas de normalización canónica de identidad y objetos de valor."""

from __future__ import annotations

from datetime import date

import pytest

from onboarding_generico.domain.enums import DocumentType, Sex
from onboarding_generico.domain.identity import (
    IdentityClaimSet,
    compare_claims,
    format_mrz_date,
    normalize_id_number,
    normalize_name,
    normalize_text,
    parse_mrz_date,
)
from onboarding_generico.domain.value_objects import (
    Confidence,
    CountryCode,
    ObjectRef,
    SessionId,
    TenantId,
)
from onboarding_generico.errors import ValidationError


# --------------------------------------------------------------------------
# Normalización
# --------------------------------------------------------------------------


def test_normalize_text_strips_diacritics_and_uppercases() -> None:
    assert normalize_text("José Muñoz") == "JOSE MUNOZ"
    assert normalize_text("  doble   espacio ") == "DOBLE ESPACIO"


def test_normalize_name_replaces_mrz_filler() -> None:
    assert normalize_name("ERIKSSON<<ANNA<MARIA<<<") == "ERIKSSON ANNA MARIA"


def test_normalize_id_number_drops_separators() -> None:
    assert normalize_id_number("D-231.458/90") == "D23145890"
    assert normalize_id_number("D23145890<<<<") == "D23145890"


def test_parse_mrz_date_century_pivot() -> None:
    """Sin siglo en la MRZ: `YY<=pivot` es 20YY y el resto 19YY."""
    assert parse_mrz_date("740812", pivot=30) == date(1974, 8, 12)
    assert parse_mrz_date("050101", pivot=30) == date(2005, 1, 1)
    # Con pivote 99 (fecha de expiración) todo cae en el siglo XXI.
    assert parse_mrz_date("740812", pivot=99) == date(2074, 8, 12)


def test_parse_mrz_date_rejects_invalid() -> None:
    with pytest.raises(ValidationError):
        parse_mrz_date("741312")
    with pytest.raises(ValidationError):
        parse_mrz_date("7408")


def test_format_mrz_date_roundtrip() -> None:
    assert format_mrz_date(date(1974, 8, 12)) == "740812"


# --------------------------------------------------------------------------
# IdentityClaimSet
# --------------------------------------------------------------------------


def test_create_normalizes_all_fields() -> None:
    claims = IdentityClaimSet.create(
        first_name="José  María",
        last_name="Muñoz<<Pérez",
        id_number="d-231.458/90",
        issuing_state="mex",
        nationality="mex",
        sex="male",
        document_type="ine_2019",
    )
    assert claims.first_name == "JOSE MARIA"
    assert claims.last_name == "MUNOZ PEREZ"
    assert claims.id_number == "D23145890"
    assert claims.issuing_state == "MEX"
    assert claims.sex is Sex.MALE
    assert claims.document_type is DocumentType.INE_2019
    assert claims.full_name == "JOSE MARIA MUNOZ PEREZ"


def test_from_mapping_accepts_iso_and_mrz_dates() -> None:
    iso = IdentityClaimSet.from_mapping({"birth_date": "1974-08-12"})
    mrz = IdentityClaimSet.from_mapping({"birth_date": "740812"})
    assert iso.birth_date == date(1974, 8, 12)
    assert mrz.birth_date == date(2074, 8, 12)


def test_from_mapping_unknown_document_type_is_unknown_not_error() -> None:
    claims = IdentityClaimSet.from_mapping({"document_type": "CEDULA_MARCIANA"})
    assert claims.document_type is DocumentType.UNKNOWN


def test_is_expired_and_age_at() -> None:
    claims = IdentityClaimSet.create(
        birth_date=date(1990, 6, 15), expiry_date=date(2024, 1, 1)
    )
    assert claims.is_expired(as_of=date(2026, 1, 1)) is True
    assert claims.is_expired(as_of=date(2023, 1, 1)) is False
    assert claims.age_at(date(2026, 6, 14)) == 35
    assert claims.age_at(date(2026, 6, 15)) == 36
    assert IdentityClaimSet.create().age_at(date(2026, 1, 1)) is None


def test_merged_with_fills_gaps_without_overwriting() -> None:
    left = IdentityClaimSet.create(first_name="ANNA", source="mrz")
    right = IdentityClaimSet.create(first_name="OTRA", last_name="ERIKSSON", source="ocr")
    merged = left.merged_with(right)
    assert merged.first_name == "ANNA"
    assert merged.last_name == "ERIKSSON"
    assert merged.source == "mrz+ocr"


# --------------------------------------------------------------------------
# Comparación
# --------------------------------------------------------------------------


def test_compare_ignores_fields_absent_on_one_side() -> None:
    """La MRZ no lleva domicilio; el OCR frontal no siempre lleva nacionalidad."""
    left = IdentityClaimSet.create(first_name="ANNA", nationality="UTO")
    right = IdentityClaimSet.create(first_name="ANNA")
    assert compare_claims(left, right) == ()


def test_compare_ignores_name_particles() -> None:
    left = IdentityClaimSet.create(last_name="DE LA CRUZ")
    right = IdentityClaimSet.create(last_name="CRUZ")
    assert compare_claims(left, right) == ()


def test_compare_flags_single_character_difference_as_minor() -> None:
    left = IdentityClaimSet.create(id_number="D23145890")
    right = IdentityClaimSet.create(id_number="D23145891")
    discrepancies = compare_claims(left, right)
    assert len(discrepancies) == 1
    assert discrepancies[0].is_minor is True
    assert discrepancies[0].field_name == "id_number"


def test_discrepancy_carries_no_values() -> None:
    """La discrepancia va al expediente: no puede llevar el valor en claro."""
    left = IdentityClaimSet.create(id_number="D23145890")
    right = IdentityClaimSet.create(id_number="ZZ99999999")
    discrepancy = compare_claims(left, right)[0]
    serialized = str(discrepancy)
    assert "D23145890" not in serialized
    assert "ZZ99999999" not in serialized


# --------------------------------------------------------------------------
# Objetos de valor
# --------------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["", "A", "Acme", "acme_1", "-acme", "x" * 64])
def test_tenant_id_rejects_invalid(bad: str) -> None:
    with pytest.raises(ValidationError):
        TenantId(bad)


def test_tenant_id_aad_is_canonical() -> None:
    assert TenantId("acme").aad == b"tenant:acme"


def test_session_id_generate_and_validate() -> None:
    session_id = SessionId.generate()
    assert len(session_id.value) == 32
    with pytest.raises(ValidationError):
        SessionId("no-es-un-uuid")


def test_country_code_wildcard() -> None:
    assert CountryCode("*").is_wildcard is True
    assert CountryCode("MX").is_wildcard is False
    with pytest.raises(ValidationError):
        CountryCode("mx")


def test_object_ref_requires_matching_uri() -> None:
    digest = "a" * 64
    ref = ObjectRef.build(scheme="s3", bucket="b", key="k/1", sha256=digest)
    assert ref.uri == "s3://b/k/1"
    assert ref.scheme == "s3"
    with pytest.raises(ValidationError):
        ObjectRef(uri="s3://otro/k/1", bucket="b", key="k/1", sha256=digest)
    with pytest.raises(ValidationError):
        ObjectRef(uri="s3://b/k/1", bucket="b", key="k/1", sha256="corto")


def test_confidence_bounds_and_comparison() -> None:
    assert Confidence(0.9).meets(0.85) is True
    assert Confidence(0.5) < Confidence(0.6)
    assert float(Confidence.certain()) == 1.0
    with pytest.raises(ValidationError):
        Confidence(1.5)
