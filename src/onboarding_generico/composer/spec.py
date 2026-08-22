"""Especificación de flujo: modelo y parseo con errores precisos.

Una especificación describe **qué** pasos ejecutar para una combinación de
tenant, país, tipo de documento y tier, no **cómo** ejecutarlos. El "cómo" lo
produce el compilador (`compiler.py`) para cada orquestador.

Principio de los mensajes de error: cada fallo indica la **ruta exacta** del
campo (`steps[2].thresholds.similarity_min`) y qué se esperaba. Una spec la
escribe un ingeniero de integración, no el autor del motor; un error de
publicación con "campo inválido" a secas es inservible.

Reglas estructurales que se comprueban aquí (V1):

- `apiVersion` y `kind` fijos.
- `metadata.version` en semver estricto (la spec es inmutable por versión).
- Identificadores de paso únicos y no vacíos.
- Capacidades del catálogo, con rango de versión opcional (``@^1.4``).
- Los pasos declaran dependencias por identificador; la aciclicidad la
  verifica el validador (V4), no el parser.
"""

from __future__ import annotations

import json
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..domain.enums import (
    ArtifactSlot,
    Capability,
    DataClass,
    DecisionIssuer,
    DecisionOutcome,
    OnFailure,
    WaitClass,
)
from ..errors import SpecValidationError

API_VERSION: str = "og.flow/v1"
KIND: str = "FlowSpec"

_SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
_STEP_ID_RE = re.compile(r"^[a-z][a-z0-9_]{1,63}$")
_CAPABILITY_RE = re.compile(
    r"^(?P<id>[a-z][a-z0-9._]*\.v\d+)(?:@(?P<range>[\^~]?\d+\.\d+(?:\.\d+)?))?$"
)


def _require(data: Mapping[str, Any], key: str, path: str, expected: str) -> Any:
    if key not in data:
        raise SpecValidationError(
            f"falta el campo obligatorio '{key}' ({expected})", check="V1", path=f"{path}.{key}"
        )
    return data[key]


def _require_type(value: Any, kind: type | tuple[type, ...], path: str, expected: str) -> Any:
    if not isinstance(value, kind):
        raise SpecValidationError(
            f"tipo inválido: se esperaba {expected} y llegó {type(value).__name__}",
            check="V1",
            path=path,
        )
    return value


def _require_str_list(value: Any, path: str) -> tuple[str, ...]:
    _require_type(value, (list, tuple), path, "una lista de cadenas")
    for index, item in enumerate(value):
        _require_type(item, str, f"{path}[{index}]", "una cadena")
    return tuple(value)


def _require_number_map(value: Any, path: str) -> dict[str, float]:
    _require_type(value, dict, path, "un objeto de umbrales numéricos")
    result: dict[str, float] = {}
    for name, raw in value.items():
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise SpecValidationError(
                "los umbrales deben ser numéricos", check="V1", path=f"{path}.{name}"
            )
        result[str(name)] = float(raw)
    return result


def _parse_enum(enum_cls: Any, raw: Any, path: str) -> Any:
    _require_type(raw, str, path, "una cadena")
    try:
        return enum_cls(raw)
    except ValueError as exc:
        allowed = sorted(member.value for member in enum_cls)
        raise SpecValidationError(
            f"valor no admitido '{raw}'; se admiten: {', '.join(allowed)}",
            check="V1",
            path=path,
        ) from exc


@dataclass(frozen=True, slots=True)
class CapabilityRef:
    """Referencia a una capacidad con rango de versión opcional.

    El rango (``^1.4``) se resuelve a una versión concreta **en la
    publicación** y queda congelado en el artefacto compilado: una sesión
    ejecutada con la spec v3.2.1 usa exactamente las versiones vigentes al
    publicarla, aunque después salgan otras. Es requisito de trazabilidad.
    """

    capability: Capability
    version_range: str = ""

    def __str__(self) -> str:
        return (
            f"{self.capability}@{self.version_range}"
            if self.version_range
            else str(self.capability)
        )

    @classmethod
    def parse(cls, raw: str, path: str) -> CapabilityRef:
        match = _CAPABILITY_RE.match(raw)
        if match is None:
            raise SpecValidationError(
                "referencia de capacidad mal formada; se espera "
                "'ocr.document.v1' u 'ocr.document.v1@^1.4'",
                check="V1",
                path=path,
            )
        try:
            capability = Capability(match.group("id"))
        except ValueError as exc:
            known = ", ".join(sorted(c.value for c in Capability))
            raise SpecValidationError(
                f"capacidad desconocida '{match.group('id')}'; el catálogo contiene: {known}",
                check="V2",
                path=path,
            ) from exc
        return cls(capability=capability, version_range=match.group("range") or "")


