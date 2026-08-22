"""Motor de composición: parseo, resolución, validación y compilación."""

from __future__ import annotations

from .compiler import (
    ExecutionPlan,
    ExecutionTier,
    FlowCompiler,
    PlannedStep,
    check_quotas,
    emit_asl,
    emit_cloud_workflows,
)
from .registry import FlowSpecRegistry, ResolvedSpec, satisfies_range
from .spec import ArtifactSpec, CapabilityRef, DecisionPolicy, FlowSpec, StepSpec
from .validator import (
    CapabilityCatalog,
    FlowSpecValidator,
    ValidationIssue,
    ValidationReport,
    assert_tenant_provisioned,
)

__all__ = [
    "ArtifactSpec",
    "CapabilityCatalog",
    "CapabilityRef",
    "DecisionPolicy",
    "ExecutionPlan",
    "ExecutionTier",
    "FlowCompiler",
    "FlowSpec",
    "FlowSpecRegistry",
    "FlowSpecValidator",
    "PlannedStep",
    "ResolvedSpec",
    "StepSpec",
    "ValidationIssue",
    "ValidationReport",
    "assert_tenant_provisioned",
    "check_quotas",
    "emit_asl",
    "emit_cloud_workflows",
    "satisfies_range",
]
