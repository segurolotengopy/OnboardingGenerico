"""Pruebas de la cadena de hash del log de auditoría (invariante I8)."""

from __future__ import annotations

from dataclasses import replace

import pytest

from onboarding_generico.domain.enums import EventType
from onboarding_generico.domain.events import (
    GENESIS_HASH,
    AuditChain,
    AuditEvent,
    canonical_json,
    verify_chain,
)
from onboarding_generico.errors import AuditChainError


def _chain(count: int = 3) -> AuditChain:
    chain = AuditChain("acme", "a" * 32)
    types = [EventType.SESSION_CREATED, EventType.STEP_STARTED, EventType.STEP_COMPLETED]
    for index in range(count):
        chain.append(types[index % len(types)], actor="worker", attributes={"i": index})
    return chain


# --------------------------------------------------------------------------
# Encadenado
# --------------------------------------------------------------------------


def test_first_event_links_to_genesis() -> None:
    chain = _chain(1)
    event = chain.events[0]
    assert event.previous_hash == GENESIS_HASH
    assert event.sequence == 0
    assert event.is_intact() is True


def test_each_event_links_to_the_previous() -> None:
    chain = _chain(4)
    for previous, current in zip(chain.events, chain.events[1:], strict=False):
        assert current.previous_hash == previous.event_hash
        assert current.sequence == previous.sequence + 1
    chain.verify()


def test_hash_covers_previous_hash() -> None:
    """Si el hash no cubriera `previous_hash`, no sería una cadena."""
    chain = _chain(2)
    tampered = replace(chain.events[1], previous_hash=GENESIS_HASH)
    assert tampered.is_intact() is False


def test_head_hash_of_empty_chain_is_genesis() -> None:
    assert AuditChain("acme", "b" * 32).head_hash == GENESIS_HASH


def test_event_from_another_session_is_rejected() -> None:
    chain = _chain(1)
    with pytest.raises(AuditChainError):
        AuditEvent.create(
            tenant_id="acme",
            session_id="c" * 32,
            event_type=EventType.STEP_STARTED,
            actor="worker",
            previous=chain.events[0],
        )


# --------------------------------------------------------------------------
# Detección de manipulación
# --------------------------------------------------------------------------


def test_altering_an_event_breaks_integrity() -> None:
    chain = _chain(3)
    events = list(chain.events)
    events[1] = replace(events[1], actor="atacante")
    with pytest.raises(AuditChainError) as excinfo:
        verify_chain(events)
    assert "alterado" in excinfo.value.message


def test_altering_attributes_breaks_integrity() -> None:
    chain = _chain(2)
    events = list(chain.events)
    events[0] = replace(events[0], attributes={"i": 999})
    with pytest.raises(AuditChainError):
        verify_chain(events)


def test_deleting_an_event_breaks_the_link() -> None:
    chain = _chain(3)
    events = [chain.events[0], chain.events[2]]
    with pytest.raises(AuditChainError):
        verify_chain(events)


def test_reordering_events_breaks_the_chain() -> None:
    chain = _chain(3)
    events = [chain.events[0], chain.events[2], chain.events[1]]
    with pytest.raises(AuditChainError):
        verify_chain(events)


def test_inserting_a_forged_event_breaks_numbering() -> None:
    chain = _chain(2)
    forged = AuditEvent.create(
        tenant_id="acme",
        session_id=chain.session_id,
        event_type=EventType.DECISION_ISSUED,
        actor="atacante",
        previous=chain.events[0],
    )
    events = [chain.events[0], forged, chain.events[1]]
    with pytest.raises(AuditChainError):
        verify_chain(events)


# --------------------------------------------------------------------------
# Redacción y manifiesto
# --------------------------------------------------------------------------


def test_attributes_are_redacted_on_creation() -> None:
    """El log de auditoría es un artefacto de cumplimiento, no un volcado."""
    chain = AuditChain("acme", "d" * 32)
    event = chain.append(
        EventType.SESSION_CREATED,
        actor="api",
        attributes={"first_name": "ANNA", "id_number": "D23145890", "country": "MX"},
    )
    assert "ANNA" not in str(event.attributes)
    assert "D23145890" not in str(event.attributes)
    assert event.attributes["country"] == "MX"
    assert str(event.attributes["first_name"]).startswith("[REDACTED]")


def test_redaction_is_stable_for_the_same_value() -> None:
    """La huella redactada permite correlacionar sin revelar el valor."""
    chain = AuditChain("acme", "e" * 32)
    first = chain.append(EventType.STEP_STARTED, actor="w", attributes={"id_number": "X1"})
    second = chain.append(EventType.STEP_STARTED, actor="w", attributes={"id_number": "X1"})
    third = chain.append(EventType.STEP_STARTED, actor="w", attributes={"id_number": "X2"})
    assert first.attributes["id_number"] == second.attributes["id_number"]
    assert first.attributes["id_number"] != third.attributes["id_number"]


def test_manifest_changes_with_the_chain() -> None:
    chain = _chain(2)
    before = chain.manifest()
    chain.append(EventType.DECISION_ISSUED, actor="engine")
    assert chain.manifest() != before
    assert chain.manifest().startswith("sha256:")


def test_canonical_json_is_order_independent() -> None:
    assert canonical_json({"b": 1, "a": 2}) == canonical_json({"a": 2, "b": 1})
    assert " " not in canonical_json({"a": 1, "b": 2})


def test_as_dict_roundtrip_keeps_hash() -> None:
    event = _chain(1).events[0]
    data = event.as_dict()
    assert data["event_hash"] == event.event_hash
    assert data["previous_hash"] == GENESIS_HASH
    assert data["sequence"] == 0