@dataclass(frozen=True, slots=True)
class RetryPolicy:
    """Política de reintentos de un paso."""

    max_attempts: int = 0
    base_ms: int = 200
    jitter: str = "full"

    @classmethod
    def parse(cls, raw: Any, path: str) -> RetryPolicy:
        if raw is None:
            return cls()
        _require_type(raw, dict, path, "un objeto de política de reintentos")
        max_attempts = raw.get("max", 0)
        if not isinstance(max_attempts, int) or isinstance(max_attempts, bool) or max_attempts < 0:
            raise SpecValidationError(
                "'max' debe ser un entero no negativo", check="V1", path=f"{path}.max"
            )
        if max_attempts > 10:
            raise SpecValidationError(
                "'max' por encima de 10 dispara la estimación de eventos de historial "
                "(límite de 25.000 por ejecución en Step Functions Standard)",
                check="V1",
                path=f"{path}.max",
            )
        jitter = raw.get("jitter", "full")
        if jitter not in {"full", "none", "equal"}:
            raise SpecValidationError(
                "'jitter' debe ser 'full', 'equal' o 'none'", check="V1", path=f"{path}.jitter"
            )
        return cls(
            max_attempts=max_attempts, base_ms=int(raw.get("base_ms", 200)), jitter=str(jitter)
        )


@dataclass(frozen=True, slots=True)
class ArtifactSpec:
    """Ranura de artefacto que el requirente debe llenar."""

    slot: ArtifactSlot
    mime_types: tuple[str, ...]
    max_bytes: int
    data_class: DataClass
    purge_after_decision: bool = False

    @classmethod
    def parse(cls, raw: Any, path: str) -> ArtifactSpec:
        _require_type(raw, dict, path, "un objeto de artefacto")
        slot = _parse_enum(
            ArtifactSlot, _require(raw, "slot", path, "ranura del artefacto"), f"{path}.slot"
        )
        mime_types = _require_str_list(
            _require(raw, "mime_types", path, "lista de tipos MIME aceptados"), f"{path}.mime_types"
        )
        if not mime_types:
            raise SpecValidationError(
                "hay que declarar al menos un tipo MIME", check="V1", path=f"{path}.mime_types"
            )
        max_bytes = _require(raw, "max_bytes", path, "tamaño máximo en bytes")
        if not isinstance(max_bytes, int) or isinstance(max_bytes, bool) or max_bytes <= 0:
            raise SpecValidationError(
                "'max_bytes' debe ser un entero positivo", check="V1", path=f"{path}.max_bytes"
            )
        data_class = _parse_enum(
            DataClass, _require(raw, "data_class", path, "clase de dato"), f"{path}.data_class"
        )
        purge = bool(raw.get("purge_after_decision", data_class is DataClass.BIOMETRIC))
        if data_class is DataClass.BIOMETRIC and not purge:
            raise SpecValidationError(
                "un artefacto biométrico exige 'purge_after_decision: true' (invariante I7 y "
                "minimización del art. 25 del GDPR)",
                check="V1",
                path=f"{path}.purge_after_decision",
            )
        return cls(
            slot=slot,
            mime_types=mime_types,
            max_bytes=max_bytes,
            data_class=data_class,
            purge_after_decision=purge,
        )


