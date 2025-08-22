import click

from stellar_contract_bindings import __version__
from stellar_contract_bindings.python import command as python_command
from stellar_contract_bindings.java import command as java_command
from stellar_contract_bindings.flutter import command as flutter_command
from stellar_contract_bindings.php import command as php_command
from stellar_contract_bindings.swift import command as swift_command


@click.group()
@click.version_option(version=__version__)
def cli():
    """CLI for generating Stellar contract bindings."""


cli.add_command(python_command)
cli.add_command(java_command)
cli.add_command(flutter_command)
cli.add_command(php_command)
cli.add_command(swift_command)


# https://github.com/lightsail-network/stellar-contract-bindings/issues/14
def cli_python():
    """CLI for generating Stellar contract bindings (Python)."""
    python_command()


def cli_java():
    """CLI for generating Stellar contract bindings (Java)."""
    java_command()


def cli_flutter():
    """CLI for generating Stellar contract bindings (Flutter)."""
    flutter_command()


def cli_php():
    """CLI for generating Stellar contract bindings (PHP)."""
    php_command()


def cli_swift():
    """CLI for generating Stellar contract bindings (Swift)."""
    swift_command()


if __name__ == "__main__":
    cli()
