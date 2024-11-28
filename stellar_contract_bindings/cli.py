import click

from stellar_contract_bindings import __version__
from stellar_contract_bindings.python import command as python_command


@click.group()
@click.version_option(version=__version__)
def cli():
    """CLI for generating Stellar contract bindings."""


cli.add_command(python_command)
