"""Política criptográfica por atributo.

Tres directivas, tomadas del modelo del AWS Database Encryption SDK:

===================  ===========================================================
Directiva            Semántica
===================  ===========================================================
`ENCRYPT_AND_SIGN`   El valor se cifra y entra en la firma del registro.
`SIGN_ONLY`          El valor viaja **en claro** pero entra en la firma.
`DO_NOTHING`         Ni se cifra ni se firma.
===================  ===========================================================

Consecuencia de diseño que hay que respetar sin excepción: **las claves de
partición y de ordenación son obligatoriamente `SIGN_ONLY`**, es decir, viajan
en claro. Por eso nunca pueden contener PII: una clave de ordenación
``SESSION#<numero_documento>`` anula el cifrado del resto del registro.

`DO_NOTHING` se reserva a metadatos verdaderamente volátiles (contadores de
reintento, marcas de caché). Un atributo `DO_NOTHING` es **modificable por
cualquiera con permiso de escritura sin que la firma lo detecte**, así que la
lista debe mantenerse corta y justificada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Mapping

from ..errors import ValidationError


class CryptoAction(str, Enum):
    """Directiva criptográfica aplicable a un atributo."""

    ENCRYPT_AND_SIGN = "ENCRYPT_AND_SIGN"
    SIGN_ONLY = "SIGN_ONLY"
    DO_NOTHING = "DO_NOTHING"

    def __str__(self) -> str:
        return str(self.value)


#: Atributos que llevan PII y se cifran siempre.
ENCRYPTED_FIELDS: frozenset[str] = frozenset(
    {
        "first_name",
        "last_name",
        "full_name",
        "id_number",
        "birth_date",
        "expiry_date",
        "address",
        "email",
        "phone",
        "mrz_lines",
        "claims",
        "face_embedding",
        "portrait_ref",
        "reviewer_notes",
        "raw_text",
    }
)

#: Atributos estructurales: en claro pero firmados.
SIGNED_FIELDS: frozenset[str] = frozenset(
    {
        "tenant_id",
        "session_id",
        "subject_ref",
        "state",
        "version",
        "country",
        "document_type",
        "tier",
        "spec_key",
        "spec_version",
        "spec_hash",
        "created_at",
        "expires_at",
        "external_ref",
        "decision_outcome",
        "risk_level",
        "evidence_manifest",
    }
)

#: Metadatos volátiles, fuera de la firma. Mantener esta lista corta.
UNPROTECTED_FIELDS: frozenset[str] = frozenset({"cache_hint", "last_seen_at", "retry_hint"})


@dataclass(frozen=True, slots=True)
class FieldPolicy:
    """Mapa atributo → directiva, con acción por defecto para lo desconocido."""

    directives: Mapping[str, CryptoAction] = field(default_factory=dict)
    default_action: CryptoAction = CryptoAction.ENCRYPT_AND_SIGN

    def action_for(self, field_name: str) -> CryptoAction:
        """Directiva del atributo.

        El **valor por defecto es cifrar**: un campo nuevo que nadie clasificó
        se protege en vez de filtrarse. Es la elección segura ante el olvido.
        """
        return self.directives.get(field_name, self.default_action)

    def encrypted_fields(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, a in self.directives.items() if a is CryptoAction.ENCRYPT_AND_SIGN))

    def signed_fields(self) -> tuple[str, ...]:
        return tuple(sorted(n for n, a in self.directives.items() if a is CryptoAction.SIGN_ONLY))

    def assert_keys_are_safe(self, key_attributes: Iterable[str]) -> None:
        """Verifica que ninguna clave de índice se cifra ni lleva PII.

        Una clave `ENCRYPT_AND_SIGN` es directamente inviable (el almacén
        necesita leerla en claro), y una clave con PII anula el cifrado.
        """
        for name in key_attributes:
            action = self.action_for(name)
            if action is CryptoAction.ENCRYPT_AND_SIGN:
                raise ValidationError(
                    "una clave de índice no puede ser ENCRYPT_AND_SIGN; debe ser SIGN_ONLY sin PII",
                    field=name,
                )
            if name in ENCRYPTED_FIELDS:
                raise ValidationError(
                    "una clave de índice no puede contener PII",
                    field=name,
                )

    def with_overrides(self, overrides: Mapping[str, CryptoAction]) -> FieldPolicy:
        """Devuelve una política nueva con directivas adicionales por tenant."""
        merged = dict(self.directives)
        merged.update(overrides)
        return FieldPolicy(directives=merged, default_action=self.default_action)


def default_policy() -> FieldPolicy:
    """Política estándar del middleware."""
    directives: dict[str, CryptoAction] = {}
    for name in ENCRYPTED_FIELDS:
        directives[name] = CryptoAction.ENCRYPT_AND_SIGN
    for name in SIGNED_FIELDS:
        directives[name] = CryptoAction.SIGN_ONLY
    for name in UNPROTECTED_FIELDS:
        directives[name] = CryptoAction.DO_NOTHING
    return FieldPolicy(directives=directives)


def apply_policy(policy: FieldPolicy, item: Mapping[str, object]) -> dict[str, list[str]]:
    """Clasifica los atributos de un registro según la política.

    Útil para las pruebas de arquitectura y para el informe de cumplimiento:
    permite afirmar que ningún campo PII acabó en `sign_only` o `unprotected`.
    """
    buckets: dict[str, list[str]] = {"encrypt": [], "sign_only": [], "unprotected": []}
    for name in item:
        action = policy.action_for(name)
        if action is CryptoAction.ENCRYPT_AND_SIGN:
            buckets["encrypt"].append(name)
        elif action is CryptoAction.SIGN_ONLY:
            buckets["sign_only"].append(name)
        else:
            buckets["unprotected"].append(name)
    return {key: sorted(values) for key, values in buckets.items()}


__all__ = [
    "ENCRYPTED_FIELDS",
    "SIGNED_FIELDS",
    "UNPROTECTED_FIELDS",
    "CryptoAction",
    "FieldPolicy",
    "apply_policy",
    "default_policy",
]
