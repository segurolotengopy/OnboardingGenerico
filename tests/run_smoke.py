#!/usr/bin/env python3
"""Prueba de humo sin dependencias: `python tests/run_smoke.py`.

Existe porque el suite de `pytest` puede no ser ejecutable en un entorno de
construcción mínimo. Este script recorre los mismos caminos críticos usando
solo `assert` y la biblioteca estándar:

1. ICAO 9303 con los tres ejemplos canónicos.
2. Cifrado de sobre con AAD y fallo con otro `tenant_id`.
3. Caché de material con carga atómica bajo concurrencia real.
4. Composición: parseo, validación, resolución y compilación a ASL y YAML.
5. Máquina de estados y cadena de auditoría.
6. Motor de decisión.
7. Flujo completo de onboarding con los adaptadores en memoria.
8. Purga y crypto-shredding.

Devuelve 0 si todo pasa y 1 al primer fallo, con el detalle del caso.
"""

from __future__ import annotations

import hashlib
import json
import sys
import threading
import time
import traceback
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from onboarding_generico.application import (  # noqa: E402
    AssignCaseCommand,
    HandleManualReview,
    PurgeCommand,
    PurgeTenantData,
    ResolveCaseCommand,
    ResolveDecision,
    ResolveDecisionCommand,
    StartSession,
    StartSessionCommand,
    SubmitDocument,
    SubmitDocumentCommand,
    SubmitSelfie,
    SubmitSelfieCommand,
)
from onboarding_generico.composer.compiler import (  # noqa: E402
    ExecutionTier,
    FlowCompiler,
    check_quotas,
    emit_asl,
    emit_cloud_workflows,
)
from onboarding_generico.composer.registry import FlowSpecRegistry  # noqa: E402
from onboarding_generico.composer.spec import FlowSpec  # noqa: E402
from onboarding_generico.composer.validator import FlowSpecValidator  # noqa: E402
from onboarding_generico.config import load_settings  # noqa: E402
from onboarding_generico.container import (  # noqa: E402
    build_inmemory_container,
    provision_demo_tenant,
)
from onboarding_generico.crypto.envelope import (  # noqa: E402
    EnvelopeCipher,
    EnvelopeFieldCipher,
    LocalKeyProvider,
)
from onboarding_generico.crypto.field_policy import CryptoAction, default_policy  # noqa: E402
from onboarding_generico.crypto.material_cache import AtomicMaterialCache  # noqa: E402
from onboarding_generico.domain.decision import DecisionEngine, DecisionThresholds  # noqa: E402
from onboarding_generico.domain.enums import (  # noqa: E402
    Capability,
    DecisionIssuer,
    DecisionOutcome,
    DocumentType,
    EventType,
    EvidenceKind,
    MrzFormat,
    SessionState,
    StepState,
    Verdict,
)
from onboarding_generico.domain.events import AuditChain, verify_chain  # noqa: E402
from onboarding_generico.domain.identity import IdentityClaimSet  # noqa: E402
from onboarding_generico.domain.mrz import (  # noqa: E402
    check_digit,
    composite_payload,
    cross_check,
    normalize_lines,
    parse_mrz,
    verify_check_digit,
)
from onboarding_generico.domain.session import OnboardingSession, Step  # noqa: E402
from onboarding_generico.domain.value_objects import (  # noqa: E402
    Evidence,
    FlowSpecRef,
    ProviderRef,
    SessionId,
    SubjectRef,
    TenantId,
)
from onboarding_generico.errors import (  # noqa: E402
    AuditChainError,
    DecryptionError,
    DomainError,
    KeyDestroyedError,
    ValidationError,
)

FIXTURES = ROOT / "tests" / "fixtures"
PRINCIPAL = "svc-requester"

TD1 = (
    "I<UTOD231458907<<<<<<<<<<<<<<<\n"
    "7408122F1204159UTO<<<<<<<<<<<6\n"
    "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"
)
TD2 = "I<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<\nD231458907UTO7408122F1204159<<<<<<<6"
TD3 = (
    "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<\n"
    "L898902C36UTO7408122F1204159ZE184226B<<<<<10"
)

