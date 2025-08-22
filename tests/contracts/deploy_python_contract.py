import pathlib

from stellar_sdk import Keypair, Network, SorobanServer
from stellar_sdk.contract import ContractClient

soroban_server_url = "https://soroban-testnet.stellar.org"
kp = Keypair.from_secret("SAP7MDXJBWT3VODMOGDENNYHY6IRJRWCX4YH3HZW22LTMZ7NOTXGF3DM")

base_dir = pathlib.Path(__file__).parent
wasm_path = base_dir / "target" / "wasm32v1-none" / "release" / "python.wasm"

with open(wasm_path, "rb") as f:
    wasm_bytes = f.read()

soroban_server = SorobanServer(soroban_server_url)

wasm_id = ContractClient.upload_contract_wasm(wasm_bytes, kp.public_key, kp, soroban_server,
                                              network_passphrase=Network.TESTNET_NETWORK_PASSPHRASE)
print(f"WASM Uploaded, ID: {wasm_id.hex()}")

contract_id = ContractClient.create_contract(wasm_id, kp.public_key, kp, soroban_server,
                                             network_passphrase=Network.TESTNET_NETWORK_PASSPHRASE, salt=b'\x00' * 32)
print(f"Contract Created, ID: {contract_id}")