@dataclass(frozen=True, slots=True)
class StepSpec:
    """Paso declarado en la especificación."""

    step_id: str
    capability: CapabilityRef
    depends_on: tuple[str, ...] = ()
    provider: str = ""
    fallback_provider: tuple[str, ...] = ()
    inputs: Mapping[str, Any] = field(default_factory=dict)
    thresholds: Mapping[str, float] = field(default_factory=dict)
    retries: RetryPolicy = field(default_factory=RetryPolicy)
    required: bool = True
    on_failure: OnFailure = OnFailure.ABORT
    wait: WaitClass = WaitClass.NONE
    compensable: bool = True

    @classmethod
    def parse(cls, raw: Any, path: str) -> StepSpec:
        _require_type(raw, dict, path, "un objeto de paso")
        step_id = _require(raw, "id", path, "identificador único del paso")
        _require_type(step_id, str, f"{path}.id", "una cadena")
        if not _STEP_ID_RE.match(step_id):
            raise SpecValidationError(
                "identificador de paso inválido: 2-64 caracteres [a-z0-9_] empezando por letra",
                check="V1",
                path=f"{path}.id",
            )
        capability = CapabilityRef.parse(
            _require_type(
                _require(raw, "capability", path, "capacidad del catálogo"),
                str,
                f"{path}.capability",
                "una cadena",
            ),
            f"{path}.capability",
        )
        fallback_raw = raw.get("fallback_provider", ())
        # Anotación explícita: sin ella mypy fija el tipo en la primera rama
        # (`tuple[str]`, exactamente un elemento) y rechaza la lista de la
        # segunda. La lista de respaldo tiene longitud arbitraria.
        fallback: tuple[str, ...]
        if isinstance(fallback_raw, str):
            fallback = (fallback_raw,)
        else:
            fallback = _require_str_list(fallback_raw, f"{path}.fallback_provider")

        wait = (
            _parse_enum(WaitClass, raw["wait"], f"{path}.wait") if "wait" in raw else WaitClass.NONE
        )
        on_failure = (
            _parse_enum(OnFailure, raw["on_failure"], f"{path}.on_failure")
            if "on_failure" in raw
            else OnFailure.ABORT
        )
        compensable = bool(raw.get("compensable", True))

        # El PAD no se degrada: un paso de liveness no admite cadena de reserva.
        if capability.capability is Capability.BIOMETRICS_LIVENESS and fallback:
            raise SpecValidationError(
                "un paso de liveness no admite 'fallback_provider': el PAD no se degrada a un "
                "proveedor sin certificación iBeta",
                check="V1",
                path=f"{path}.fallback_provider",
            )

        return cls(
            step_id=step_id,
            capability=capability,
            depends_on=_require_str_list(raw.get("depends_on", ()), f"{path}.depends_on"),
            provider=str(raw.get("provider", "")),
            fallback_provider=fallback,
            inputs=dict(_require_type(raw.get("inputs", {}), dict, f"{path}.inputs", "un objeto")),
            thresholds=_require_number_map(raw.get("thresholds", {}), f"{path}.thresholds"),
            retries=RetryPolicy.parse(raw.get("retries"), f"{path}.retries"),
            required=bool(raw.get("required", True)),
            on_failure=on_failure,
            wait=wait,
            compensable=compensable,
        )

    @property
    def provider_chain(self) -> tuple[str, ...]:
        """Cadena efectiva de proveedores: primario seguido de las reservas."""
        chain = (self.provider,) if self.provider else ()
        return chain + tuple(p for p in self.fallback_provider if p != self.provider)


@dataclass(frozen=True, slots=True)
class DecisionRule:
    """Regla de la política de veredicto."""

    when: str
    then: DecisionOutcome
    reason: str

    @classmethod
    def parse(cls, raw: Any, path: str) -> DecisionRule:
        _require_type(raw, dict, path, "un objeto de regla")
        return cls(
            when=str(_require(raw, "when", path, "condición de la regla")),
            then=_parse_enum(
                DecisionOutcome, _require(raw, "then", path, "veredicto"), f"{path}.then"
            ),
            reason=str(_require(raw, "reason", path, "código de motivo estable")),
        )