CLAIMS = {
    "first_name": "ANNA MARIA",
    "last_name": "ERIKSSON",
    "id_number": "D23145890",
    "birth_date": "1974-08-12",
    "expiry_date": "2012-04-15",
    "issuing_state": "UTO",
    "nationality": "UTO",
    "sex": "F",
}

_CHECKS: list[tuple[str, Callable[[], None]]] = []


def check(name: str) -> Callable[[Callable[[], None]], Callable[[], None]]:
    def _register(function: Callable[[], None]) -> Callable[[], None]:
        _CHECKS.append((name, function))
        return function

    return _register


def raises(error_type: type[BaseException], action: Callable[[], Any], label: str) -> None:
    try:
        action()
    except error_type:
        return
    except Exception as exc:  # noqa: BLE001
        raise AssertionError(f"{label}: se esperaba {error_type.__name__} y llegó {exc!r}") from exc
    raise AssertionError(f"{label}: se esperaba {error_type.__name__} y no se lanzó nada")


# --------------------------------------------------------------------------
# 1. ICAO 9303
# --------------------------------------------------------------------------


@check("ICAO 9303 - dígito de control 7-3-1")
def _check_digit_algorithm() -> None:
    assert check_digit("D23145890") == 7, "ejemplo trabajado de la referencia"
    assert check_digit("740812") == 2
    assert check_digit("120415") == 9
    assert check_digit("L898902C3") == 6
    assert check_digit("ZE184226B<<<<<") == 1
    assert check_digit("") == 0
    assert verify_check_digit("740812", "2") is True
    assert verify_check_digit("740812", "3") is False
    # Excepción del número personal vacío en TD3.
    assert verify_check_digit("<" * 14, "<", allow_filler=True) is True
    assert verify_check_digit("<" * 14, "<", allow_filler=False) is False


@check("ICAO 9303 - los tres ejemplos canónicos cuadran por completo")
def _canonical_examples() -> None:
    samples = json.loads((FIXTURES / "mrz_samples.json").read_text(encoding="utf-8"))
    for key in ("td1", "td2", "td3"):
        sample = samples["canonical"][key]
        record = parse_mrz(sample["lines"])
        expected = sample["expected"]
        assert str(record.mrz_format) == expected["format"], key
        assert record.is_valid is True, f"{key}: fallaron {record.failed_checks}"
        assert record.failed_checks == (), key
        assert record.document_number == expected["document_number"], key
        assert record.composite_check == expected["composite_check"], key
        assert record.surname == "ERIKSSON", key
        assert record.given_names == "ANNA MARIA", key
        assert record.birth_date == date(1974, 8, 12), key
        assert record.expiry_date == date(2012, 4, 15), key
    td3 = parse_mrz(samples["canonical"]["td3"]["lines"])
    assert td3.check_results["personal_number"] is True


@check("ICAO 9303 - el compuesto TD1 cubre los datos opcionales de la línea 1")
def _td1_composite_range() -> None:
    lines = normalize_lines(
        "I<UTOD231458907ABC123XYZ<<<<<<\n"
        "7408122F1204159UTO<<<<<<<<<<<0\n"
        "ERIKSSON<<ANNA<MARIA<<<<<<<<<<"
    )
    payload = composite_payload(MrzFormat.TD1, lines)
    assert "ABC123XYZ" in payload, "error clásico: omitir la posición 16-30 de la línea 1"
    assert len(payload) == 50
    assert len(composite_payload(MrzFormat.TD2, normalize_lines(TD2))) == 31
    assert len(composite_payload(MrzFormat.TD3, normalize_lines(TD3))) == 39


