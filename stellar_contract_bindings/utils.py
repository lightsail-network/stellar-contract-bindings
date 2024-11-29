from typing import List

from stellar_sdk import SorobanServer
from stellar_sdk import xdr, Address
from stellar_contract_bindings.metadata import (
    parse_contract_metadata,
    get_token_sc_spec_entry,
)


def get_specs_by_wasm_hash(wasm_hash: bytes, rpc_url: str) -> list[xdr.SCSpecEntry]:
    """Get the contract wasm by wasm hash.

    :param wasm_hash: The wasm hash.
    :param rpc_url: The Soroban RPC URL.
    :return: The contract wasm.
    :raises ValueError: If wasm not found.
    """
    with SorobanServer(rpc_url) as server:
        key = xdr.LedgerKey(
            xdr.LedgerEntryType.CONTRACT_CODE,
            contract_code=xdr.LedgerKeyContractCode(hash=xdr.Hash(wasm_hash)),
        )
        resp = server.get_ledger_entries([key])
        if not resp.entries:
            raise ValueError(f"Wasm not found, wasm id: {wasm_hash.hex()}")
        data = xdr.LedgerEntryData.from_xdr(resp.entries[0].xdr)
        meta_data = data.contract_code.code
        return parse_contract_metadata(meta_data).spec


def get_specs_by_contract_id(contract_id: str, rpc_url: str) -> list[xdr.SCSpecEntry]:
    """Get the wasm hash by contract id.

    :param contract_id: The contract id.
    :param rpc_url: The Soroban RPC URL.
    :return: The wasm hash.
    :raises ValueError: If contract not found.
    """
    with SorobanServer(rpc_url) as server:
        key = xdr.LedgerKey(
            xdr.LedgerEntryType.CONTRACT_DATA,
            contract_data=xdr.LedgerKeyContractData(
                contract=Address(contract_id).to_xdr_sc_address(),
                key=xdr.SCVal(xdr.SCValType.SCV_LEDGER_KEY_CONTRACT_INSTANCE),
                durability=xdr.ContractDataDurability.PERSISTENT,
            ),
        )
        resp = server.get_ledger_entries([key])
        if not resp.entries:
            raise ValueError(f"Contract not found, contract id: {contract_id}")
        data = xdr.LedgerEntryData.from_xdr(resp.entries[0].xdr)
        if (
            data.contract_data.val.instance.executable.type
            == xdr.ContractExecutableType.CONTRACT_EXECUTABLE_STELLAR_ASSET
        ):
            return get_token_sc_spec_entry()
        elif (
            data.contract_data.val.instance.executable.type
            == xdr.ContractExecutableType.CONTRACT_EXECUTABLE_WASM
        ):
            return get_specs_by_wasm_hash(
                data.contract_data.val.instance.executable.wasm_hash.hash, rpc_url
            )
        else:
            raise ValueError(
                f"Unknown executable type, type: {data.contract_data.val.instance.executable.type}"
            )


if __name__ == "__main__":
    get_specs_by_contract_id(
        "CAS3J7GYLGXMF6TDJBBYYSE3HQ6BBSMLNUQ34T6TZMYMW2EVH34XOWMA",
        "https://mainnet.sorobanrpc.com",
    )