@dataclass(frozen=True, slots=True)
class DecisionPolicy:
    """Política de veredicto de la especificación."""

    issuer: DecisionIssuer
    default_outcome: DecisionOutcome
    rules: tuple[DecisionRule, ...] = ()

    @classmethod
    def parse(cls, raw: Any, path: str) -> DecisionPolicy:
        _require_type(raw, dict, path, "un objeto de política de veredicto")
        issuer = _parse_enum(
            DecisionIssuer, _require(raw, "issuer", path, "emisor del veredicto"), f"{path}.issuer"
        )
        default_outcome = _parse_enum(
            DecisionOutcome,
            _require(raw, "default", path, "veredicto por defecto (la política debe ser total)"),
            f"{path}.default",
        )
        rules_raw = _require_type(
            raw.get("rules", []), list, f"{path}.rules", "una lista de reglas"
        )
        rules = tuple(
            DecisionRule.parse(item, f"{path}.rules[{index}]")
            for index, item in enumerate(rules_raw)
        )
        return cls(issuer=issuer, default_outcome=default_outcome, rules=rules)


@dataclass(frozen=True, slots=True)
class ResolutionSpec:
    """Clave de resolución compuesta y prioridad de desempate."""

    countries: tuple[str, ...]
    document_types: tuple[str, ...]
    tiers: tuple[str, ...]
    priority: int = 0

    @classmethod
    def parse(cls, raw: Any, path: str) -> ResolutionSpec:
        _require_type(raw, dict, path, "un objeto de resolución")
        countries = _require_str_list(
            _require(raw, "countries", path, "países cubiertos o ['*']"), f"{path}.countries"
        )
        documents = _require_str_list(
            _require(raw, "document_types", path, "tipos de documento o ['*']"),
            f"{path}.document_types",
        )
        tiers = _require_str_list(raw.get("tiers", ["IAL2"]), f"{path}.tiers")
        if not countries or not documents:
            raise SpecValidationError(
                "'countries' y 'document_types' no pueden estar vacíos", check="V1", path=path
            )
        for index, country in enumerate(countries):
            if country != "*" and not re.fullmatch(r"[A-Z]{2}", country):
                raise SpecValidationError(
                    "código de país inválido: ISO 3166-1 alfa-2 en mayúsculas o '*'",
                    check="V1",
                    path=f"{path}.countries[{index}]",
                )
        priority = raw.get("priority", 0)
        if not isinstance(priority, int) or isinstance(priority, bool):
            raise SpecValidationError(
                "'priority' debe ser un entero", check="V1", path=f"{path}.priority"
            )
        return cls(countries=countries, document_types=documents, tiers=tiers, priority=priority)

    @property
    def specificity(self) -> int:
        """Especificidad: cuántas dimensiones están fijadas sin comodín.

        **La especificidad manda sobre la prioridad**: una spec con
        ``countries: [MX]`` gana a una con ``countries: ['*']``
        independientemente del valor de `priority`.
        """
        score = 0
        score += 0 if "*" in self.countries else 4
        score += 0 if "*" in self.document_types else 2
        score += 0 if "*" in self.tiers else 1
        return score

    def matches(self, *, country: str, document_type: str, tier: str) -> bool:
        return (
            (country in self.countries or "*" in self.countries)
            and (document_type in self.document_types or "*" in self.document_types)
            and (tier in self.tiers or "*" in self.tiers)
        )


