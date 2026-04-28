"""Authentication subcommands."""

import click

from scopus_for_dobby.core import auth as auth_mod

from ._output import handle_error, output


@click.group()
def auth():
    """Authentication and API key management."""


@auth.command("setup")
@click.option("--api-key", required=True, help="Elsevier API key from dev.elsevier.com")
@click.option(
    "--inst-token", default=None, help="Institutional token (optional, for COMPLETE view)"
)
@handle_error
def auth_setup(api_key, inst_token):
    """Configure Scopus API credentials."""
    result = auth_mod.setup(api_key, inst_token)
    output(result, f"Configured ({result['tier']} tier).")


@auth.command("upgrade")
@click.option("--inst-token", required=True, help="Institutional token")
@handle_error
def auth_upgrade(inst_token):
    """Add institutional token to upgrade to COMPLETE view."""
    result = auth_mod.set_inst_token(inst_token)
    output(result, result["message"])


@auth.command("downgrade")
@handle_error
def auth_downgrade():
    """Remove institutional token, revert to free tier."""
    result = auth_mod.remove_inst_token()
    output(result, result["message"])


@auth.command("status")
@handle_error
def auth_status():
    """Check API key status and connectivity."""
    result = auth_mod.get_status()
    output(result)


@auth.command("logout")
@handle_error
def auth_logout():
    """Remove all saved credentials."""
    result = auth_mod.logout()
    output(result, "Credentials removed.")


def register(cli_group):
    cli_group.add_command(auth)
