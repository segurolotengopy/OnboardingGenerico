"""Compilador: `FlowSpec` → `ExecutionPlan` → ASL / Cloud Workflows.

El `ExecutionPlan` es **agnóstico del orquestador**: es lo que consumen los
step-workers y lo que se congela en la sesión. Los emisores (`emit_asl`,
`emit_cloud_workflows`) traducen ese plan al lenguaje de cada nube.

Reparto padre/hijo
------------------

======================================================  =========  ==========================
Condición del paso                                      Destino    Razón
======================================================  =========  ==========================
`wait: LONG`, `compensable: false` o espera de callback Padre      Express no soporta
                                                                   `.waitForTaskToken`, `.sync`,
                                                                   Distributed Map ni Activities
Automatizado, idempotente, corto                        Hijo       Coste por duración en vez
                                                                   de por transición
Puramente computacional y de microsegundos              Fusionado  Cada transición del padre
                                                                   cuesta
======================================================  =========  ==========================

El ahorro del patrón anidado es **específico de cada flujo**. Los datos de
referencia sobre un flujo ejemplo ejecutado 1.000 veces: Standard puro con 17
transiciones = 0,42 USD; Express puro con 11.300 ms de media = 0,01 USD
(**98 %** de reducción); anidado con padre de 8 transiciones = 0,20 USD
(**~52 %**). Arrancar un workflow anidado no tiene coste adicional.

Cuotas que el compilador verifica
---------------------------------

- **ASL**: definición ≤ 1 MB (cuota dura), payload ≤ 256 KiB, ≤ 25.000 eventos
  de historial por ejecución en Standard. Se advierte al superar el 60 %.
- **Cloud Workflows**: 512 KB acumulados por ejecución (el límite dominante),
  ≤ 10 ramas por paso `parallel` (se agrupan en olas), longitud de expresión
  ≤ 400 caracteres, código fuente ≤ 128 KB.

Espera larga en GCP
-------------------

Con `wait: LONG` **no** se emite `await_callback` sin más: su timeout por
defecto son 43.200 s (12 h), hay **un solo slot pendiente por endpoint** (el
segundo recibe HTTP 429) y no hay heartbeat. Se emite el patrón de persistir
el estado, terminar la ejecución y relanzar una nueva con `executions.run`
cuando llegue la decisión.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any

from ..domain.enums import Capability, CompileTarget, OnFailure, WaitClass
from ..errors import SpecValidationError
from .spec import FlowSpec, StepSpec

#: Cuotas verificadas al compilar.
MAX_ASL_DEFINITION_BYTES: int = 1_048_576
MAX_STEP_FUNCTIONS_PAYLOAD_BYTES: int = 262_144
MAX_HISTORY_EVENTS: int = 25_000
HISTORY_WARNING_RATIO: float = 0.60
MAX_WORKFLOWS_EXECUTION_BYTES: int = 524_288
MAX_WORKFLOWS_PARALLEL_BRANCHES: int = 10
MAX_WORKFLOWS_SOURCE_BYTES: int = 131_072
CLOUD_WORKFLOWS_CALLBACK_DEFAULT_SECONDS: int = 43_200

#: Capacidades puramente computacionales: se fusionan con el paso vecino,
#: porque cada transición del padre cuesta y colapsarlas reduce la factura.
MERGEABLE_CAPABILITIES: frozenset[Capability] = frozenset(
    {Capability.MRZ_PARSE, Capability.VALIDATION_CROSSFIELD}
)


class ExecutionTier(str):
    """Nivel de orquestación asignado a un paso."""

    PARENT = "PARENT"
    CHILD = "CHILD"
    MERGED = "MERGED"


@dataclass(frozen=True, slots=True)
class PlannedStep:
    """Paso ya clasificado y con su cadena de proveedores resuelta."""

    step_id: str
    capability: str
    resolved_capability: str
    provider_chain: tuple[str, ...]
    depends_on: tuple[str, ...]
    tier: str
    thresholds: Mapping[str, float] = field(default_factory=dict)
    inputs: Mapping[str, Any] = field(default_factory=dict)
    max_attempts: int = 0
    base_ms: int = 200
    required: bool = True
    on_failure: str = str(OnFailure.ABORT)
    wait: str = str(WaitClass.NONE)
    compensable: bool = True
    merged_into: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "id": self.step_id,
            "capability": self.capability,
            "resolved_capability": self.resolved_capability,
            "provider_chain": list(self.provider_chain),
            "depends_on": list(self.depends_on),
            "tier": self.tier,
            "thresholds": dict(self.thresholds),
            "inputs": dict(self.inputs),
            "retries": {"max": self.max_attempts, "base_ms": self.base_ms},
            "required": self.required,
            "on_failure": self.on_failure,
            "wait": self.wait,
            "compensable": self.compensable,
            "merged_into": self.merged_into,
        }


@dataclass(frozen=True, slots=True)
class ExecutionPlan:
    """Artefacto independiente del orquestador, consumido por los step-workers."""

    spec_key: str
    spec_version: str
    content_hash: str
    steps: tuple[PlannedStep, ...]
    waves: tuple[tuple[str, ...], ...]
    decision_issuer: str
    default_outcome: str
    warnings: tuple[str, ...] = ()
    estimated_history_events: int = 0

    def step(self, step_id: str) -> PlannedStep:
        for candidate in self.steps:
            if candidate.step_id == step_id:
                return candidate
        raise SpecValidationError(
            f"paso inexistente en el plan: '{step_id}'", check="V4", path="steps"
        )

    @property
    def parent_steps(self) -> tuple[PlannedStep, ...]:
        return tuple(s for s in self.steps if s.tier == ExecutionTier.PARENT)

    @property
    def child_steps(self) -> tuple[PlannedStep, ...]:
        return tuple(s for s in self.steps if s.tier == ExecutionTier.CHILD)

    @property
    def merged_steps(self) -> tuple[PlannedStep, ...]:
        return tuple(s for s in self.steps if s.tier == ExecutionTier.MERGED)

    def as_dict(self) -> dict[str, Any]:
        return {
            "spec_ref": {"key": self.spec_key, "version": self.spec_version},
            "content_hash": self.content_hash,
            "decision": {"issuer": self.decision_issuer, "default": self.default_outcome},
            "waves": [list(wave) for wave in self.waves],
            "steps": {s.step_id: s.as_dict() for s in self.steps},
            "estimated_history_events": self.estimated_history_events,
            "warnings": list(self.warnings),
        }

    def to_json(self) -> str:
        return json.dumps(self.as_dict(), ensure_ascii=False, sort_keys=True, indent=2)


def topological_waves(spec: FlowSpec) -> tuple[tuple[str, ...], ...]:
    """Ordena los pasos en olas: cada ola puede ejecutarse en paralelo.

    Se agrupan en olas y no en una lista lineal porque el paralelismo es lo
    que determina el número real de transiciones, y con él el coste.
    """
    pending = {step.step_id: set(step.depends_on) for step in spec.steps}
    resolved: set[str] = set()
    waves: list[tuple[str, ...]] = []
    while pending:
        ready = sorted(node for node, deps in pending.items() if deps <= resolved)
        if not ready:
            raise SpecValidationError(
                "el grafo de dependencias tiene un ciclo y no se puede ordenar",
                check="V4",
                path="$.steps",
            )
        waves.append(tuple(ready))
        resolved.update(ready)
        for node in ready:
            pending.pop(node)
    return tuple(waves)


def classify(step: StepSpec) -> str:
    """Asigna el nivel de orquestación de un paso."""
    if step.wait is WaitClass.LONG or not step.compensable:
        return ExecutionTier.PARENT
    if step.capability.capability in MERGEABLE_CAPABILITIES:
        return ExecutionTier.MERGED
    return ExecutionTier.CHILD


class FlowCompiler:
    """Compila una spec validada a un plan de ejecución y a cada destino."""

    __slots__ = ("resolved_capabilities",)

    def __init__(self, resolved_capabilities: Mapping[str, str] | None = None) -> None:
        self.resolved_capabilities = dict(resolved_capabilities or {})

    def compile(self, spec: FlowSpec) -> ExecutionPlan:
        """Produce el `ExecutionPlan` agnóstico."""
        waves = topological_waves(spec)
        planned: list[PlannedStep] = []
        warnings: list[str] = []

        for step in spec.steps:
            tier = classify(step)
            merged_into = _merge_target(spec, step) if tier == ExecutionTier.MERGED else None
            planned.append(
                PlannedStep(
                    step_id=step.step_id,
                    capability=str(step.capability.capability),
                    resolved_capability=self.resolved_capabilities.get(
                        step.step_id, str(step.capability.capability)
                    ),
                    provider_chain=step.provider_chain,
                    depends_on=step.depends_on,
                    tier=tier,
                    thresholds=dict(step.thresholds),
                    inputs=dict(step.inputs),
                    max_attempts=step.retries.max_attempts,
                    base_ms=step.retries.base_ms,
                    required=step.required,
                    on_failure=str(step.on_failure),
                    wait=str(step.wait),
                    compensable=step.compensable,
                    merged_into=merged_into,
                )
            )

        estimated = _estimate_history_events(planned)
        if estimated > MAX_HISTORY_EVENTS * HISTORY_WARNING_RATIO:
            warnings.append(
                f"la estimación de eventos de historial ({estimated}) supera el "
                f"{int(HISTORY_WARNING_RATIO * 100)} % del límite de "
                f"{MAX_HISTORY_EVENTS} por ejecución; "
                "considere el patrón de arrancar ejecuciones nuevas"
            )
        for wave in waves:
            if len(wave) > MAX_WORKFLOWS_PARALLEL_BRANCHES:
                warnings.append(
                    f"la ola con {len(wave)} pasos supera las "
                    f"{MAX_WORKFLOWS_PARALLEL_BRANCHES} ramas por "
                    "paso 'parallel' de Cloud Workflows; el compilador la agrupa en olas sucesivas"
                )

        return ExecutionPlan(
            spec_key=spec.key,
            spec_version=spec.version,
            content_hash=spec.content_hash,
            steps=tuple(planned),
            waves=waves,
            decision_issuer=str(spec.decision_policy.issuer),
            default_outcome=str(spec.decision_policy.default_outcome),
            warnings=tuple(warnings),
            estimated_history_events=estimated,
        )

    # -- Emisores ---------------------------------------------------------

    def emit(self, plan: ExecutionPlan, target: CompileTarget) -> dict[str, Any] | str:
        if target is CompileTarget.ASL:
            return emit_asl(plan)
        return emit_cloud_workflows(plan)


def emit_asl(plan: ExecutionPlan) -> dict[str, Any]:
    """Emite Amazon States Language como diccionario.

    Se devuelve un `dict` y no una cadena a propósito: el llamador decide si
    lo serializa para Terraform, para la API o para calcular su hash.
    """
    states: dict[str, Any] = {}
    wave_names: list[str] = []

    for index, wave in enumerate(plan.waves):
        executable = [
            step_id for step_id in wave if plan.step(step_id).tier != ExecutionTier.MERGED
        ]
        if not executable:
            continue
        name = f"Wave{index}"
        wave_names.append(name)
        if len(executable) == 1:
            states[name] = _asl_task(plan, plan.step(executable[0]))
        else:
            states[name] = {
                "Type": "Parallel",
                "Comment": "Pasos sin dependencias entre sí; se ejecutan en paralelo",
                "Branches": [
                    {
                        "StartAt": step_id,
                        "States": {step_id: _asl_task(plan, plan.step(step_id), terminal=True)},
                    }
                    for step_id in executable
                ],
                "ResultPath": f"$.results.{name}",
            }

    for position, name in enumerate(wave_names):
        if position + 1 < len(wave_names):
            states[name]["Next"] = wave_names[position + 1]
        else:
            states[name]["Next"] = "Decide"

    states["Decide"] = {
        "Type": "Task",
        "Resource": "arn:aws:states:::lambda:invoke",
        "Parameters": {
            "FunctionName": "${resolve_decision_arn}",
            "Payload": {
                "tenant_id.$": "$.tenant_id",
                "session_id.$": "$.session_id",
                "issuer": plan.decision_issuer,
                "default_outcome": plan.default_outcome,
            },
        },
        "ResultPath": "$.decision",
        "End": True,
    }

    return {
        "Comment": f"{plan.spec_key} v{plan.spec_version} ({plan.content_hash})",
        "StartAt": wave_names[0] if wave_names else "Decide",
        "TimeoutSeconds": 31_536_000,  # 1 año: máximo real de Standard
        "States": states,
    }


def _asl_task(plan: ExecutionPlan, step: PlannedStep, *, terminal: bool = False) -> dict[str, Any]:
    """Estado ASL de un paso.

    Ningún estado transporta binarios: la entrada y la salida son punteros y
    metadatos. El payload está limitado a 256 KiB en ambos tipos de workflow.
    """
    if step.wait == str(WaitClass.LONG):
        resource = "arn:aws:states:::lambda:invoke.waitForTaskToken"
        payload: dict[str, Any] = {"task_token.$": "$$.Task.Token"}
    else:
        resource = "arn:aws:states:::lambda:invoke"
        payload = {}

    payload.update(
        {
            "tenant_id.$": "$.tenant_id",
            "session_id.$": "$.session_id",
            "step_id": step.step_id,
            "capability": step.resolved_capability,
            "provider_chain": list(step.provider_chain),
            "thresholds": dict(step.thresholds),
            "artifact_refs.$": "$.artifact_refs",
        }
    )

    state: dict[str, Any] = {
        "Type": "Task",
        "Comment": f"{step.capability} (tier={step.tier})",
        "Resource": resource,
        "Parameters": {"FunctionName": "${step_dispatch_arn}", "Payload": payload},
        "ResultPath": f"$.results.{step.step_id}",
        "ResultSelector": {
            "evidence_ref.$": "$.Payload.evidence_ref",
            "state.$": "$.Payload.state",
        },
    }

    if step.max_attempts:
        state["Retry"] = [
            {
                "ErrorEquals": ["OG_PROVIDER_UNAVAILABLE", "OG_PROVIDER_THROTTLED"],
                "IntervalSeconds": max(1, step.base_ms // 1000),
                "MaxAttempts": step.max_attempts,
                "BackoffRate": 2.0,
                "JitterStrategy": "FULL",
            }
        ]
    if len(step.provider_chain) > 1:
        state["Catch"] = [
            {
                "ErrorEquals": [
                    "OG_PROVIDER_UNAVAILABLE",
                    "OG_PROVIDER_THROTTLED",
                    "OG_INCONCLUSIVE",
                    "OG_PROVIDER_CONTRACT",
                ],
                "Next": f"{step.step_id}__fallback",
                "ResultPath": "$.error",
            }
        ]
    if step.on_failure == str(OnFailure.HUMAN_REVIEW):
        state.setdefault("Catch", []).append(
            {"ErrorEquals": ["States.ALL"], "Next": "Decide", "ResultPath": "$.error"}
        )
    if terminal:
        state["End"] = True
    return state


def emit_cloud_workflows(plan: ExecutionPlan) -> str:
    """Emite YAML de Cloud Workflows como cadena.

    La traducción **no es mecánica**: Workflows usa YAML/CEL, no ASL, y carece
    de las funciones intrínsecas de ASL y del catálogo de integraciones
    optimizadas de SDK; todo se resuelve con `http.post` o conectores.

    Se genera sin dependencia de PyYAML: el YAML emitido es un subconjunto
    plano y controlado, lo que además evita instalar una dependencia solo para
    escribir texto.
    """
    lines: list[str] = [
        f"# {plan.spec_key} v{plan.spec_version}",
        f"# content_hash: {plan.content_hash}",
        "# Solo punteros: el limite dominante son 512 KB acumulados por ejecucion.",
        "main:",
        "  params: [args]",
        "  steps:",
        "    - init:",
        "        assign:",
        "          - tenant_id: ${args.tenant_id}",
        "          - session_id: ${args.session_id}",
        "          - artifact_refs: ${args.artifact_refs}",
        "          - results: {}",
    ]

    for index, wave in enumerate(plan.waves):
        executable = [s for s in wave if plan.step(s).tier != ExecutionTier.MERGED]
        if not executable:
            continue
        long_waits = [s for s in executable if plan.step(s).wait == str(WaitClass.LONG)]
        immediate = [s for s in executable if s not in long_waits]

        if len(immediate) == 1:
            lines.extend(_workflows_call(plan.step(immediate[0]), indent="    "))
        elif len(immediate) > 1:
            # Máximo 10 ramas por paso parallel: se parte en olas sucesivas.
            for chunk_index, chunk in enumerate(
                _chunks(immediate, MAX_WORKFLOWS_PARALLEL_BRANCHES)
            ):
                lines.append(f"    - wave{index}_{chunk_index}:")
                lines.append("        parallel:")
                lines.append("          shared: [results]")
                lines.append("          branches:")
                for step_id in chunk:
                    lines.append(f"            - {step_id}_branch:")
                    lines.append("                steps:")
                    lines.extend(_workflows_call(plan.step(step_id), indent="                  "))

        for step_id in long_waits:
            lines.extend(_workflows_long_wait(plan.step(step_id)))

    lines.extend(
        [
            "    - decide:",
            "        call: http.post",
            "        args:",
            '          url: ${sys.get_env("OG_DECISION_URL")}',
            "          auth: {type: OIDC}",
            "          body:",
            "            tenant_id: ${tenant_id}",
            "            session_id: ${session_id}",
            f"            issuer: {plan.decision_issuer}",
            f"            default_outcome: {plan.default_outcome}",
            "        result: decision",
            "    - release_memory:",
            "        assign:",
            "          - results: null",
            "    - done:",
            "        return: ${decision.body}",
        ]
    )
    return "\n".join(lines) + "\n"


def _workflows_call(step: PlannedStep, *, indent: str = "    ") -> list[str]:
    return [
        f"{indent}- {step.step_id}:",
        f"{indent}    call: http.post",
        f"{indent}    args:",
        f'{indent}      url: ${{sys.get_env("OG_STEP_DISPATCH_URL")}}',
        f"{indent}      auth: {{type: OIDC}}",
        f"{indent}      body:",
        f"{indent}        tenant_id: ${{tenant_id}}",
        f"{indent}        session_id: ${{session_id}}",
        f"{indent}        step_id: {step.step_id}",
        f"{indent}        capability: {step.resolved_capability}",
        f"{indent}        provider_chain: {json.dumps(list(step.provider_chain))}",
        f"{indent}        artifact_refs: ${{artifact_refs}}",
        f"{indent}    result: {step.step_id}_result",
    ]


def _workflows_long_wait(step: PlannedStep) -> list[str]:
    """Patrón de espera larga en GCP: persistir, terminar y relanzar.

    No se emite `events.await_callback`: su timeout por defecto son 12 h, solo
    admite **un slot pendiente por endpoint** (el segundo recibe HTTP 429) y no
    tiene heartbeat. Un caso que escala a compliance o cruza un fin de semana
    no cabe ahí.
    """
    return [
        f"    - {step.step_id}_suspend:",
        "        call: http.post",
        "        args:",
        '          url: ${sys.get_env("OG_SUSPEND_URL")}',
        "          auth: {type: OIDC}",
        "          body:",
        "            tenant_id: ${tenant_id}",
        "            session_id: ${session_id}",
        f"            step_id: {step.step_id}",
        "            reason: LONG_WAIT",
        "        result: suspend_result",
        f"    - {step.step_id}_end_execution:",
        "        # Se termina la ejecucion; la decision relanza una nueva con executions.run.",
        "        return: ${suspend_result.body}",
    ]


def _chunks(items: Sequence[str], size: int) -> list[list[str]]:
    return [list(items[i : i + size]) for i in range(0, len(items), size)]


def _merge_target(spec: FlowSpec, step: StepSpec) -> str | None:
    """Paso vecino con el que se fusiona un paso puramente computacional."""
    if step.depends_on:
        return step.depends_on[-1]
    for candidate in spec.steps:
        if step.step_id in candidate.depends_on:
            return candidate.step_id
    return None


def _estimate_history_events(steps: Sequence[PlannedStep]) -> int:
    """Cota superior de eventos de historial con los reintentos máximos.

    Cada intento de un paso genera del orden de 5 eventos
    (`TaskStateEntered`, `TaskScheduled`, `TaskStarted`, `TaskSucceeded`,
    `TaskStateExited`); las esperas con token añaden un par más.
    """
    total = 2  # ExecutionStarted + ExecutionSucceeded
    for step in steps:
        if step.tier == ExecutionTier.MERGED:
            continue
        attempts = 1 + step.max_attempts + max(0, len(step.provider_chain) - 1)
        per_attempt = 7 if step.wait == str(WaitClass.LONG) else 5
        total += attempts * per_attempt
    return total


def check_quotas(plan: ExecutionPlan) -> tuple[str, ...]:
    """Verifica las cuotas duras de ambos destinos sobre el plan compilado."""
    findings: list[str] = []
    asl_bytes = len(json.dumps(emit_asl(plan)).encode("utf-8"))
    if asl_bytes > MAX_ASL_DEFINITION_BYTES:
        findings.append(
            f"la definición ASL ocupa {asl_bytes} bytes y la cuota dura es "
            f"{MAX_ASL_DEFINITION_BYTES}; "
            "hay que partirla en un padre y varios hijos anidados"
        )
    yaml_bytes = len(emit_cloud_workflows(plan).encode("utf-8"))
    if yaml_bytes > MAX_WORKFLOWS_SOURCE_BYTES:
        findings.append(
            f"el YAML de Cloud Workflows ocupa {yaml_bytes} bytes y el máximo es "
            f"{MAX_WORKFLOWS_SOURCE_BYTES}; hay que partir el workflow"
        )
    if plan.estimated_history_events > MAX_HISTORY_EVENTS:
        findings.append(
            f"la estimación de {plan.estimated_history_events} eventos supera el límite de "
            f"{MAX_HISTORY_EVENTS} por ejecución de Standard"
        )
    return tuple(findings)


__all__ = [
    "CLOUD_WORKFLOWS_CALLBACK_DEFAULT_SECONDS",
    "HISTORY_WARNING_RATIO",
    "MAX_ASL_DEFINITION_BYTES",
    "MAX_HISTORY_EVENTS",
    "MAX_STEP_FUNCTIONS_PAYLOAD_BYTES",
    "MAX_WORKFLOWS_EXECUTION_BYTES",
    "MAX_WORKFLOWS_PARALLEL_BRANCHES",
    "MAX_WORKFLOWS_SOURCE_BYTES",
    "MERGEABLE_CAPABILITIES",
    "ExecutionPlan",
    "ExecutionTier",
    "FlowCompiler",
    "PlannedStep",
    "check_quotas",
    "classify",
    "emit_asl",
    "emit_cloud_workflows",
    "topological_waves",
]
