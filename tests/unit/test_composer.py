"""Pruebas del motor de composición sobre la spec `Standard-eKYC-Latam`."""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from onboarding_generico.composer.compiler import (
    MAX_ASL_DEFINITION_BYTES,
    MAX_WORKFLOWS_PARALLEL_BRANCHES,
    ExecutionTier,
    FlowCompiler,
    check_quotas,
    classify,
    emit_asl,
    emit_cloud_workflows,
    topological_waves,
)
from onboarding_generico.composer.registry import (
    FlowSpecRegistry,
    parse_semver,
    satisfies_range,
)
from onboarding_generico.composer.spec import FlowSpec
from onboarding_generico.composer.validator import (
    CapabilityCatalog,
    FlowSpecValidator,
    assert_tenant_provisioned,
)
from onboarding_generico.domain.enums import Capability, WaitClass
from onboarding_generico.errors import (
    AmbiguousFlowSpecError,
    CapabilityNotProvisionedError,
    NoApplicableFlowSpecError,
    SpecValidationError,
)

# --------------------------------------------------------------------------
# Parseo (V1)
# --------------------------------------------------------------------------


def test_parses_the_reference_spec(flow_spec: FlowSpec) -> None:
    assert flow_spec.name == "Standard-eKYC-Latam"
    assert flow_spec.tenant == "GLOBAL"
    assert flow_spec.version == "1.0.0"
    assert flow_spec.content_hash.startswith("sha256:")
    assert "document_alignment" in flow_spec.step_ids
    assert "data_extraction_ocr" in flow_spec.step_ids
    assert "liveness_check" in flow_spec.step_ids
    assert "biometric_matching" in flow_spec.step_ids


def test_fallback_provider_builds_the_chain(flow_spec: FlowSpec) -> None:
    ocr = flow_spec.step("data_extraction_ocr")
    assert ocr.provider == "textract_ocr"
    assert ocr.fallback_provider == ("documentai_ocr", "tesseract_ocr")
    assert ocr.provider_chain == ("textract_ocr", "documentai_ocr", "tesseract_ocr")


def test_liveness_declares_long_wait_and_no_compensation(flow_spec: FlowSpec) -> None:
    liveness = flow_spec.step("liveness_check")
    assert liveness.wait is WaitClass.LONG
    assert liveness.compensable is False
    assert liveness.fallback_provider == ()


def test_biometric_matching_depends_on_liveness(flow_spec: FlowSpec) -> None:
    """Comparar contra una imagen que no superó el reto es gastar y errar."""
    assert "liveness_check" in flow_spec.step("biometric_matching").depends_on


def test_liveness_rejects_fallback_chain(flow_spec_document: dict[str, Any]) -> None:
    """El PAD no se degrada a un proveedor sin certificación iBeta."""
    document = copy.deepcopy(flow_spec_document)
    for step in document["steps"]:
        if step["id"] == "liveness_check":
            step["fallback_provider"] = ["proveedor_barato"]
    with pytest.raises(SpecValidationError) as excinfo:
        FlowSpec.parse(document)
    assert "iBeta" in excinfo.value.message


