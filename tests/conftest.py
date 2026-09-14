import pytest

from . import reference_contract

_CACHE_KEY = "stellar-contract-bindings/reference-contract"


@pytest.fixture(scope="session")
def reference_contract_id(request) -> str:
    """The reference contract, deployed to testnet for this session.

    Deployed once per session, and reused across sessions through pytest's
    cache for as long as the contract is still on the ledger and was built
    from the wasm the tests now hold; after a testnet reset, or a rebuild of
    the contract, it is simply deployed again. Skips when
    STELLAR_BINDINGS_OFFLINE=1.
    """
    if reference_contract.OFFLINE:
        pytest.skip("STELLAR_BINDINGS_OFFLINE=1")
    digest = reference_contract.wasm_digest()
    cached = request.config.cache.get(_CACHE_KEY, None)
    if (
        isinstance(cached, dict)
        and cached.get("wasm") == digest
        and reference_contract.exists(cached["contract_id"])
    ):
        return cached["contract_id"]
    contract_id = reference_contract.deploy()
    request.config.cache.set(_CACHE_KEY, {"wasm": digest, "contract_id": contract_id})
    return contract_id
