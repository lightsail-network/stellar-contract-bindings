import os

import click
from stellar_sdk import StrKey

from stellar_contract_bindings.python import generate_binding
from stellar_contract_bindings.utils import (
    get_wasm_hash_by_contract_id,
    get_contract_wasm_by_hash,
)


@click.group()
@click.version_option()
def cli():
    """CLI for generating Stellar contract bindings."""


@cli.command(name="generate")
@click.option(
    "--contract-id", required=True, help="The contract ID to generate bindings for"
)
@click.option(
    "--language",
    default="python",
    type=click.Choice(["python"]),
    help="Target language for bindings (default: python)",
)
@click.option(
    "--rpc-url", default="https://mainnet.sorobanrpc.com", help="Soroban RPC URL"
)
@click.option(
    "--output",
    default=None,
    help="Output directory for generated bindings, defaults to current directory",
)
def generate(contract_id: str, language: str, rpc_url: str, output: str):
    """Generate contract bindings from a deployed Soroban contract."""
    if not StrKey.is_valid_contract(contract_id):
        click.echo(f"Invalid contract ID: {contract_id}", err=True)
        raise click.Abort()

    # Use current directory if output is not specified
    if output is None:
        output = os.getcwd()
    try:
        wasm_id = get_wasm_hash_by_contract_id(contract_id, rpc_url)
        click.echo(f"Got wasm id: {wasm_id.hex()}")
        wasm_code = get_contract_wasm_by_hash(wasm_id, rpc_url)
        click.echo(f"Got wasm code")
    except Exception as e:
        click.echo(f"Error: {str(e)}", err=True)
        raise click.Abort()
    if language == "python":
        click.echo("Generating Python bindings")
        generated = generate_binding(wasm_code)
        if not os.path.exists(output):
            os.makedirs(output)
        output_path = os.path.join(output, "bindings.py")
        with open(output_path, "w") as f:
            f.write(generated)
        click.echo(f"Generated Python bindings to {output_path}")
        click.echo(
            f"We recommend running `black {output_path}` to format the generated code."
        )
    else:
        click.echo(f"Unsupported language: {language}", err=True)
        raise click.Abort()