def test_biometric_artifact_requires_purge_flag(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    for artifact in document["required_artifacts"]:
        if artifact["slot"] == "SELFIE":
            artifact["purge_after_decision"] = False
    with pytest.raises(SpecValidationError) as excinfo:
        FlowSpec.parse(document)
    assert excinfo.value.details["path"].endswith("purge_after_decision")


@pytest.mark.parametrize(
    ("mutation", "expected_path"),
    [
        ({"apiVersion": "og.flow/v2"}, "$.apiVersion"),
        ({"kind": "Otra"}, "$.kind"),
    ],
)
def test_rejects_wrong_envelope(
    flow_spec_document: dict[str, Any], mutation: dict[str, Any], expected_path: str
) -> None:
    document = copy.deepcopy(flow_spec_document)
    document.update(mutation)
    with pytest.raises(SpecValidationError) as excinfo:
        FlowSpec.parse(document)
    assert excinfo.value.details["path"] == expected_path


def test_rejects_non_semver_version(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["metadata"]["version"] = "v1.0"
    with pytest.raises(SpecValidationError) as excinfo:
        FlowSpec.parse(document)
    assert excinfo.value.details["path"] == "$.metadata.version"


def test_error_message_points_at_the_exact_path(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][1]["thresholds"]["min_field_confidence"] = "alta"
    with pytest.raises(SpecValidationError) as excinfo:
        FlowSpec.parse(document)
    assert excinfo.value.details["path"] == "$.steps[1].thresholds.min_field_confidence"


def test_rejects_unknown_capability(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][0]["capability"] = "magia.negra.v1"
    with pytest.raises(SpecValidationError) as excinfo:
        FlowSpec.parse(document)
    assert excinfo.value.details["check"] == "V2"


def test_rejects_duplicate_step_ids(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][1]["id"] = document["steps"][0]["id"]
    with pytest.raises(SpecValidationError):
        FlowSpec.parse(document)


def test_from_json_reports_line_and_column() -> None:
    with pytest.raises(SpecValidationError) as excinfo:
        FlowSpec.from_json('{"apiVersion": "og.flow/v1",}')
    assert "línea" in excinfo.value.message


# --------------------------------------------------------------------------
# Validación (V2..V7)
# --------------------------------------------------------------------------


def test_reference_spec_validates(flow_spec: FlowSpec) -> None:
    report = FlowSpecValidator().validate(flow_spec)
    assert report.ok is True
    assert report.resolved_capabilities["data_extraction_ocr"] == "ocr.document.v1@1.5.2"
    assert report.resolved_capabilities["liveness_check"] == "biometrics.liveness.v2@2.0.0"


def test_v2_unresolvable_version_range(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][1]["capability"] = "ocr.document.v1@^9.0"
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert report.ok is False
    assert report.errors[0].check == "V2"


def test_v3_rejects_us_only_processor_for_latam(flow_spec_document: dict[str, Any]) -> None:
    """`AnalyzeID` y los procesadores de identidad de Document AI no sirven en LATAM."""
    document = copy.deepcopy(flow_spec_document)
    document["steps"][1]["provider"] = "textract_analyze_id"
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert report.ok is False
    assert any(issue.check == "V3" for issue in report.errors)
    assert "EE. UU." in report.errors[0].message


def test_v3_rejects_capability_without_country_coverage(flow_spec: FlowSpec) -> None:
    catalog = CapabilityCatalog(countries={Capability.OCR_DOCUMENT: ["US"]})
    report = FlowSpecValidator(catalog).validate(flow_spec)
    assert report.ok is False
    assert any(issue.check == "V3" for issue in report.errors)


def test_v4_detects_cycles(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][0]["depends_on"] = ["biometric_matching"]
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert report.ok is False
    assert any(issue.check == "V4" and "ciclo" in issue.message for issue in report.errors)


def test_v4_detects_dangling_dependency(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][1]["depends_on"] = ["paso_inexistente"]
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert any(issue.check == "V4" for issue in report.errors)


def test_v5_rejects_reference_to_undeclared_output(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][1]["inputs"]["artifact_ref"] = "${steps.document_alignment.output.no_existe}"
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert report.ok is False
    assert any(issue.check == "V5" for issue in report.errors)
    assert "aligned_ref" in report.errors[0].message


def test_v5_rejects_reference_without_declared_dependency(
    flow_spec_document: dict[str, Any],
) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][0]["inputs"]["ref"] = "${steps.liveness_check.output.score}"
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert any(issue.check == "V5" and "depends_on" in issue.message for issue in report.errors)


def test_v5_rejects_unknown_artifact_slot(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][0]["inputs"]["artifact_ref"] = "${artifacts.PROOF_OF_ADDRESS.pointer}"
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert any(issue.check == "V5" for issue in report.errors)


def test_v6_rejects_duplicate_reason_codes(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["decision_policy"]["rules"][1]["reason"] = document["decision_policy"]["rules"][0][
        "reason"
    ]
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert any(issue.check == "V6" for issue in report.errors)


def test_v6_requires_total_policy(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    del document["decision_policy"]["default"]
    with pytest.raises(SpecValidationError):
        FlowSpec.parse(document)


def test_v7_middleware_issuer_is_forbidden_in_bolivia(flow_spec_document: dict[str, Any]) -> None:
    """Art. 32(II) del Instructivo UIF: la Debida Diligencia no se delega."""
    document = copy.deepcopy(flow_spec_document)
    document["decision_policy"]["issuer"] = "MIDDLEWARE"
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert report.ok is False
    error = next(issue for issue in report.errors if issue.check == "V7")
    assert "BO" in error.message
    assert "32(II)" in error.message


def test_v7_allows_middleware_issuer_outside_bolivia(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["decision_policy"]["issuer"] = "MIDDLEWARE"
    document["resolution"]["countries"] = ["MX", "PY"]
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert report.ok is True


def test_v7_warns_about_early_non_compensable_step(flow_spec: FlowSpec) -> None:
    """Gastar cuota antes de saber si la sesión completa es un coste evitable."""
    report = FlowSpecValidator().validate(flow_spec)
    warnings = [w for w in report.warnings if w.check == "V7"]
    assert warnings, "se esperaba una advertencia por el paso no compensable temprano"


def test_report_raise_if_failed(flow_spec_document: dict[str, Any]) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["steps"][0]["depends_on"] = ["biometric_matching"]
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    with pytest.raises(SpecValidationError):
        report.raise_if_failed()


def test_tenant_provisioning_check(flow_spec: FlowSpec) -> None:
    all_capabilities = [step.capability.capability for step in flow_spec.steps]
    assert_tenant_provisioned(flow_spec, tenant_capabilities=all_capabilities)
    with pytest.raises(CapabilityNotProvisionedError) as excinfo:
        assert_tenant_provisioned(flow_spec, tenant_capabilities=[Capability.OCR_DOCUMENT])
    assert "biometrics.facematch.v1" in excinfo.value.details["missing_capabilities"]


# --------------------------------------------------------------------------
# Registro y resolución
# --------------------------------------------------------------------------


def test_semver_range_resolution() -> None:
    assert satisfies_range("1.5.2", "^1.4") is True
    assert satisfies_range("2.0.0", "^1.4") is False
    assert satisfies_range("1.4.9", "~1.4") is True
    assert satisfies_range("1.5.0", "~1.4") is False
    assert satisfies_range("1.4.2", "1.4.2") is True
    assert satisfies_range("9.9.9", "") is True
    assert parse_semver("1.2.3") == (1, 2, 3)


def test_resolve_returns_the_reference_spec(flow_spec: FlowSpec) -> None:
    registry = FlowSpecRegistry([flow_spec])
    resolved = registry.resolve(tenant_id="acme", country="MX", document_type="INE_2019")
    assert resolved.spec.name == "Standard-eKYC-Latam"
    assert resolved.tenant_scoped is False
    assert resolved.ref.content_hash == flow_spec.content_hash


def test_no_applicable_spec_raises(flow_spec: FlowSpec) -> None:
    registry = FlowSpecRegistry([flow_spec])
    with pytest.raises(NoApplicableFlowSpecError):
        registry.resolve(tenant_id="acme", country="FR", document_type="PASSPORT")


def test_tenant_spec_wins_over_global(
    flow_spec: FlowSpec, flow_spec_document: dict[str, Any]
) -> None:
    document = copy.deepcopy(flow_spec_document)
    document["metadata"]["tenant"] = "acme"
    document["metadata"]["name"] = "acme-mx"
    registry = FlowSpecRegistry([flow_spec, FlowSpec.parse(document)])
    resolved = registry.resolve(tenant_id="acme", country="MX", document_type="INE_2019")
    assert resolved.spec.tenant == "acme"
    assert resolved.tenant_scoped is True


def test_specificity_beats_priority(
    flow_spec: FlowSpec, flow_spec_document: dict[str, Any]
) -> None:
    """Una spec con país concreto gana a una con comodín, sea cual sea `priority`."""
    wildcard = copy.deepcopy(flow_spec_document)
    wildcard["metadata"]["name"] = "catch-all"
    wildcard["resolution"]["countries"] = ["*"]
    wildcard["resolution"]["document_types"] = ["*"]
    wildcard["resolution"]["priority"] = 9_999
    registry = FlowSpecRegistry([flow_spec, FlowSpec.parse(wildcard)])
    resolved = registry.resolve(tenant_id="acme", country="MX", document_type="INE_2019")
    assert resolved.spec.name == "Standard-eKYC-Latam"


def test_higher_semver_wins_for_the_same_key(flow_spec_document: dict[str, Any]) -> None:
    newer = copy.deepcopy(flow_spec_document)
    newer["metadata"]["version"] = "1.1.0"
    registry = FlowSpecRegistry([FlowSpec.parse(flow_spec_document), FlowSpec.parse(newer)])
    resolved = registry.resolve(tenant_id="acme", country="MX", document_type="INE_2019")
    assert resolved.spec.version == "1.1.0"
    assert registry.list_versions("GLOBAL", "Standard-eKYC-Latam") == ("1.0.0", "1.1.0")


def test_ambiguous_publication_is_rejected(
    flow_spec: FlowSpec, flow_spec_document: dict[str, Any]
) -> None:
    """Empate en especificidad y prioridad: error de publicación, no azar."""
    twin = copy.deepcopy(flow_spec_document)
    twin["metadata"]["name"] = "otro-nombre"
    registry = FlowSpecRegistry([flow_spec])
    with pytest.raises(AmbiguousFlowSpecError):
        registry.publish(FlowSpec.parse(twin))


def test_republishing_a_modified_version_is_rejected(
    flow_spec: FlowSpec, flow_spec_document: dict[str, Any]
) -> None:
    modified = copy.deepcopy(flow_spec_document)
    modified["metadata"]["description"] = "otra cosa"
    registry = FlowSpecRegistry([flow_spec])
    with pytest.raises(SpecValidationError):
        registry.publish(FlowSpec.parse(modified))


def test_republishing_the_identical_version_is_idempotent(flow_spec: FlowSpec) -> None:
    registry = FlowSpecRegistry([flow_spec])
    ref = registry.publish(flow_spec)
    assert ref.content_hash == flow_spec.content_hash
    assert len(registry) == 1


# --------------------------------------------------------------------------
# Compilación
# --------------------------------------------------------------------------


def test_topological_waves(flow_spec: FlowSpec) -> None:
    waves = topological_waves(flow_spec)
    assert waves[0] == ("document_alignment",)
    assert set(waves[1]) == {"data_extraction_ocr", "liveness_check"}
    flat = [step for wave in waves for step in wave]
    assert flat.index("liveness_check") < flat.index("biometric_matching")


def test_step_classification(flow_spec: FlowSpec) -> None:
    """Espera larga o no compensable van al padre; lo computacional se fusiona."""
    assert classify(flow_spec.step("liveness_check")) == ExecutionTier.PARENT
    assert classify(flow_spec.step("data_extraction_ocr")) == ExecutionTier.CHILD
    assert classify(flow_spec.step("mrz_parse")) == ExecutionTier.MERGED
    assert classify(flow_spec.step("cross_field_validation")) == ExecutionTier.MERGED


def test_compile_produces_plan(flow_spec: FlowSpec) -> None:
    report = FlowSpecValidator().validate(flow_spec)
    plan = FlowCompiler(report.resolved_capabilities).compile(flow_spec)
    assert plan.spec_key == "GLOBAL:Standard-eKYC-Latam"
    assert plan.content_hash == flow_spec.content_hash
    assert plan.decision_issuer == "SIGNALS_ONLY"
    assert {s.step_id for s in plan.parent_steps} == {"liveness_check"}
    assert {s.step_id for s in plan.merged_steps} == {"mrz_parse", "cross_field_validation"}
    assert plan.step("data_extraction_ocr").provider_chain[0] == "textract_ocr"
    assert plan.estimated_history_events > 0


def test_plan_is_json_serializable(flow_spec: FlowSpec) -> None:
    plan = FlowCompiler().compile(flow_spec)
    assert json.loads(plan.to_json())["spec_ref"]["version"] == "1.0.0"


def test_emit_asl_structure(flow_spec: FlowSpec) -> None:
    plan = FlowCompiler().compile(flow_spec)
    asl = emit_asl(plan)
    assert asl["StartAt"] == "Wave0"
    # 1 año es el máximo real de Standard, no "sin límite".
    assert asl["TimeoutSeconds"] == 31_536_000
    assert asl["States"]["Decide"]["End"] is True

    states = asl["States"]
    assert states["Wave1"]["Type"] == "Parallel"
    branches = {b["StartAt"] for b in states["Wave1"]["Branches"]}
    assert branches == {"data_extraction_ocr", "liveness_check"}

    liveness_state = next(
        b["States"]["liveness_check"]
        for b in states["Wave1"]["Branches"]
        if b["StartAt"] == "liveness_check"
    )
    assert liveness_state["Resource"].endswith(".waitForTaskToken")
    assert liveness_state["Parameters"]["Payload"]["task_token.$"] == "$$.Task.Token"


def test_asl_injects_retry_and_fallback_catch(flow_spec: FlowSpec) -> None:
    plan = FlowCompiler().compile(flow_spec)
    states = emit_asl(plan)["States"]
    ocr_state = next(
        b["States"]["data_extraction_ocr"]
        for b in states["Wave1"]["Branches"]
        if b["StartAt"] == "data_extraction_ocr"
    )
    assert ocr_state["Retry"][0]["MaxAttempts"] == 2
    assert "OG_PROVIDER_UNAVAILABLE" in ocr_state["Retry"][0]["ErrorEquals"]
    assert ocr_state["Catch"][0]["Next"] == "data_extraction_ocr__fallback"


def test_asl_carries_pointers_not_binaries(flow_spec: FlowSpec) -> None:
    plan = FlowCompiler().compile(flow_spec)
    serialized = json.dumps(emit_asl(plan))
    assert "artifact_refs.$" in serialized
    assert "base64" not in serialized
    assert len(serialized.encode("utf-8")) < MAX_ASL_DEFINITION_BYTES


def test_merged_steps_do_not_generate_asl_states(flow_spec: FlowSpec) -> None:
    """Cada transición del padre cuesta: los pasos triviales se colapsan."""
    plan = FlowCompiler().compile(flow_spec)
    serialized = json.dumps(emit_asl(plan))
    assert '"mrz_parse"' not in serialized


def test_emit_cloud_workflows_yaml(flow_spec: FlowSpec) -> None:
    plan = FlowCompiler().compile(flow_spec)
    yaml = emit_cloud_workflows(plan)
    assert yaml.startswith("# GLOBAL:Standard-eKYC-Latam v1.0.0")
    assert "main:" in yaml
    assert "params: [args]" in yaml
    assert "data_extraction_ocr" in yaml
    # La ola 1 tiene dos pasos, pero `liveness_check` es de espera larga y se
    # emite aparte con el patrón de suspensión, así que no queda un `parallel`.
    assert "OG_STEP_DISPATCH_URL" in yaml
    # Se libera memoria antes de terminar: 512 KB acumulados por ejecución.
    assert "results: null" in yaml


def test_cloud_workflows_uses_relaunch_not_await_callback(flow_spec: FlowSpec) -> None:
    """12 h de timeout, un solo slot por endpoint y sin heartbeat: no sirve."""
    yaml = emit_cloud_workflows(FlowCompiler().compile(flow_spec))
    assert "await_callback" not in yaml
    assert "liveness_check_suspend" in yaml
    assert "executions.run" in yaml


def test_quota_check_passes_for_the_reference_spec(flow_spec: FlowSpec) -> None:
    assert check_quotas(FlowCompiler().compile(flow_spec)) == ()


def test_compiler_warns_when_a_wave_exceeds_ten_branches(
    flow_spec_document: dict[str, Any],
) -> None:
    """Cloud Workflows admite 10 ramas por paso `parallel`."""
    document = copy.deepcopy(flow_spec_document)
    base = document["steps"][0]
    for index in range(MAX_WORKFLOWS_PARALLEL_BRANCHES + 1):
        clone = copy.deepcopy(base)
        clone["id"] = f"extra_{index}"
        clone["depends_on"] = []
        clone.pop("inputs", None)
        document["steps"].append(clone)
    plan = FlowCompiler().compile(FlowSpec.parse(document))
    assert any("ramas" in warning for warning in plan.warnings)
    # Y el YAML agrupa la ola en bloques `parallel` de como mucho 10 ramas.
    yaml = emit_cloud_workflows(plan)
    assert yaml.count("parallel:") >= 2