@check("ICAO 9303 - TD3 sin número personal admite '<' y '0' como dígito")
def _td3_empty_personal_number() -> None:
    line1 = "P<UTOERIKSSON<<ANNA<MARIA<<<<<<<<<<<<<<<<<<<"
    body = "L898902C36UTO7408122F1204159" + "<" * 14
    for personal_check in ("<", "0"):
        partial = body + personal_check
        composite = str(check_digit(partial[0:10] + partial[13:20] + partial[21:43]))
        record = parse_mrz([line1, partial + composite])
        assert record.is_valid is True, personal_check
        assert record.personal_number == ""


@check("ICAO 9303 - un dígito erróneo se reporta sin perder la lectura")
def _corrupted_mrz() -> None:
    corrupted = TD1.replace("D231458907", "D231458908")
    record = parse_mrz(corrupted)
    assert record.is_valid is False
    assert "document_number" in record.failed_checks
    assert record.surname == "ERIKSSON"
    assert "ERIKSSON" not in str(record.audit_summary()), "el resumen no puede llevar PII"


@check("ICAO 9303 - validación cruzada contra otra fuente")
def _cross_check() -> None:
    record = parse_mrz(TD1)
    consistent = cross_check(record, IdentityClaimSet.from_mapping(CLAIMS, source="llm"))
    assert consistent.is_consistent is True
    assert consistent.discrepancies == ()

    divergent = cross_check(
        record, IdentityClaimSet.from_mapping(dict(CLAIMS, birth_date="1980-01-01"), source="llm")
    )
    assert "birth_date" in divergent.discrepancies
    assert "D23145890" not in str(divergent.as_dict())


# --------------------------------------------------------------------------
# 2. Criptografía
# --------------------------------------------------------------------------


@check("Cripto - descifrar con otro tenant_id falla")
def _envelope_isolation() -> None:
    keys = LocalKeyProvider(b"raiz-de-prueba-de-32-bytes-xxxxx")
    cipher = EnvelopeCipher(keys)
    acme, globex = TenantId("acme"), TenantId("globex")

    envelope = cipher.encrypt(acme, b"D23145890", context={"field": "id_number"})
    assert cipher.decrypt(acme, envelope, context={"field": "id_number"}) == b"D23145890"
    raises(
        DecryptionError,
        lambda: cipher.decrypt(globex, envelope, context={"field": "id_number"}),
        "descifrado con otro tenant",
    )
    raises(
        DecryptionError,
        lambda: cipher.decrypt(acme, envelope, context={"field": "first_name"}),
        "descifrado con otro contexto",
    )


@check("Cripto - política por campo y firma del registro")
def _field_cipher() -> None:
    keys = LocalKeyProvider(b"raiz-de-prueba-de-32-bytes-xxxxx")
    field_cipher = EnvelopeFieldCipher(EnvelopeCipher(keys), keys)
    acme, globex = TenantId("acme"), TenantId("globex")

    item = {"tenant_id": "acme", "state": "CREATED", "id_number": "D23145890"}
    encrypted = field_cipher.encrypt_item(acme, item)
    assert "D23145890" not in str(encrypted)
    assert encrypted["tenant_id"] == "acme", "SIGN_ONLY viaja en claro"
    assert field_cipher.decrypt_item(acme, encrypted) == item
    raises(
        DecryptionError,
        lambda: field_cipher.decrypt_item(globex, encrypted),
        "descifrado de registro con otro tenant",
    )

    tampered = dict(encrypted, state="DECIDED")
    raises(
        DecryptionError,
        lambda: field_cipher.decrypt_item(acme, tampered),
        "alteración de un campo firmado",
    )

    beacon = field_cipher.beacon(acme, "email", "a@b.c")
    assert beacon == field_cipher.beacon(acme, "email", "a@b.c"), "el beacon es determinista"
    assert beacon != field_cipher.beacon(globex, "email", "a@b.c"), "el beacon es por tenant"

    policy = default_policy()
    assert policy.action_for("campo_nuevo") is CryptoAction.ENCRYPT_AND_SIGN
    raises(ValidationError, lambda: policy.assert_keys_are_safe(["id_number"]), "PII como clave")


