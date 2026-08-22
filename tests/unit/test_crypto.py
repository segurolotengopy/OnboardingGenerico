"""Pruebas de la capa criptográfica: AAD, política por campo y caché atómica."""

from __future__ import annotations

import threading
import time
from typing import Any

import pytest

from onboarding_generico.crypto.envelope import (
    ENVELOPE_VERSION,
    DeterministicRandom,
    Envelope,
    EnvelopeCipher,
    EnvelopeFieldCipher,
    LocalKeyProvider,
    build_aad,
    shred_tenant_key,
)
from onboarding_generico.crypto.field_policy import (
    ENCRYPTED_FIELDS,
    CryptoAction,
    FieldPolicy,
    apply_policy,
    default_policy,
)
from onboarding_generico.crypto.material_cache import (
    AtomicMaterialCache,
    CachedKeyProvider,
    tenant_cache_key,
)
from onboarding_generico.domain.value_objects import TenantId
from onboarding_generico.errors import DecryptionError, KeyDestroyedError, ValidationError


@pytest.fixture()
def keys() -> LocalKeyProvider:
    return LocalKeyProvider(b"root-key-de-prueba-32-bytes-xxxx")


@pytest.fixture()
def cipher(keys: LocalKeyProvider) -> EnvelopeCipher:
    return EnvelopeCipher(keys)


@pytest.fixture()
def field_cipher(keys: LocalKeyProvider, cipher: EnvelopeCipher) -> EnvelopeFieldCipher:
    return EnvelopeFieldCipher(cipher, keys)


# --------------------------------------------------------------------------
# Cifrado de sobre y AAD
# --------------------------------------------------------------------------


def test_roundtrip(cipher: EnvelopeCipher, tenant: TenantId) -> None:
    envelope = cipher.encrypt(tenant, b"datos sensibles")
    assert cipher.decrypt(tenant, envelope) == b"datos sensibles"
    assert envelope.version == ENVELOPE_VERSION


def test_decrypting_with_another_tenant_fails(
    cipher: EnvelopeCipher, tenant: TenantId, other_tenant: TenantId
) -> None:
    """**La prueba central del aislamiento multi-tenant.**

    GCP no puede aplicar aislamiento en el plano de datos, así que un error de
    alcance debe producir un fallo de descifrado, nunca una lectura cruzada.
    """
    envelope = cipher.encrypt(tenant, b"numero de documento")
    with pytest.raises(DecryptionError) as excinfo:
        cipher.decrypt(other_tenant, envelope)
    assert excinfo.value.code == "OG_DECRYPTION_FAILED"


def test_decrypting_with_another_context_fails(cipher: EnvelopeCipher, tenant: TenantId) -> None:
    """El contexto entra en el AAD: mover un valor de campo invalida el sobre."""
    envelope = cipher.encrypt(tenant, b"valor", context={"field": "id_number"})
    assert cipher.decrypt(tenant, envelope, context={"field": "id_number"}) == b"valor"
    with pytest.raises(DecryptionError):
        cipher.decrypt(tenant, envelope, context={"field": "first_name"})


def test_tampered_ciphertext_fails_authentication(
    cipher: EnvelopeCipher, tenant: TenantId
) -> None:
    envelope = cipher.encrypt(tenant, b"valor original")
    tampered = Envelope(
        version=envelope.version,
        wrapped_key=envelope.wrapped_key,
        nonce=envelope.nonce,
        ciphertext="AAAA" + envelope.ciphertext[4:],
        tag=envelope.tag,
    )
    with pytest.raises(DecryptionError):
        cipher.decrypt(tenant, tampered)


def test_malformed_envelope_is_rejected(cipher: EnvelopeCipher, tenant: TenantId) -> None:
    with pytest.raises(DecryptionError):
        cipher.decrypt(tenant, {"version": ENVELOPE_VERSION, "nonce": "x"})


def test_nonce_is_fresh_per_encryption(cipher: EnvelopeCipher, tenant: TenantId) -> None:
    first = cipher.encrypt(tenant, b"mismo texto")
    second = cipher.encrypt(tenant, b"mismo texto")
    assert first.nonce != second.nonce
    assert first.ciphertext != second.ciphertext


def test_aad_starts_with_tenant(tenant: TenantId) -> None:
    aad = build_aad(tenant, context={"field": "id_number"})
    assert aad.startswith(f"{ENVELOPE_VERSION}|tenant={tenant.value}".encode())


def test_deterministic_random_is_reproducible() -> None:
    left = DeterministicRandom(b"semilla")
    right = DeterministicRandom(b"semilla")
    assert left.token_bytes(16) == right.token_bytes(16)


# --------------------------------------------------------------------------
# Cifrado por campo
# --------------------------------------------------------------------------


def test_encrypt_item_applies_policy(field_cipher: EnvelopeFieldCipher, tenant: TenantId) -> None:
    item = {"tenant_id": "acme", "session_id": "s1", "id_number": "D23145890", "state": "CREATED"}
    encrypted = field_cipher.encrypt_item(tenant, item)

    # SIGN_ONLY viaja en claro; ENCRYPT_AND_SIGN se sustituye por un sobre.
    assert encrypted["tenant_id"] == "acme"
    assert encrypted["state"] == "CREATED"
    assert "id_number" not in encrypted
    assert "__og_env__id_number" in encrypted
    assert "D23145890" not in str(encrypted)
    assert field_cipher.decrypt_item(tenant, encrypted) == item


