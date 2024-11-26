# stellar-contract-bindings

`stellar-contract-bindings` is a CLI tool designed to generate language bindings for Stellar Soroban smart contracts.

This tool simplifies the process of interacting with Soroban contracts by generating the necessary code to call contract methods directly from your preferred programming language. Currently, it supports Python. [stellar-cli](https://github.com/stellar/stellar-cli) provides support for TypeScript and Rust.

## Installation

You can install `stellar-contract-bindings` using pip:

```shell
pip install stellar-contract-bindings
```

## Usage

To generate bindings for a Soroban contract, use the `generate` command with the required options:

```shell
stellar-contract-bindings generate --contract-id CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF
```

### Options

- `--contract-id`: The contract ID to generate bindings for (required).
- `--rpc-url`: The Soroban RPC URL (default: https://mainnet.sorobanrpc.com).
- `--language`: The target language for bindings (default: python).
- `--output`: Output directory for generated bindings (defaults to the current directory).

### Example

```shell
stellar-contract-bindings generate --contract-id CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF --rpc-url https://mainnet.sorobanrpc.com --language python --output ./bindings
```

This command will generate Python binding for the specified contract and save it in the `./bindings` directory.

### Using the Generated Binding

#### Python

After generating the binding, you can use it to interact with your Soroban contract. Here's an example:

```python
from stellar_sdk import Network
from bindings import Client # Import the generated bindings

contract_id = "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF"
rpc_url = "https://mainnet.sorobanrpc.com"
network_passphrase = Network.PUBLIC_NETWORK_PASSPHRASE

client = Client(contract_id, rpc_url, network_passphrase)
assembled_tx = client.hello(b"world")
print(assembled_tx.result())
# assembled_tx.sign_and_submit()
```

## License

This project is licensed under the Apache-2.0 License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please open an issue or submit a pull request for any improvements or bug fixes.
