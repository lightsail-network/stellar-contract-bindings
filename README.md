# stellar-contract-bindings

`stellar-contract-bindings` is a CLI tool designed to generate language bindings for Stellar Soroban smart contracts.

This tool simplifies the process of interacting with Soroban contracts by generating the necessary code to call contract
methods directly from your preferred programming language. Currently, it supports
Python, Java, Flutter/Dart, PHP, and Swift/iOS. [stellar-cli](https://github.com/stellar/stellar-cli) provides support for TypeScript and Rust.

## Web Interface
We have a web interface for generating bindings. You can access via [https://stellar-contract-bindings.fly.dev/](https://stellar-contract-bindings.fly.dev/).

## Installation

You can install `stellar-contract-bindings` using pip:

```shell
pip install stellar-contract-bindings
```

## Usage

Please check the help message for the most up-to-date usage information:

```shell
stellar-contract-bindings --help
```

### Examples

#### Python
```shell
stellar-contract-bindings python --contract-id CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF --rpc-url https://mainnet.sorobanrpc.com --output ./bindings
```

#### Java
```shell
stellar-contract-bindings java --contract-id CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF --rpc-url https://mainnet.sorobanrpc.com --output ./bindings --package com.example
```

#### Flutter/Dart
```shell
stellar-contract-bindings flutter --contract-id CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF --rpc-url https://mainnet.sorobanrpc.com --output ./lib --class-name MyContract
```

#### PHP
```shell
stellar-contract-bindings php --contract-id CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF --rpc-url https://mainnet.sorobanrpc.com --output ./generated --namespace MyApp\\Contracts --class-name MyContractClient
```

#### Swift/iOS
```shell
stellar-contract-bindings swift --contract-id CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF --rpc-url https://mainnet.sorobanrpc.com --output ./Sources --class-name MyContract
```

These commands will generate language-specific bindings for the specified contract and save them in the respective directories.

### Using the Generated Binding

After generating the binding, you can use it to interact with your Soroban contract. Here's an example:

#### Python

```python
from stellar_sdk import Network
from bindings import Client  # Import the generated bindings

contract_id = "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF"
rpc_url = "https://mainnet.sorobanrpc.com"
network_passphrase = Network.PUBLIC_NETWORK_PASSPHRASE

client = Client(contract_id, rpc_url, network_passphrase)
assembled_tx = client.hello(b"world")
print(assembled_tx.result())
# assembled_tx.sign_and_submit()
```

#### Java
```java
public class Example extends ContractClient {
    public static void main(String[] args) {
        KeyPair kp = KeyPair.fromAccountId("GD5KKP3LHUDXLDCGKP55NLEOEHMS3Z4BS6IDDZFCYU3BDXUZTBWL7JNF");
        Client client = new Client("CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF", "https://mainnet.sorobanrpc.com", Network.PUBLIC);
        AssembledTransaction<List<byte[]>> tx = client.hello("World".getBytes(), kp.getAccountId(), kp, 100);
    }
}
```

#### Flutter/Dart
```dart
import 'package:stellar_flutter_sdk/stellar_flutter_sdk.dart';
import 'lib/my_contract_client.dart'; // Import the generated bindings

void main() async {
  final sourceKeyPair = KeyPair.fromAccountId("GD5KKP3LHUDXLDCGKP55NLEOEHMS3Z4BS6IDDZFCYU3BDXUZTBWL7JNF");
  // or: final sourceKeyPair = KeyPair.fromSecretSeed("S...");
  
  // Create client instance
  final client = await MyContractClient.forContractId(
    sourceAccountKeyPair: sourceKeyPair,
    contractId: "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF",
    network: Network.PUBLIC,
    rpcUrl: "https://mainnet.sorobanrpc.com",
  );
  
  // Call contract method directly
  try {
    final result = await client.hello(input: "World");
    print("Contract response: $result");
  } catch (e) {
    print("Error calling contract: $e");
  }
  
  // Or build an assembled transaction for more control
  final assembledTx = await client.buildHelloTx(
    input: "World",
    methodOptions: MethodOptions(),
  );
}
```

#### PHP
```php
<?php

use Soneso\StellarSDK\Crypto\KeyPair;
use Soneso\StellarSDK\Network;
use Soneso\StellarSDK\Soroban\Contract\ClientOptions;
use Soneso\StellarSDK\Soroban\Contract\MethodOptions;
use MyApp\Contracts\MyContractClient; // Import the generated bindings

// Initialize
$sourceKeyPair = KeyPair::fromAccountId("GD5KKP3LHUDXLDCGKP55NLEOEHMS3Z4BS6IDDZFCYU3BDXUZTBWL7JNF");
// or: $sourceKeyPair = KeyPair::fromSeed("S...")

// Create client instance
$options = new ClientOptions(
    sourceAccountKeyPair: $sourceKeyPair,
    contractId: "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF",
    network: Network::public(),
    rpcUrl: "https://mainnet.sorobanrpc.com"
);

$client = MyContractClient::forClientOptions($options);

// Call contract method directly
try {
    $result = $client->hello("World");
    echo "Contract response: " . $result . "\n";
} catch (Exception $e) {
    echo "Error calling contract: " . $e->getMessage() . "\n";
}

// Or build an assembled transaction for more control
$methodOptions = new MethodOptions();
$assembledTx = $client->buildHelloTx("World", $methodOptions);
```

#### Swift/iOS
```swift
import stellarsdk
import Foundation

// Import the generated bindings
// Assuming the generated file is named MyContract.swift

// Initialize
let sourceKeyPair = try! KeyPair.init(accountId: "GD5KKP3LHUDXLDCGKP55NLEOEHMS3Z4BS6IDDZFCYU3BDXUZTBWL7JNF")
// or: let sourceKeyPair = try! KeyPair.init(secretSeed: "S...")

// Create client instance
let options = ClientOptions(
    sourceAccountKeyPair: sourceKeyPair,
    contractId: "CDOAW6D7NXAPOCO7TFAWZNJHK62E3IYRGNRVX3VOXNKNVOXCLLPJXQCF",
    network: .public,
    rpcUrl: "https://mainnet.sorobanrpc.com"
)

Task {
    do {
        let client = try await MyContract.forClientOptions(options: options)
        
        // Call contract method directly
        let result = try await client.hello(
            to: "World",
            methodOptions: nil,
            force: false
        )
        print("Contract response: \(result)")
        
        // Or build an assembled transaction for more control
        let methodOptions = MethodOptions()
        let assembledTx = try await client.buildHelloTx(
            to: "World",
            methodOptions: methodOptions
        )
        
    } catch {
        print("Error calling contract: \(error)")
    }
}
```

## License

This project is licensed under the Apache-2.0 License. See the [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! The project is designed to be easy to add support for other languages, please open an issue
or submit a pull request for any improvements or bug fixes.