"""Validador de especificaciones de flujo: comprobaciones V2 a V7.

V1 (esquema estructural) la hace el parser en `spec.py`, porque sin estructura
no hay nada que validar. Aquí van las comprobaciones semánticas:

======  ======================================================================
Chequeo Qué verifica
======  ======================================================================
V2      Las capacidades existen y el rango de versión resuelve.
V3      Aplicabilidad: cada capacidad cubre los países y documentos declarados.
V4      El grafo de dependencias es acíclico, conexo y todo paso es alcanzable.
V5      Encaje de contratos entre la salida de un paso y la entrada del siguiente.
V6      La política de veredicto es total.
V7      Reglas de cumplimiento y orden de los pasos no compensables.
======  ======================================================================

V7 merece énfasis: colocar un paso no compensable temprano en el DAG significa
gastar dinero y consumir cuota **antes** de saber si la sesión va a
completarse. Se emite advertencia cuando el paso podría moverse más tarde sin
romper dependencias.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..domain.enums import Capability, DecisionIssuer
from ..errors import CapabilityNotProvisionedError, SpecValidationError
from .registry import satisfies_range
from .spec import FlowSpec, StepSpec

#: Jurisdicciones donde el middleware **no puede** emitir el veredicto.
#: Bolivia: art. 32(II) del Instructivo UIF — "El Sujeto Obligado no podrá
#: delegar a terceros la ejecución de las medidas de Debida Diligencia del
#: cliente".
DELEGATION_PROHIBITED_COUNTRIES: frozenset[str] = frozenset({"BO"})

#: Capacidades que **no** deben usarse fuera de EE. UU.: los procesadores de
#: identidad de Textract (`AnalyzeID`) y Document AI cubren esencialmente
#: EE. UU. El patrón portable para LATAM es OCR genérico + LLM multimodal.
US_ONLY_PROVIDERS: frozenset[str] = frozenset(
    {"textract_analyze_id", "documentai_us_identity", "documentai_id_proofing"}
)

#: Esquema de salida declarado por cada capacidad, para el encaje V5.
CAPABILITY_OUTPUTS: dict[Capability, frozenset[str]] = {
    Capability.CAPTURE_QUALITY: frozenset({"sharpness", "glare", "resolution_px", "accepted"}),
    Capability.DOCUMENT_ALIGNMENT: frozenset(
        {"aligned_ref", "detected", "sharpness", "glare", "resolution_px", "skew_degrees"}
    ),
    Capability.OCR_DOCUMENT: frozenset({"blocks", "text", "min_confidence", "language"}),
    Capability.MRZ_PARSE: frozenset(
        {"record", "claims", "is_valid", "failed_checks", "mrz_format"}
    ),
    Capability.EXTRACTION_SEMANTIC: frozenset(
        {"fields", "claims", "field_confidence", "portrait_ref", "confidence"}
    ),
    Capability.VALIDATION_CROSSFIELD: frozenset(
        {"discrepancies", "minor_discrepancies", "is_consistent", "expired"}
    ),
    Capability.FORGERY_DETECTION: frozenset({"forgery_score", "suspicious", "signals"}),
    Capability.BIOMETRICS_LIVENESS: frozenset(
        {"score", "passed", "injection_detected", "audited_image_ref"}
    ),
    Capability.BIOMETRICS_FACEMATCH: frozenset({"similarity", "matched", "quality_candidate"}),
    Capability.REGISTRY_VERIFY: frozenset({"result", "matched_fields"}),
    Capability.AML_SCREENING: frozenset({"strong_hits", "weak_hits", "lists"}),
    Capability.HUMAN_REVIEW: frozenset({"outcome", "reviewer", "case_id"}),
    Capability.NOTIFY_WEBHOOK: frozenset({"delivered", "event_id"}),
}

#: Países cubiertos por cada capacidad. `*` significa sin restricción.
CAPABILITY_COUNTRIES: dict[Capability, frozenset[str]] = {
    capability: frozenset({"*"}) for capability in Capability
}

_REFERENCE_RE = re.compile(r"\$\{(?P<kind>steps|artifacts|session)\.(?P<body>[^}]+)\}")

#: Longitud máxima de una expresión en Cloud Workflows.
MAX_WORKFLOWS_EXPRESSION_LENGTH: int = 400


@dataclass(frozen=True, slots=True)
class ValidationIssue:
    """Hallazgo del validador."""

    check: str
    severity: str
    message: str
    path: str = ""

    def __str__(self) -> str:
        return f"[{self.check}/{self.severity}] {self.path}: {self.message}"


@dataclass(frozen=True, slots=True)
class ValidationReport:
    """Resultado completo de la validación."""

    errors: tuple[ValidationIssue, ...] = ()
    warnings: tuple[ValidationIssue, ...] = field(default=())
    resolved_capabilities: Mapping[str, str] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return not self.errors

    def raise_if_failed(self) -> None:
        if self.errors:
            first = self.errors[0]
            raise SpecValidationError(first.message, check=first.check, path=first.path)


class CapabilityCatalog:
    """Catálogo de capacidades con sus versiones publicadas y su aplicabilidad."""

    __slots__ = ("_versions", "_countries", "_documents")

    def __init__(
        self,
        versions: Mapping[Capability, Sequence[str]] | None = None,
        countries: Mapping[Capability, Sequence[str]] | None = None,
        documents: Mapping[Capability, Sequence[str]] | None = None,
    ) -> None:
        self._versions: dict[Capability, tuple[str, ...]] = {
            capability: ("1.0.0",) for capability in Capability
        }
        self._versions[Capability.OCR_DOCUMENT] = ("1.0.0", "1.4.0", "1.5.2")
        self._versions[Capability.EXTRACTION_SEMANTIC] = ("2.0.0", "2.1.0")
        self._versions[Capability.MRZ_PARSE] = ("1.0.0", "1.2.0")
        self._versions[Capability.BIOMETRICS_FACEMATCH] = ("1.3.0",)
        self._versions[Capability.BIOMETRICS_LIVENESS] = ("2.0.0",)
        self._versions[Capability.VALIDATION_CROSSFIELD] = ("1.1.0",)
        if versions:
            self._versions.update({k: tuple(v) for k, v in versions.items()})
        self._countries: dict[Capability, frozenset[str]] = {
            k: frozenset(v) for k, v in (countries or {}).items()
        }
        self._documents: dict[Capability, frozenset[str]] = {
            k: frozenset(v) for k, v in (documents or {}).items()
        }

    def resolve_version(self, capability: Capability, version_range: str) -> str | None:
        """Versión concreta más alta que satisface el rango."""
        candidates = [v for v in self._versions.get(capability, ()) if satisfies_range(v, version_range)]
        if not candidates:
            return None
        return max(candidates, key=lambda v: tuple(int(p) for p in v.split(".")))

    def available_versions(self, capability: Capability) -> tuple[str, ...]:
        return self._versions.get(capability, ())

    def supports_country(self, capability: Capability, country: str) -> bool:
        allowed = self._countries.get(capability, CAPABILITY_COUNTRIES.get(capability, frozenset({"*"})))
        return "*" in allowed or country == "*" or country in allowed

    def supports_document(self, capability: Capability, document_type: str) -> bool:
        allowed = self._documents.get(capability)
        if allowed is None:
            return True
        return "*" in allowed or document_type == "*" or document_type in allowed

    def outputs(self, capability: Capability) -> frozenset[str]:
        return CAPABILITY_OUTPUTS.get(capability, frozenset())


class FlowSpecValidator:
    """Ejecuta V2..V7 sobre una spec ya parseada."""

    __slots__ = ("catalog",)

    def __init__(self, catalog: CapabilityCatalog | None = None) -> None:
        self.catalog = catalog or CapabilityCatalog()

    def validate(self, spec: FlowSpec) -> ValidationReport:
        errors: list[ValidationIssue] = []
        warnings: list[ValidationIssue] = []
        resolved: dict[str, str] = {}

        self._check_capabilities(spec, errors, resolved)          # V2
        self._check_applicability(spec, errors)                   # V3
        self._check_graph(spec, errors, warnings)                 # V4
        self._check_contracts(spec, errors, warnings)             # V5
        self._check_decision_policy(spec, errors)                 # V6
        self._check_compliance(spec, errors, warnings)            # V7

        return ValidationReport(
            errors=tuple(errors), warnings=tuple(warnings), resolved_capabilities=resolved
        )

    # -- V2 ----------------------------------------------------------------

    def _check_capabilities(
        self, spec: FlowSpec, errors: list[ValidationIssue], resolved: dict[str, str]
    ) -> None:
        for index, step in enumerate(spec.steps):
            version = self.catalog.resolve_version(
                step.capability.capability, step.capability.version_range
            )
            if version is None:
                available = ", ".join(self.catalog.available_versions(step.capability.capability))
                errors.append(
                    ValidationIssue(
                        check="V2",
                        severity="error",
                        message=(
                            f"el rango '{step.capability.version_range}' de "
                            f"'{step.capability.capability}' no resuelve; versiones publicadas: {available}"
                        ),
                        path=f"$.steps[{index}].capability",
                    )
                )
                continue
            resolved[step.step_id] = f"{step.capability.capability}@{version}"

    # -- V3 ----------------------------------------------------------------

    def _check_applicability(self, spec: FlowSpec, errors: list[ValidationIssue]) -> None:
        for index, step in enumerate(spec.steps):
            capability = step.capability.capability
            for country in spec.resolution.countries:
                if not self.catalog.supports_country(capability, country):
                    errors.append(
                        ValidationIssue(
                            check="V3",
                            severity="error",
                            message=(
                                f"'{capability}' no cubre el país '{country}' declarado en la resolución"
                            ),
                            path=f"$.steps[{index}].capability",
                        )
                    )
            for document_type in spec.resolution.document_types:
                if not self.catalog.supports_document(capability, document_type):
                    errors.append(
                        ValidationIssue(
                            check="V3",
                            severity="error",
                            message=(
                                f"'{capability}' no cubre el documento '{document_type}'"
                            ),
                            path=f"$.steps[{index}].capability",
                        )
                    )
            non_us = [c for c in spec.resolution.countries if c not in {"US", "*"}]
            for provider in step.provider_chain:
                if provider in US_ONLY_PROVIDERS and non_us:
                    errors.append(
                        ValidationIssue(
                            check="V3",
                            severity="error",
                            message=(
                                f"'{provider}' es un procesador de identidad limitado a EE. UU. y la "
                                f"spec declara {non_us}; use OCR genérico + LLM multimodal"
                            ),
                            path=f"$.steps[{index}].provider",
                        )
                    )

    # -- V4 ----------------------------------------------------------------

    def _check_graph(
        self, spec: FlowSpec, errors: list[ValidationIssue], warnings: list[ValidationIssue]
    ) -> None:
        known = set(spec.step_ids)
        for index, step in enumerate(spec.steps):
            for dependency in step.depends_on:
                if dependency not in known:
                    errors.append(
                        ValidationIssue(
                            check="V4",
                            severity="error",
                            message=f"dependencia hacia un paso inexistente '{dependency}'",
                            path=f"$.steps[{index}].depends_on",
                        )
                    )
                if dependency == step.step_id:
                    errors.append(
                        ValidationIssue(
                            check="V4",
                            severity="error",
                            message="un paso no puede depender de sí mismo",
                            path=f"$.steps[{index}].depends_on",
                        )
                    )

        cycle = _find_cycle(spec)
        if cycle:
            errors.append(
                ValidationIssue(
                    check="V4",
                    severity="error",
                    message=f"ciclo en el grafo de dependencias: {' -> '.join(cycle)}",
                    path="$.steps",
                )
            )
            return

        # Todo paso debe ser alcanzable: o es raíz, o alguien depende de él, o
        # depende de alguien. Un paso aislado en una spec con varios pasos es
        # casi siempre un error de edición.
        referenced = {dep for step in spec.steps for dep in step.depends_on}
        for index, step in enumerate(spec.steps):
            if len(spec.steps) > 1 and not step.depends_on and step.step_id not in referenced:
                warnings.append(
                    ValidationIssue(
                        check="V4",
                        severity="warning",
                        message="paso huérfano: ni depende de otro ni nadie depende de él",
                        path=f"$.steps[{index}].id",
                    )
                )

    # -- V5 ----------------------------------------------------------------

    def _check_contracts(
        self, spec: FlowSpec, errors: list[ValidationIssue], warnings: list[ValidationIssue]
    ) -> None:
        slots = {str(artifact.slot) for artifact in spec.required_artifacts}
        for index, step in enumerate(spec.steps):
            for input_name, raw in step.inputs.items():
                if not isinstance(raw, str):
                    continue
                if len(raw) > MAX_WORKFLOWS_EXPRESSION_LENGTH:
                    warnings.append(
                        ValidationIssue(
                            check="V5",
                            severity="warning",
                            message=(
                                "expresión de más de 400 caracteres: Cloud Workflows exige partirla "
                                "en pasos 'assign'; el compilador lo hace automáticamente"
                            ),
                            path=f"$.steps[{index}].inputs.{input_name}",
                        )
                    )
                for match in _REFERENCE_RE.finditer(raw):
                    path = f"$.steps[{index}].inputs.{input_name}"
                    kind, body = match.group("kind"), match.group("body")
                    if kind == "artifacts":
                        slot = body.split(".")[0]
                        if slot not in slots:
                            errors.append(
                                ValidationIssue(
                                    check="V5",
                                    severity="error",
                                    message=(
                                        f"referencia al slot de artefacto '{slot}', que no está en "
                                        "'required_artifacts'"
                                    ),
                                    path=path,
                                )
                            )
                    elif kind == "steps":
                        pieces = body.split(".")
                        source_id = pieces[0]
                        if source_id not in set(spec.step_ids):
                            errors.append(
                                ValidationIssue(
                                    check="V5",
                                    severity="error",
                                    message=f"referencia al paso inexistente '{source_id}'",
                                    path=path,
                                )
                            )
                            continue
                        if source_id not in step.depends_on:
                            errors.append(
                                ValidationIssue(
                                    check="V5",
                                    severity="error",
                                    message=(
                                        f"se referencia la salida de '{source_id}' sin declararlo en "
                                        "'depends_on'; el orden de ejecución no estaría garantizado"
                                    ),
                                    path=path,
                                )
                            )
                            continue
                        if len(pieces) >= 3 and pieces[1] == "output":
                            attribute = pieces[2]
                            outputs = self.catalog.outputs(spec.step(source_id).capability.capability)
                            if outputs and attribute not in outputs:
                                errors.append(
                                    ValidationIssue(
                                        check="V5",
                                        severity="error",
                                        message=(
                                            f"'{attribute}' no existe en el esquema de salida de "
                                            f"'{spec.step(source_id).capability.capability}'; "
                                            f"campos disponibles: {', '.join(sorted(outputs))}"
                                        ),
                                        path=path,
                                    )
                                )

    # -- V6 ----------------------------------------------------------------

    def _check_decision_policy(self, spec: FlowSpec, errors: list[ValidationIssue]) -> None:
        policy = spec.decision_policy
        seen_reasons: set[str] = set()
        for index, rule in enumerate(policy.rules):
            if not rule.when.strip():
                errors.append(
                    ValidationIssue(
                        check="V6",
                        severity="error",
                        message="la condición de la regla no puede estar vacía",
                        path=f"$.decision_policy.rules[{index}].when",
                    )
                )
            if rule.reason in seen_reasons:
                errors.append(
                    ValidationIssue(
                        check="V6",
                        severity="error",
                        message=f"código de motivo duplicado '{rule.reason}'",
                        path=f"$.decision_policy.rules[{index}].reason",
                    )
                )
            seen_reasons.add(rule.reason)
        # La totalidad la garantiza `default`, obligatorio en el parser (V1).

    # -- V7 ----------------------------------------------------------------

    def _check_compliance(
        self, spec: FlowSpec, errors: list[ValidationIssue], warnings: list[ValidationIssue]
    ) -> None:
        prohibited = sorted(
            set(spec.resolution.countries) & DELEGATION_PROHIBITED_COUNTRIES
        )
        if spec.decision_policy.issuer is DecisionIssuer.MIDDLEWARE and prohibited:
            errors.append(
                ValidationIssue(
                    check="V7",
                    severity="error",
                    message=(
                        f"'issuer: MIDDLEWARE' es incompatible con {prohibited}: el art. 32(II) del "
                        "Instructivo UIF de Bolivia prohíbe delegar en terceros la Debida Diligencia "
                        "del cliente; use 'SIGNALS_ONLY' o 'REQUESTER_CONFIRMS'"
                    ),
                    path="$.decision_policy.issuer",
                )
            )

        depth = _depths(spec)
        max_depth = max(depth.values()) if depth else 0
        for index, step in enumerate(spec.steps):
            if step.compensable:
                continue
            if depth.get(step.step_id, 0) < max_depth:
                warnings.append(
                    ValidationIssue(
                        check="V7",
                        severity="warning",
                        message=(
                            "paso no compensable en un nivel temprano del DAG: gasta cuota y dinero "
                            "antes de saber si la sesión va a completarse; considere moverlo más tarde"
                        ),
                        path=f"$.steps[{index}].id",
                    )
                )

        for index, step in enumerate(spec.steps):
            if step.capability.capability is Capability.BIOMETRICS_LIVENESS and step.retries.max_attempts > 1:
                warnings.append(
                    ValidationIssue(
                        check="V7",
                        severity="warning",
                        message=(
                            "más de un reintento de liveness incrementa la fricción y el BPCER "
                            "efectivo sin mejorar el PAD"
                        ),
                        path=f"$.steps[{index}].retries.max",
                    )
                )


def assert_tenant_provisioned(
    spec: FlowSpec,
    *,
    tenant_capabilities: Sequence[Capability],
    active_providers: Sequence[str] = (),
) -> None:
    """Comprobación de **resolución**, no de publicación (doc 04 §6.1).

    Una spec puede ser estructuralmente válida y no ejecutable para un tenant
    concreto. Se ejecuta al resolver y en el modo `dry-run` de
    ``POST /v1/flows:validate``, para que aprovisionar un tenant nuevo se
    pueda verificar sin crear sesiones.
    """
    authorized = set(tenant_capabilities)
    missing = sorted(
        {str(s.capability.capability) for s in spec.steps if s.capability.capability not in authorized}
    )
    if missing:
        raise CapabilityNotProvisionedError(
            "el tenant no tiene proveedor configurado para todas las capacidades de la spec",
            spec=spec.key,
            missing_capabilities=missing,
        )
    if active_providers:
        available = set(active_providers)
        unavailable = sorted(
            {p for step in spec.steps for p in step.provider_chain if p and p not in available}
        )
        if unavailable:
            raise CapabilityNotProvisionedError(
                "hay proveedores declarados en la spec que no están activos para el tenant",
                spec=spec.key,
                inactive_providers=unavailable,
            )


def _find_cycle(spec: FlowSpec) -> list[str]:
    graph = {step.step_id: [d for d in step.depends_on if d in set(spec.step_ids)] for step in spec.steps}
    state: dict[str, int] = {node: 0 for node in graph}

    def visit(node: str, path: list[str]) -> list[str]:
        if state[node] == 1:
            return path[path.index(node) :] + [node]
        if state[node] == 2:
            return []
        state[node] = 1
        for neighbour in graph[node]:
            found = visit(neighbour, path + [node])
            if found:
                return found
        state[node] = 2
        return []

    for node in graph:
        found = visit(node, [])
        if found:
            return found
    return []


def _depths(spec: FlowSpec) -> dict[str, int]:
    """Profundidad topológica de cada paso; 0 son las raíces."""
    graph = {step.step_id: tuple(step.depends_on) for step in spec.steps}
    depth: dict[str, int] = {}

    def resolve(node: str, seen: frozenset[str]) -> int:
        if node in depth:
            return depth[node]
        if node in seen or node not in graph:
            return 0
        dependencies = graph[node]
        value = 0 if not dependencies else 1 + max(
            resolve(dep, seen | {node}) for dep in dependencies
        )
        depth[node] = value
        return value

    for step in spec.steps:
        resolve(step.step_id, frozenset())
    return depth


def step_signature(step: StepSpec) -> dict[str, Any]:
    """Resumen del paso para el informe de validación (sin datos de negocio)."""
    return {
        "id": step.step_id,
        "capability": str(step.capability),
        "depends_on": list(step.depends_on),
        "provider_chain": list(step.provider_chain),
        "wait": str(step.wait),
        "compensable": step.compensable,
        "required": step.required,
    }


__all__ = [
    "CAPABILITY_OUTPUTS",
    "DELEGATION_PROHIBITED_COUNTRIES",
    "MAX_WORKFLOWS_EXPRESSION_LENGTH",
    "US_ONLY_PROVIDERS",
    "CapabilityCatalog",
    "FlowSpecValidator",
    "ValidationIssue",
    "ValidationReport",
    "assert_tenant_provisioned",
    "step_signature",
]
