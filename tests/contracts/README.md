# The reference contract

`contracts/python` is a Soroban contract that declares every spec type: the
scalars, structs, tuple structs, enums, error enums, unions, options, vectors,
maps and tuples, plus names that are keywords in the target languages. The
generators are tested against its spec, and the generated bindings are tested
by calling it.

Its build is checked in as `tests/fixtures/python.wasm`, so the tests need no
Rust toolchain. The tests that call the contract deploy that wasm to testnet
themselves, from a throwaway account funded by friendbot, once per test
session (see `tests/reference_contract.py`); nothing about the deployment is
stored, so a testnet reset needs no attention. Set
`STELLAR_BINDINGS_OFFLINE=1` to skip those tests.

After changing the contract, rebuild the fixture:

```shell
cd tests/contracts
stellar contract build
cp target/wasm32v1-none/release/python.wasm ../fixtures/python.wasm
```

and regenerate `tests/client.py`, the Python bindings the Python tests call
the contract through.

To deploy the contract by hand, for instance to try the bindings against it:

```shell
uv run python -m tests.reference_contract
```
