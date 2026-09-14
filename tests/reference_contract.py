"""The reference contract the end-to-end tests call.

``tests/contracts/contracts/python`` is a contract that declares every spec
type, built to ``tests/fixtures/python.wasm``. Its spec is what the generator
tests read, and the tests that need a contract on a network deploy that wasm
to testnet themselves, from a throwaway account funded by friendbot. Nothing
about the deployment is stored, so a testnet reset costs nothing: the next
test session deploys again.

Deploying takes two transactions, about fifteen seconds, and happens once
per test session; a deployment is remembered in pytest's cache and reused
while the contract still exists. Set ``STELLAR_BINDINGS_OFFLINE=1`` to skip
every test that reaches the network.

Run this module to deploy by hand::

    uv run python -m tests.reference_contract
"""

import hashlib
import os
import pathlib
import time

import requests
from stellar_sdk import Keypair, Network, SorobanServer, xdr
from stellar_sdk.contract import ContractClient

from stellar_contract_bindings.utils import get_specs_by_wasm_file

WASM = pathlib.Path(__file__).parent / "fixtures" / "python.wasm"
RPC_URL = "https://soroban-testnet.stellar.org"
NETWORK_PASSPHRASE = Network.TESTNET_NETWORK_PASSPHRASE
FRIENDBOT_URL = "https://friendbot.stellar.org"

OFFLINE = os.environ.get("STELLAR_BINDINGS_OFFLINE") == "1"


def specs() -> list[xdr.SCSpecEntry]:
    """The reference contract's spec entries, read from the wasm."""
    return get_specs_by_wasm_file(str(WASM))


def wasm_digest() -> str:
    """Identifies the build a deployment was made from, so that a rebuilt
    contract is deployed afresh rather than reached through a stale one."""
    return hashlib.sha256(WASM.read_bytes()).hexdigest()


def fund(account_id: str) -> None:
    """Create and fund a testnet account through friendbot.

    Friendbot is rate-limited, so a refusal is retried a few times before it
    is reported.
    """
    last_error: Exception | None = None
    for attempt in range(3):
        try:
            response = requests.get(
                FRIENDBOT_URL, params={"addr": account_id}, timeout=60
            )
            response.raise_for_status()
            return
        except requests.RequestException as e:
            last_error = e
            time.sleep(2 * (attempt + 1))
    raise RuntimeError(f"friendbot could not fund {account_id}") from last_error


def deploy() -> str:
    """Deploy the reference contract to testnet and return its contract ID."""
    deployer = Keypair.random()
    fund(deployer.public_key)
    with SorobanServer(RPC_URL) as server:
        wasm_id = ContractClient.upload_contract_wasm(
            WASM.read_bytes(),
            deployer.public_key,
            deployer,
            server,
            network_passphrase=NETWORK_PASSPHRASE,
        )
        return ContractClient.create_contract(
            wasm_id,
            deployer.public_key,
            deployer,
            server,
            network_passphrase=NETWORK_PASSPHRASE,
        )


def exists(contract_id: str) -> bool:
    """Whether the contract instance is on the ledger, so a testnet reset
    since the last deployment is noticed rather than trusted."""
    with SorobanServer(RPC_URL) as server:
        instance = xdr.SCVal(xdr.SCValType.SCV_LEDGER_KEY_CONTRACT_INSTANCE)
        return server.get_contract_data(contract_id, instance) is not None


if __name__ == "__main__":
    print(deploy())
