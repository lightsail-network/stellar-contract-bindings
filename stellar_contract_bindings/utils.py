from stellar_sdk import SorobanServer
from stellar_sdk import xdr, Address


def get_contract_wasm_by_hash(wasm_hash: bytes, rpc_url: str) -> bytes:
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
        return data.contract_code.code


def get_wasm_hash_by_contract_id(contract_id: str, rpc_url: str) -> bytes:
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
        return data.contract_data.val.instance.executable.wasm_hash.hash
