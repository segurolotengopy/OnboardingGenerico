"""Núcleo de dominio: agnóstico de nube y sin dependencias externas.

Nada de este subpaquete importa `boto3`, `google-cloud-*` ni ningún SDK. Si
alguna vez lo hiciera, el adaptador de la otra nube dejaría de ser viable.
"""

from __future__ import annotations

from .decision import Decision, DecisionEngine, DecisionReason, DecisionThresholds
from .enums import (
    ArtifactSlot,
    Capability,
    CompileTarget,
    DataClass,
    DecisionIssuer,
    DecisionOutcome,
    DecisionSource,
    DocumentType,
    EventType,
    EvidenceKind,
    MrzFormat,
    OnFailure,
    ProviderKind,
    RiskLevel,
    SessionState,
    Sex,
    StepState,
    Verdict,
    WaitClass,
)
from .events import AuditChain, AuditEvent, verify_chain
from .identity import IdentityClaimSet, compare_claims
from .mrz import MrzRecord, check_digit, cross_check, parse_mrz
from .session import OnboardingSession, Step
from .value_objects import (
    Artifact,
    Confidence,
    CountryCode,
    Evidence,
    FlowSpecRef,
    ObjectRef,
    ProviderRef,
    ResolutionKey,
    SessionId,
    SubjectRef,
    TenantId,
)

__all__ = [
    "Artifact",
    "ArtifactSlot",
    "AuditChain",
    "AuditEvent",
    "Capability",
    "CompileTarget",
    "Confidence",
    "CountryCode",
    "DataClass",
    "Decision",
    "DecisionEngine",
    "DecisionIssuer",
    "DecisionOutcome",
    "DecisionReason",
    "DecisionSource",
    "DecisionThresholds",
    "DocumentType",
    "EventType",
    "Evidence",
    "EvidenceKind",
    "FlowSpecRef",
    "IdentityClaimSet",
    "MrzFormat",
    "MrzRecord",
    "ObjectRef",
    "OnFailure",
    "OnboardingSession",
    "ProviderKind",
    "ProviderRef",
    "ResolutionKey",
    "RiskLevel",
    "SessionId",
    "SessionState",
    "Sex",
    "Step",
    "StepState",
    "SubjectRef",
    "TenantId",
    "Verdict",
    "WaitClass",
    "check_digit",
    "compare_claims",
    "cross_check",
    "parse_mrz",
    "verify_chain",
]