@dataclass(frozen=True, slots=True)
class FlowSpec:
    """Especificación de flujo completa e inmutable."""

    name: str
    tenant: str
    version: str
    description: str
    resolution: ResolutionSpec
    required_artifacts: tuple[ArtifactSpec, ...]
    steps: tuple[StepSpec, ...]
    decision_policy: DecisionPolicy
    retention_inherits_from: str = "tenant"
    content_hash: str = ""

    # -- Consultas --------------------------------------------------------

    @property
    def key(self) -> str:
        """Clave de la spec en el registro."""
        return f"{self.tenant}:{self.name}"

    def step(self, step_id: str) -> StepSpec:
        for candidate in self.steps:
            if candidate.step_id == step_id:
                return candidate
        raise SpecValidationError(f"paso inexistente '{step_id}'", check="V4", path="steps")

    @property
    def step_ids(self) -> tuple[str, ...]:
        return tuple(s.step_id for s in self.steps)

    def artifact(self, slot: ArtifactSlot) -> ArtifactSpec | None:
        for candidate in self.required_artifacts:
            if candidate.slot is slot:
                return candidate
        return None

    # -- Parseo -----------------------------------------------------------

    @classmethod
    def parse(cls, document: Mapping[str, Any]) -> FlowSpec:
        """Parsea y valida estructuralmente (comprobación V1)."""
        _require_type(document, Mapping, "$", "un objeto")
        api_version = _require(document, "apiVersion", "$", f"'{API_VERSION}'")
        if api_version != API_VERSION:
            raise SpecValidationError(
                f"apiVersion no soportada '{api_version}'; se espera '{API_VERSION}'",
                check="V1",
                path="$.apiVersion",
            )
        kind = _require(document, "kind", "$", f"'{KIND}'")
        if kind != KIND:
            raise SpecValidationError(
                f"kind no soportado '{kind}'; se espera '{KIND}'", check="V1", path="$.kind"
            )

        metadata = _require_type(
            _require(document, "metadata", "$", "metadatos de la spec"),
            dict,
            "$.metadata",
            "un objeto",
        )
        name = str(_require(metadata, "name", "$.metadata", "nombre de la spec"))
        version = str(_require(metadata, "version", "$.metadata", "versión semver"))
        if not _SEMVER_RE.match(version):
            raise SpecValidationError(
                "la versión debe ser semver estricto MAJOR.MINOR.PATCH sin prefijos",
                check="V1",
                path="$.metadata.version",
            )

        artifacts_raw = _require_type(
            _require(document, "required_artifacts", "$", "lista de artefactos requeridos"),
            list,
            "$.required_artifacts",
            "una lista",
        )
        steps_raw = _require_type(
            _require(document, "steps", "$", "lista de pasos"), list, "$.steps", "una lista"
        )
        if not steps_raw:
            raise SpecValidationError("una spec exige al menos un paso", check="V1", path="$.steps")

        steps = tuple(
            StepSpec.parse(item, f"$.steps[{index}]") for index, item in enumerate(steps_raw)
        )
        seen: set[str] = set()
        for index, step in enumerate(steps):
            if step.step_id in seen:
                raise SpecValidationError(
                    f"identificador de paso duplicado '{step.step_id}'",
                    check="V1",
                    path=f"$.steps[{index}].id",
                )
            seen.add(step.step_id)

        retention = _require_type(
            document.get("retention", {"inherits_from": "tenant"}), dict, "$.retention", "un objeto"
        )

        spec = cls(
            name=name,
            tenant=str(metadata.get("tenant", "GLOBAL")),
            version=version,
            description=str(metadata.get("description", "")),
            resolution=ResolutionSpec.parse(
                _require(document, "resolution", "$", "clave de resolución"), "$.resolution"
            ),
            required_artifacts=tuple(
                ArtifactSpec.parse(item, f"$.required_artifacts[{index}]")
                for index, item in enumerate(artifacts_raw)
            ),
            steps=steps,
            decision_policy=DecisionPolicy.parse(
                _require(document, "decision_policy", "$", "política de veredicto"),
                "$.decision_policy",
            ),
            retention_inherits_from=str(retention.get("inherits_from", "tenant")),
            content_hash=compute_content_hash(document),
        )
        return spec

    @classmethod
    def from_json(cls, text: str) -> FlowSpec:
        try:
            document = json.loads(text)
        except json.JSONDecodeError as exc:
            raise SpecValidationError(
                f"JSON inválido en la línea {exc.lineno}, columna {exc.colno}: {exc.msg}",
                check="V1",
                path="$",
            ) from exc
        return cls.parse(document)


def compute_content_hash(document: Mapping[str, Any]) -> str:
    """Hash de contenido de la spec, base de la inmutabilidad por versión."""
    import hashlib

    canonical = json.dumps(
        document, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str
    )
    return "sha256:" + hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_specs(documents: Sequence[Mapping[str, Any]]) -> tuple[FlowSpec, ...]:
    """Parsea un lote de especificaciones."""
    return tuple(FlowSpec.parse(document) for document in documents)


__all__ = [
    "API_VERSION",
    "KIND",
    "ArtifactSpec",
    "CapabilityRef",
    "DecisionPolicy",
    "DecisionRule",
    "FlowSpec",
    "ResolutionSpec",
    "RetryPolicy",
    "StepSpec",
    "compute_content_hash",
    "parse_specs",
]