def test_decrypt_item_with_wrong_tenant_fails(
    field_cipher: EnvelopeFieldCipher, tenant: TenantId, other_tenant: TenantId
) -> None:
    encrypted = field_cipher.encrypt_item(tenant, {"id_number": "D23145890"})
    with pytest.raises(DecryptionError):
        field_cipher.decrypt_item(other_tenant, encrypted)


def test_record_signature_detects_tampering_of_signed_fields(
    field_cipher: EnvelopeFieldCipher, tenant: TenantId
) -> None:
    """Un atributo `SIGN_ONLY` viaja en claro pero no se puede alterar."""
    encrypted = field_cipher.encrypt_item(tenant, {"state": "CREATED", "id_number": "X"})
    encrypted["state"] = "DECIDED"
    with pytest.raises(DecryptionError):
        field_cipher.decrypt_item(tenant, encrypted)


def test_beacon_is_deterministic_and_tenant_scoped(
    field_cipher: EnvelopeFieldCipher, tenant: TenantId, other_tenant: TenantId
) -> None:
    first = field_cipher.beacon(tenant, "email", "a@b.c")
    second = field_cipher.beacon(tenant, "email", "a@b.c")
    other = field_cipher.beacon(other_tenant, "email", "a@b.c")
    assert first == second
    assert first != other
    assert first.startswith(f"{tenant.value}#")
    assert "a@b.c" not in first


def test_beacon_differs_per_field(field_cipher: EnvelopeFieldCipher, tenant: TenantId) -> None:
    assert field_cipher.beacon(tenant, "email", "x") != field_cipher.beacon(tenant, "phone", "x")


# --------------------------------------------------------------------------
# Política por campo
# --------------------------------------------------------------------------


def test_default_action_is_encrypt() -> None:
    """Un campo nuevo sin clasificar se protege, no se filtra."""
    policy = default_policy()
    assert policy.action_for("campo_nuevo_sin_clasificar") is CryptoAction.ENCRYPT_AND_SIGN
    assert policy.action_for("tenant_id") is CryptoAction.SIGN_ONLY
    assert policy.action_for("cache_hint") is CryptoAction.DO_NOTHING


def test_index_keys_cannot_be_encrypted_or_carry_pii() -> None:
    policy = default_policy()
    policy.assert_keys_are_safe(["tenant_id", "session_id", "state"])
    with pytest.raises(ValidationError):
        policy.assert_keys_are_safe(["id_number"])
    with pytest.raises(ValidationError):
        policy.assert_keys_are_safe(["campo_desconocido"])


def test_no_pii_field_is_sign_only() -> None:
    """Verificación de arquitectura: ningún campo PII puede ir en claro."""
    policy = default_policy()
    for field_name in ENCRYPTED_FIELDS:
        assert policy.action_for(field_name) is CryptoAction.ENCRYPT_AND_SIGN


def test_apply_policy_classifies() -> None:
    buckets = apply_policy(default_policy(), {"tenant_id": 1, "id_number": 2, "cache_hint": 3})
    assert buckets["sign_only"] == ["tenant_id"]
    assert buckets["encrypt"] == ["id_number"]
    assert buckets["unprotected"] == ["cache_hint"]


def test_with_overrides_is_immutable() -> None:
    base = default_policy()
    extended = base.with_overrides({"campo_tenant": CryptoAction.SIGN_ONLY})
    assert extended.action_for("campo_tenant") is CryptoAction.SIGN_ONLY
    assert base.action_for("campo_tenant") is CryptoAction.ENCRYPT_AND_SIGN


def test_custom_policy_default_action() -> None:
    policy = FieldPolicy(directives={}, default_action=CryptoAction.SIGN_ONLY)
    assert policy.action_for("lo-que-sea") is CryptoAction.SIGN_ONLY


# --------------------------------------------------------------------------
# Crypto-shredding
# --------------------------------------------------------------------------


def test_shredding_makes_data_unrecoverable(
    keys: LocalKeyProvider, cipher: EnvelopeCipher, tenant: TenantId
) -> None:
    envelope = cipher.encrypt(tenant, b"expediente")
    assert shred_tenant_key(keys, tenant) is True
    assert keys.is_shredded(tenant) is True
    with pytest.raises(KeyDestroyedError):
        cipher.decrypt(tenant, envelope)
    # Es idempotente: destruir dos veces no vuelve a "destruir".
    assert shred_tenant_key(keys, tenant) is False


def test_shredding_one_tenant_does_not_affect_another(
    keys: LocalKeyProvider, cipher: EnvelopeCipher, tenant: TenantId, other_tenant: TenantId
) -> None:
    envelope = cipher.encrypt(other_tenant, b"otro expediente")
    shred_tenant_key(keys, tenant)
    assert cipher.decrypt(other_tenant, envelope) == b"otro expediente"


