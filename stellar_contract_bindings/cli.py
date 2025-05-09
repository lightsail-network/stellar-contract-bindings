import click

from stellar_contract_bindings import __version__
from stellar_contract_bindings.python import command as python_command
from stellar_contract_bindings.java import command as java_command


@click.group()
@click.version_option(version=__version__)
def cli():
    """CLI for generating Stellar contract bindings."""


cli.add_command(python_command)
cli.add_command(java_command)


# https://github.com/lightsail-network/stellar-contract-bindings/issues/14
def cli_python():
    """CLI for generating Stellar contract bindings (Python)."""
    python_command()


def cli_java():
    """CLI for generating Stellar contract bindings (Java)."""
    java_command()


if __name__ == "__main__":
    cli()
