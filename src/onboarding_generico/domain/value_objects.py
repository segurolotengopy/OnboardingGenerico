"""Objetos de valor del dominio.

Todos son `@dataclass(frozen=True, slots=True)`: inmutables, comparables por
valor y baratos en memoria. La validación ocurre en `__post_init__`, de modo
que **no existe una instancia inválida**.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any
from uuid import uuid4

from ..errors import ValidationError
from .enums import ArtifactSlot, DataClass, EvidenceKind, Verdict

_TENANT_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
_COUNTRY_RE = re.compile(r"^[A-Z]{2}$")
_URI_RE = re.compile(r"^(s3|gs|mem)://([^/]+)/(.+)$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def utc_now() -> datetime:
    """Instante actual en UTC. Único punto de lectura del reloj del dominio."""
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class TenantId:
    """Identificador del tenant.

    Es **Associated Data del cifrado de sobre**: su formato está restringido
    porque acaba formando parte del AAD y de la clave de partición.
    """

    value: str

    def __post_init__(self) -> None:
        if not _TENANT_RE.match(self.value):
            raise ValidationError(
                "tenant_id inválido: se esperan 2-63 caracteres [a-z0-9-] "
                "que empiecen por alfanumérico",
                field="tenant_id",
            )

    def __str__(self) -> str:
        return self.value

    @property
    def aad(self) -> bytes:
        """Bytes canónicos del AAD derivados del tenant."""
        return f"tenant:{self.value}".encode()


@dataclass(frozen=True, slots=True)
class SessionId:
    """Identificador opaco de la sesión (UUID4 en hexadecimal)."""

    value: str

    def __post_init__(self) -> None:
        if not re.fullmatch(r"[0-9a-f]{32}", self.value):
            raise ValidationError(
                "session_id inválido: se espera UUID4 hex de 32 caracteres", field="session_id"
            )

    def __str__(self) -> str:
        return self.value

    @classmethod
    def generate(cls) -> SessionId:
        return cls(uuid4().hex)


@dataclass(frozen=True, slots=True)
class SubjectRef:
    """Seudónimo estable del titular dentro de un tenant.

    Nunca es el número de documento: es una referencia opaca que el requirente
    controla, de modo que el crypto-shredding pueda operar por titular.
    """

    value: str

    def __post_init__(self) -> None:
        if not 1 <= len(self.value) <= 128:
            raise ValidationError(
                "subject_ref debe tener entre 1 y 128 caracteres", field="subject_ref"
            )

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class CountryCode:
    """Código de país ISO 3166-1 alfa-2, o `*` como comodín en las specs."""

    value: str

    def __post_init__(self) -> None:
        if self.value != "*" and not _COUNTRY_RE.match(self.value):
            raise ValidationError(
                "country_code inválido: se espera ISO 3166-1 alfa-2 o '*'", field="country"
            )

    def __str__(self) -> str:
        return self.value

    @property
    def is_wildcard(self) -> bool:
        return self.value == "*"


@dataclass(frozen=True, slots=True)
class ObjectRef:
    """Puntero a un objeto en el almacén.

    **Ningún binario viaja por el estado del orquestador**: siempre se pasa
    esta referencia. Cloud Workflows tiene un tope de 512 KB acumulados por
    ejecución y Step Functions 256 KiB por payload; un puntero cabe siempre.
    """

    uri: str
    bucket: str
    key: str
    sha256: str
    size_bytes: int = 0
    content_type: str = "application/octet-stream"

    def __post_init__(self) -> None:
        match = _URI_RE.match(self.uri)
        if match is None:
            raise ValidationError(
                "uri de objeto inválida: se espera s3://bucket/key, gs://bucket/key o mem://bucket/key",
                field="uri",
            )
        scheme_bucket, scheme_key = match.group(2), match.group(3)
        if scheme_bucket != self.bucket or scheme_key != self.key:
            raise ValidationError(
                "la uri no concuerda con bucket/key",
                field="uri",
                bucket=self.bucket,
            )
        if not _SHA256_RE.match(self.sha256):
            raise ValidationError(
                "sha256 inválido: se esperan 64 hexadecimales en minúscula", field="sha256"
            )
        if self.size_bytes < 0:
            raise ValidationError("size_bytes no puede ser negativo", field="size_bytes")

    @classmethod
    def build(
        cls,
        *,
        scheme: str,
        bucket: str,
        key: str,
        sha256: str,
        size_bytes: int = 0,
        content_type: str = "application/octet-stream",
    ) -> ObjectRef:
        return cls(
            uri=f"{scheme}://{bucket}/{key}",
            bucket=bucket,
            key=key,
            sha256=sha256,
            size_bytes=size_bytes,
            content_type=content_type,
        )

    @property
    def scheme(self) -> str:
        return self.uri.split("://", 1)[0]

    def as_dict(self) -> dict[str, Any]:
        return {
            "uri": self.uri,
            "bucket": self.bucket,
            "key": self.key,
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "content_type": self.content_type,
        }


@dataclass(frozen=True, slots=True)
class Confidence:
    """Confianza normalizada al intervalo [0, 1]."""

    value: float

    def __post_init__(self) -> None:
        if not 0.0 <= self.value <= 1.0:
            raise ValidationError(
                "la confianza debe estar en [0, 1]", field="confidence", value=self.value
            )

    def __float__(self) -> float:
        return self.value

    def __ge__(self, other: Confidence | float) -> bool:
        return self.value >= float(other)

    def __gt__(self, other: Confidence | float) -> bool:
        return self.value > float(other)

    def __le__(self, other: Confidence | float) -> bool:
        return self.value <= float(other)

    def __lt__(self, other: Confidence | float) -> bool:
        return self.value < float(other)

    def meets(self, threshold: float) -> bool:
        return self.value >= threshold

    @classmethod
    def certain(cls) -> Confidence:
        return cls(1.0)

    @classmethod
    def unknown(cls) -> Confidence:
        return cls(0.0)


@dataclass(frozen=True, slots=True)
class ProviderRef:
    """Proveedor concreto que ejecutó un paso, con su versión de modelo."""

    provider_id: str
    version: str = "unknown"

    def __post_init__(self) -> None:
        if not self.provider_id:
            raise ValidationError("provider_id no puede estar vacío", field="provider_id")

    def __str__(self) -> str:
        return f"{self.provider_id}@{self.version}"


@dataclass(frozen=True, slots=True)
class Artifact:
    """Artefacto cargado por el titular o el requirente."""

    slot: ArtifactSlot
    ref: ObjectRef
    data_class: DataClass
    captured_at: datetime = field(default_factory=utc_now)
    purgeable_from: datetime | None = None

    def __post_init__(self) -> None:
        # I7: un artefacto biométrico exige fecha de purga explícita.
        if self.data_class is DataClass.BIOMETRIC and self.purgeable_from is None:
            raise ValidationError(
                "un artefacto biométrico exige purgeable_from (invariante I7)",
                field="purgeable_from",
                slot=str(self.slot),
            )


@dataclass(frozen=True, slots=True)
class Evidence:
    """Evidencia inmutable emitida por un paso.

    Invariante I3: una vez emitida no se modifica. Corregirla exige emitir
    otra que la supersede, referenciando `supersedes`.
    """

    evidence_id: str
    step_id: str
    kind: EvidenceKind
    provider: ProviderRef
    verdict: Verdict
    scores: Mapping[str, float] = field(default_factory=dict)
    thresholds: Mapping[str, float] = field(default_factory=dict)
    issued_at: datetime = field(default_factory=utc_now)
    supersedes: str | None = None

    @classmethod
    def create(
        cls,
        *,
        step_id: str,
        kind: EvidenceKind,
        provider: ProviderRef,
        verdict: Verdict,
        scores: Mapping[str, float] | None = None,
        thresholds: Mapping[str, float] | None = None,
        supersedes: str | None = None,
    ) -> Evidence:
        return cls(
            evidence_id=uuid4().hex,
            step_id=step_id,
            kind=kind,
            provider=provider,
            verdict=verdict,
            scores=dict(scores or {}),
            thresholds=dict(thresholds or {}),
            supersedes=supersedes,
        )

    def score(self, name: str, default: float = 0.0) -> float:
        return float(self.scores.get(name, default))

    def as_dict(self) -> dict[str, Any]:
        return {
            "evidence_id": self.evidence_id,
            "step_id": self.step_id,
            "kind": str(self.kind),
            "provider": str(self.provider),
            "verdict": str(self.verdict),
            "scores": dict(self.scores),
            "thresholds": dict(self.thresholds),
            "issued_at": self.issued_at.isoformat(),
            "supersedes": self.supersedes,
        }


@dataclass(frozen=True, slots=True)
class ResolutionKey:
    """Clave compuesta de resolución de la especificación de flujo."""

    tenant_id: str
    country: str
    document_type: str
    tier: str = "IAL2"

    def __str__(self) -> str:
        return f"{self.tenant_id}:{self.country}:{self.document_type}:{self.tier}"


@dataclass(frozen=True, slots=True)
class FlowSpecRef:
    """Referencia congelada a la spec con la que se ejecuta una sesión.

    Una republicación posterior no afecta a sesiones en vuelo: sin esto la
    sesión no es auditable (doc 04 §5.3).
    """

    key: str
    version: str
    content_hash: str

    def __post_init__(self) -> None:
        if not self.content_hash.startswith("sha256:"):
            raise ValidationError(
                "content_hash debe llevar el prefijo 'sha256:'", field="content_hash"
            )


__all__ = [
    "Artifact",
    "Confidence",
    "CountryCode",
    "Evidence",
    "FlowSpecRef",
    "ObjectRef",
    "ProviderRef",
    "ResolutionKey",
    "SessionId",
    "SubjectRef",
    "TenantId",
    "utc_now",
]