# --------------------------------------------------------------------------
# Caché de material criptográfico
# --------------------------------------------------------------------------


def test_cache_hit_and_miss_accounting() -> None:
    cache: AtomicMaterialCache[int] = AtomicMaterialCache(ttl_seconds=60)
    assert cache.get_or_load("k", lambda: 1) == 1
    assert cache.get_or_load("k", lambda: 2) == 1
    stats = cache.stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 1
    assert stats["loads"] == 1


def test_cache_expires_by_ttl() -> None:
    clock = {"now": 0.0}
    cache: AtomicMaterialCache[int] = AtomicMaterialCache(
        ttl_seconds=10, clock=lambda: clock["now"]
    )
    cache.get_or_load("k", lambda: 1)
    clock["now"] = 11.0
    assert cache.get_or_load("k", lambda: 2) == 2
    assert cache.stats()["expirations"] == 1


def test_atomic_load_prevents_cache_stampede() -> None:
    """La razón de existir de este módulo.

    Con `CachingCryptoMaterialsManager`, al expirar la entrada **todos** los
    hilos fallan a la vez y todos llaman a KMS. Aquí, N hilos que fallan sobre
    la misma clave producen exactamente **una** carga.
    """
    cache: AtomicMaterialCache[int] = AtomicMaterialCache(ttl_seconds=60)
    loads = {"count": 0}
    lock = threading.Lock()
    barrier = threading.Barrier(16)

    def slow_loader() -> int:
        with lock:
            loads["count"] += 1
        time.sleep(0.02)  # simula la latencia de KMS
        return 42

    results: list[int] = []
    results_lock = threading.Lock()

    def worker() -> None:
        barrier.wait()
        value = cache.get_or_load("tenant:acme:field", slow_loader)
        with results_lock:
            results.append(value)

    threads = [threading.Thread(target=worker) for _ in range(16)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()

    assert loads["count"] == 1, "el cargador se ejecutó más de una vez: hubo cache stampede"
    assert results == [42] * 16
    assert cache.stats()["loads"] == 1


def test_cache_does_not_serialize_across_keys() -> None:
    """Cargar material del tenant A no bloquea al tenant B."""
    cache: AtomicMaterialCache[int] = AtomicMaterialCache(ttl_seconds=60)
    order: list[str] = []

    def loader(name: str, delay: float) -> Any:
        def _load() -> int:
            time.sleep(delay)
            order.append(name)
            return len(name)

        return _load

    slow = threading.Thread(target=lambda: cache.get_or_load("a", loader("lento", 0.05)))
    fast = threading.Thread(target=lambda: cache.get_or_load("b", loader("rapido", 0.0)))
    slow.start()
    time.sleep(0.005)
    fast.start()
    slow.join()
    fast.join()
    assert order == ["rapido", "lento"]


def test_cache_eviction_respects_max_entries() -> None:
    cache: AtomicMaterialCache[int] = AtomicMaterialCache(ttl_seconds=60, max_entries=2)
    for index in range(5):
        cache.get_or_load(f"k{index}", lambda i=index: i)  # type: ignore[misc]
    assert len(cache) <= 2
    assert cache.stats()["evictions"] >= 3


def test_invalidate_prefix_clears_a_tenant() -> None:
    cache: AtomicMaterialCache[int] = AtomicMaterialCache(ttl_seconds=60)
    cache.get_or_load(tenant_cache_key("acme", "field"), lambda: 1)
    cache.get_or_load(tenant_cache_key("acme", "sign"), lambda: 2)
    cache.get_or_load(tenant_cache_key("globex", "field"), lambda: 3)
    assert cache.invalidate_prefix("acme:") == 2
    assert tenant_cache_key("globex", "field") in cache


def test_cache_rejects_invalid_configuration() -> None:
    with pytest.raises(ValueError):
        AtomicMaterialCache(ttl_seconds=0)
    with pytest.raises(ValueError):
        AtomicMaterialCache(max_entries=0)


def test_cached_key_provider_only_caches_deterministic_material(
    keys: LocalKeyProvider, tenant: TenantId
) -> None:
    cached = CachedKeyProvider(keys)
    first = cached.derive_key(tenant, purpose="sign")
    second = cached.derive_key(tenant, purpose="sign")
    assert first == second
    assert cached.cache.stats()["loads"] == 1

    # Una clave de datos es aleatoria por operación y NO debe cachearse:
    # reutilizarla con el mismo nonce rompería el cifrado.
    plain_a, _ = cached.data_key_for(tenant)
    plain_b, _ = cached.data_key_for(tenant)
    assert plain_a != plain_b


def test_cached_key_provider_invalidates_on_shred(
    keys: LocalKeyProvider, tenant: TenantId
) -> None:
    """Sin invalidar la caché, el borrado no sería efectivo hasta el TTL."""
    cached = CachedKeyProvider(keys)
    cached.derive_key(tenant, purpose="sign")
    assert len(cached.cache) == 1
    assert cached.shred_tenant_key(tenant) is True
    assert len(cached.cache) == 0
    with pytest.raises(KeyDestroyedError):
        cached.derive_key(tenant, purpose="sign")