@check("Cripto - caché con carga atómica, sin cache stampede")
def _material_cache() -> None:
    cache: AtomicMaterialCache[int] = AtomicMaterialCache(ttl_seconds=60)
    loads = {"count": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(16)

    def loader() -> int:
        with lock:
            loads["count"] += 1
        time.sleep(0.02)
        return 42

    def worker() -> None:
        barrier.wait()
        assert cache.get_or_load("acme:field", loader) == 42

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert loads["count"] == 1, f"hubo cache stampede: {loads['count']} cargas"
    assert cache.stats()["loads"] == 1

    clock = {"now": 0.0}
    ttl_cache: AtomicMaterialCache[int] = AtomicMaterialCache(
        ttl_seconds=10, clock=lambda: clock["now"]
    )
    ttl_cache.get_or_load("k", lambda: 1)
    clock["now"] = 11.0
    assert ttl_cache.get_or_load("k", lambda: 2) == 2, "el TTL debe expirar la entrada"


@check("Cripto - el crypto-shredding hace los datos irrecuperables")
def _shredding() -> None:
    keys = LocalKeyProvider(b"raiz-de-prueba-de-32-bytes-xxxxx")
    cipher = EnvelopeCipher(keys)
    acme, globex = TenantId("acme"), TenantId("globex")
    acme_envelope = cipher.encrypt(acme, b"expediente")
    globex_envelope = cipher.encrypt(globex, b"otro expediente")

    assert keys.shred_tenant_key(acme) is True
    raises(KeyDestroyedError, lambda: cipher.decrypt(acme, acme_envelope), "descifrar tras shred")
    assert cipher.decrypt(globex, globex_envelope) == b"otro expediente", "no afecta a otros"


# --------------------------------------------------------------------------
# 3. Composición
# --------------------------------------------------------------------------


def _load_spec() -> FlowSpec:
    document = json.loads(
        (FIXTURES / "flow_standard_ekyc_latam.json").read_text(encoding="utf-8")
    )
    return FlowSpec.parse(document)


@check("Composición - parseo y validación de Standard-eKYC-Latam")
def _spec_parse_and_validate() -> None:
    spec = _load_spec()
    assert spec.name == "Standard-eKYC-Latam"
    assert spec.step("data_extraction_ocr").provider_chain == (
        "textract_ocr",
        "documentai_ocr",
        "tesseract_ocr",
    )
    assert spec.step("liveness_check").compensable is False
    assert "liveness_check" in spec.step("biometric_matching").depends_on

    report = FlowSpecValidator().validate(spec)
    assert report.ok is True, [str(issue) for issue in report.errors]
    assert report.resolved_capabilities["data_extraction_ocr"].startswith("ocr.document.v1@")
    assert any(issue.check == "V7" for issue in report.warnings), "falta el aviso del no compensable"


@check("Composición - MIDDLEWARE está prohibido con BO en la resolución")
def _bolivia_rule() -> None:
    document = json.loads(
        (FIXTURES / "flow_standard_ekyc_latam.json").read_text(encoding="utf-8")
    )
    document["decision_policy"]["issuer"] = "MIDDLEWARE"
    report = FlowSpecValidator().validate(FlowSpec.parse(document))
    assert report.ok is False
    error = next(issue for issue in report.errors if issue.check == "V7")
    assert "BO" in error.message and "32(II)" in error.message


@check("Composición - resolución y precedencia")
def _resolution() -> None:
    spec = _load_spec()
    registry = FlowSpecRegistry([spec])
    resolved = registry.resolve(tenant_id="acme", country="MX", document_type="INE_2019")
    assert resolved.spec.name == "Standard-eKYC-Latam"
    assert resolved.ref.content_hash == spec.content_hash

    from onboarding_generico.errors import NoApplicableFlowSpecError

    raises(
        NoApplicableFlowSpecError,
        lambda: registry.resolve(tenant_id="acme", country="FR", document_type="PASSPORT"),
        "resolución sin spec aplicable",
    )


@check("Composición - compilación a ASL y a Cloud Workflows")
def _compilation() -> None:
    spec = _load_spec()
    report = FlowSpecValidator().validate(spec)
    plan = FlowCompiler(report.resolved_capabilities).compile(spec)

    assert plan.waves[0] == ("document_alignment",)
    assert {s.step_id for s in plan.parent_steps} == {"liveness_check"}
    assert {s.step_id for s in plan.merged_steps} == {"mrz_parse", "cross_field_validation"}
    assert plan.step("mrz_parse").tier == ExecutionTier.MERGED

    asl = emit_asl(plan)
    serialized = json.dumps(asl)
    assert asl["StartAt"] == "Wave0"
    assert asl["TimeoutSeconds"] == 31_536_000, "1 año, el máximo real de Standard"
    assert "artifact_refs.$" in serialized, "solo punteros, nunca binarios"
    assert '"mrz_parse"' not in serialized, "los pasos fusionados no generan estado"
    assert ".waitForTaskToken" in serialized

    yaml = emit_cloud_workflows(plan)
    assert "main:" in yaml
    assert "await_callback" not in yaml, "12 h y un slot por endpoint: no sirve"
    assert "liveness_check_suspend" in yaml
    assert "results: null" in yaml, "hay que liberar variables: 512 KB por ejecución"

    assert check_quotas(plan) == ()


# --------------------------------------------------------------------------
# 4. Dominio
# --------------------------------------------------------------------------


@check("Dominio - máquina de estados de la sesión")
def _state_machine() -> None:
    from onboarding_generico.errors import InvalidStateTransitionError

    session = OnboardingSession.start(
        tenant_id=TenantId("acme"),
        subject=SubjectRef("subj-1"),
        country="MX",
        document_type=DocumentType.INE_2019,
        tier="IAL2",
        spec_ref=FlowSpecRef(key="k", version="1.0.0", content_hash="sha256:" + "0" * 64),
        steps=(
            Step(step_id="align", capability=Capability.DOCUMENT_ALIGNMENT),
            Step(step_id="ocr", capability=Capability.OCR_DOCUMENT, depends_on=("align",)),
        ),
        ttl_seconds=3600,
    )
    assert session.state is SessionState.CREATED
    raises(
        InvalidStateTransitionError,
        lambda: session.transition_to(SessionState.DECIDED),
        "transición no declarada",
    )
    # I2: un paso no corre antes que su dependencia.
    assert session.can_run("ocr") is False
    raises(DomainError, lambda: session.start_step("ocr", ProviderRef("p")), "invariante I2")

    advanced = session.start_step("align", ProviderRef("p")).complete_step(
        "align", state=StepState.SUCCEEDED
    )
    assert advanced.can_run("ocr") is True

    sealed = (
        advanced.transition_to(SessionState.COLLECTING)
        .transition_to(SessionState.PROCESSING)
        .transition_to(SessionState.DECIDED)
        .seal()
    )
    assert sealed.state is SessionState.RETAINED
    assert sealed.purge().state is SessionState.PURGED
    # I4: una sesión terminal no admite pasos nuevos.
    raises(
        DomainError,
        lambda: sealed.start_step("ocr", ProviderRef("p")),
        "invariante I4",
    )


@check("Dominio - la cadena de auditoría detecta manipulación")
def _audit_chain() -> None:
    from dataclasses import replace

    chain = AuditChain("acme", "a" * 32)
    chain.append(EventType.SESSION_CREATED, actor="api", attributes={"first_name": "ANNA"})
    chain.append(EventType.STEP_STARTED, actor="worker")
    chain.append(EventType.DECISION_ISSUED, actor="engine")
    chain.verify()

    assert "ANNA" not in str(chain.events[0].attributes), "el log no puede llevar PII"

    altered = list(chain.events)
    altered[1] = replace(altered[1], actor="atacante")
    raises(AuditChainError, lambda: verify_chain(altered), "evento alterado")

    truncated = [chain.events[0], chain.events[2]]
    raises(AuditChainError, lambda: verify_chain(truncated), "evento eliminado")

    reordered = [chain.events[0], chain.events[2], chain.events[1]]
    raises(AuditChainError, lambda: verify_chain(reordered), "eventos reordenados")


@check("Dominio - motor de decisión con razones auditables")
def _decision_engine() -> None:
    def evidence(kind: EvidenceKind, **scores: float) -> Evidence:
        return Evidence.create(
            step_id="s",
            kind=kind,
            provider=ProviderRef("p"),
            verdict=Verdict.PASS,
            scores=scores,
        )

    engine = DecisionEngine(DecisionThresholds(), issuer=DecisionIssuer.MIDDLEWARE)

    clean = engine.evaluate(
        [
            evidence(EvidenceKind.LIVENESS, liveness_score=0.97),
            evidence(EvidenceKind.FACE_MATCH, similarity=0.93),
        ]
    )
    assert clean.outcome is DecisionOutcome.APPROVED

    grey = engine.evaluate([evidence(EvidenceKind.FACE_MATCH, similarity=0.78)])
    assert grey.outcome is DecisionOutcome.MANUAL_REVIEW
    reason = grey.reasons[0]
    assert reason.observed is not None and reason.threshold is not None, "sin trazas no es auditable"

    injection = engine.evaluate(
        [evidence(EvidenceKind.LIVENESS, liveness_score=0.99, injection_detected=1.0)]
    )
    assert injection.outcome is DecisionOutcome.REJECTED
    assert "PAD_INJECTION_DETECTED" in injection.reason_codes

    # El más severo gana.
    mixed = engine.evaluate(
        [
            evidence(EvidenceKind.AML, strong_hits=1.0),
            evidence(EvidenceKind.FACE_MATCH, similarity=0.10),
        ]
    )
    assert mixed.outcome is DecisionOutcome.REJECTED

    # SIGNALS_ONLY nunca emite veredicto (obligatorio en Bolivia).
    signals = DecisionEngine(issuer=DecisionIssuer.SIGNALS_ONLY).evaluate(
        [evidence(EvidenceKind.FACE_MATCH, similarity=0.05)]
    )
    assert signals.outcome is DecisionOutcome.SIGNALS_ONLY
    assert "FACE_NO_MATCH" in signals.reason_codes


# --------------------------------------------------------------------------
# 5. Flujo completo
# --------------------------------------------------------------------------


def _build_container() -> tuple[Any, TenantId]:
    settings = load_settings(
        {
            "OG_ENVIRONMENT": "test",
            "OG_CLOUD_PROVIDER": "inmemory",
            "OG_ARTIFACT_BUCKET": "og-test-artifacts",
            "OG_LOG_LEVEL": "CRITICAL",
        }
    )
    container = build_inmemory_container(settings)
    tenant = TenantId("acme")
    provision_demo_tenant(container, tenant, principal=PRINCIPAL)
    container.spec_registry.publish(_load_spec())
    return container, tenant


def _run_document(container: Any, tenant: TenantId, session_id: str, claims: dict[str, Any]) -> Any:
    key = f"sessions/{session_id}/DOC_FRONT"
    data = b"imagen-frontal"
    ref = container.storage.put(tenant, key, data, content_type="image/jpeg")
    container.ocr.script(ref, TD1)
    container.mrz.script(ref, TD1)
    container.llm.script("MX/INE_2019", claims)
    return SubmitDocument(container).execute(
        SubmitDocumentCommand(
            tenant_id=tenant.value,
            session_id=session_id,
            slot="DOC_FRONT",
            object_key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            principal=PRINCIPAL,
        )
    )


def _run_selfie(
    container: Any, tenant: TenantId, session_id: str, *, similarity: float, score: float = 0.97
) -> Any:
    key = f"sessions/{session_id}/SELFIE"
    data = b"selfie"
    ref = container.storage.put(tenant, key, data, content_type="image/jpeg")
    liveness = container.liveness.create_session(tenant)
    container.liveness.script(liveness.provider_session_id, score=score, audited_image=ref)
    container.face_match.script(ref, ref, similarity)
    return SubmitSelfie(container).execute(
        SubmitSelfieCommand(
            tenant_id=tenant.value,
            session_id=session_id,
            object_key=key,
            sha256=hashlib.sha256(data).hexdigest(),
            size_bytes=len(data),
            liveness_session_id=liveness.provider_session_id,
            principal=PRINCIPAL,
        )
    )


@check("Aplicación - flujo completo hasta decisión sellada")
def _happy_path() -> None:
    container, tenant = _build_container()
    started = StartSession(container).execute(
        StartSessionCommand(
            tenant_id=tenant.value,
            subject_ref="subj-1",
            country="MX",
            document_type="INE_2019",
            principal=PRINCIPAL,
        )
    )
    session_id = started.session_id
    assert {t.slot for t in started.upload_targets} == {"DOC_FRONT", "DOC_BACK", "SELFIE"}

    document = _run_document(container, tenant, session_id, dict(CLAIMS))
    assert document.mrz_valid is True
    assert document.discrepancies == ()
    assert document.steps["semantic_extraction"] == "SUCCEEDED"

    selfie = _run_selfie(container, tenant, session_id, similarity=0.93)
    assert selfie.liveness_passed is True and selfie.matched is True

    session = container.sessions.get(tenant, SessionId(session_id))
    container.sessions.save(session.transition_to(SessionState.PROCESSING))

    decision = ResolveDecision(container).execute(
        ResolveDecisionCommand(
            tenant_id=tenant.value, session_id=session_id, principal=PRINCIPAL
        )
    )
    assert decision.outcome == "SIGNALS_ONLY", "el tenant está configurado como SIGNALS_ONLY"
    assert decision.state == str(SessionState.RETAINED)
    assert decision.evidence_manifest.startswith("sha256:")

    trail = container.sessions.audit_trail(tenant, SessionId(session_id))
    verify_chain(trail)
    assert "ERIKSSON" not in str([event.attributes for event in trail])

    events = container.events.published_for(tenant, session_id)
    assert len(events) == 1 and events[0].event_type == "og.session.decided"


@check("Aplicación - banda gris deriva a revisión humana y se resuelve")
def _grey_band_review() -> None:
    container, tenant = _build_container()
    session_id = StartSession(container).execute(
        StartSessionCommand(
            tenant_id=tenant.value,
            subject_ref="subj-2",
            country="MX",
            document_type="INE_2019",
            principal=PRINCIPAL,
        )
    ).session_id

    _run_document(container, tenant, session_id, dict(CLAIMS))
    selfie = _run_selfie(container, tenant, session_id, similarity=0.78)
    assert selfie.grey_band is True

    session = container.sessions.get(tenant, SessionId(session_id))
    container.sessions.save(session.transition_to(SessionState.PROCESSING))
    decision = ResolveDecision(container).execute(
        ResolveDecisionCommand(
            tenant_id=tenant.value, session_id=session_id, principal=PRINCIPAL
        )
    )
    assert decision.review_case_id is not None
    assert decision.state == str(SessionState.PENDING_REVIEW)

    container.authorization.grant(PRINCIPAL, tenant, ["review:read", "review:resolve"])
    review = HandleManualReview(container)
    case = review.assign_next(
        AssignCaseCommand(tenant_id=tenant.value, reviewer="ana", principal=PRINCIPAL)
    )
    assert case is not None and case.state == "IN_REVIEW"
    assert "FACE_GREY_BAND" in case.reasons

    resolution = review.resolve(
        ResolveCaseCommand(
            tenant_id=tenant.value,
            case_id=case.case_id,
            reviewer="ana",
            outcome="APPROVED",
            principal=PRINCIPAL,
        )
    )
    assert resolution.outcome == "APPROVED"
    assert resolution.session_state == str(SessionState.RETAINED)


@check("Aplicación - discrepancia entre MRZ y extracción se reporta")
def _cross_field_discrepancy() -> None:
    container, tenant = _build_container()
    session_id = StartSession(container).execute(
        StartSessionCommand(
            tenant_id=tenant.value,
            subject_ref="subj-3",
            country="MX",
            document_type="INE_2019",
            principal=PRINCIPAL,
        )
    ).session_id
    result = _run_document(container, tenant, session_id, dict(CLAIMS, birth_date="1980-01-01"))
    assert "birth_date" in result.discrepancies
    assert result.steps["cross_field_validation"] == "NEGATIVE"


@check("Aplicación - aislamiento entre tenants")
def _tenant_isolation() -> None:
    from onboarding_generico.errors import SessionNotFoundError, TenantIsolationError

    container, tenant = _build_container()
    session_id = StartSession(container).execute(
        StartSessionCommand(
            tenant_id=tenant.value,
            subject_ref="subj-4",
            country="MX",
            document_type="INE_2019",
            principal=PRINCIPAL,
        )
    ).session_id
    other = TenantId("globex")
    assert container.sessions.find(other, SessionId(session_id)) is None
    raises(
        SessionNotFoundError,
        lambda: container.sessions.get(other, SessionId(session_id)),
        "lectura cruzada de sesión",
    )

    ref = container.storage.put(tenant, "sessions/x/DOC", b"datos")
    raises(
        TenantIsolationError,
        lambda: container.storage.get(other, ref),
        "lectura cruzada de objeto",
    )


@check("Aplicación - purga, bloqueo y crypto-shredding")
def _purge() -> None:
    from dataclasses import replace

    container, tenant = _build_container()
    session_id = StartSession(container).execute(
        StartSessionCommand(
            tenant_id=tenant.value,
            subject_ref="subj-5",
            country="MX",
            document_type="INE_2019",
            principal=PRINCIPAL,
        )
    ).session_id
    _run_document(container, tenant, session_id, dict(CLAIMS))

    session = container.sessions.get(tenant, SessionId(session_id))
    container.sessions.save(
        replace(
            session.transition_to(SessionState.EXPIRED),
            created_at=session.created_at - timedelta(days=30),
        )
    )

    encrypted = container.cipher.encrypt_item(tenant, {"id_number": "D23145890"})
    result = PurgeTenantData(container).execute(
        PurgeCommand(tenant_id=tenant.value, principal=PRINCIPAL, shred_tenant_key=True)
    )
    assert session_id in result.sessions_purged
    assert result.key_shredded is True
    assert container.sessions.find(tenant, SessionId(session_id)) is None

    # La constancia de la purga sobrevive, sin PII.
    trail = container.sessions.audit_trail(tenant, SessionId(session_id))
    assert any(str(event.event_type) == "PURGE_COMPLETED" for event in trail)
    verify_chain(trail)

    raises(
        KeyDestroyedError,
        lambda: container.cipher.decrypt_item(tenant, encrypted),
        "descifrado tras crypto-shredding",
    )


@check("Arquitectura - el paquete se importa sin SDKs de nube")
def _no_cloud_sdk() -> None:
    import importlib
    import pkgutil

    import onboarding_generico

    for module in pkgutil.walk_packages(onboarding_generico.__path__, "onboarding_generico."):
        importlib.import_module(module.name)
    for forbidden in ("boto3", "botocore", "google.cloud", "onnxruntime", "cv2"):
        assert forbidden not in sys.modules, f"{forbidden} se cargó al importar el paquete"


# --------------------------------------------------------------------------
# Ejecución
# --------------------------------------------------------------------------


def main() -> int:
    passed = 0
    failures: list[tuple[str, str]] = []
    for name, function in _CHECKS:
        try:
            function()
        except Exception:  # noqa: BLE001 - se reporta el detalle completo
            failures.append((name, traceback.format_exc()))
            print(f"FALLO  {name}")
        else:
            passed += 1
            print(f"OK     {name}")

    total = len(_CHECKS)
    print("-" * 70)
    if failures:
        for name, trace in failures:
            print(f"\n=== {name} ===\n{trace}")
        print(f"{passed}/{total} comprobaciones pasaron, {len(failures)} fallaron")
        return 1
    print(f"{passed}/{total} comprobaciones pasaron")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
