"""Authentication subcommands."""

import contextlib
import time

import click

from scopus_for_dobby.core import auth as auth_mod
from scopus_for_dobby.utils.api_client import get_cached_quota

from ._output import handle_error, output


def _fmt_epoch(value) -> str | None:
    """Format an epoch-seconds value as a UTC string, or None if unparseable."""
    with contextlib.suppress(ValueError, OSError, TypeError):
        return time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(value)))
    return None


def _format_quota(quota: dict | None) -> dict:
    """Render cached rate-limit info into a display-friendly dict.

    Reads only what was cached on the last API call — makes no request.
    """
    if not quota:
        return {"cached_quota": "none recorded yet (run a search first)"}

    info: dict = {"remaining": quota.get("remaining")}

    resets_at = _fmt_epoch(quota.get("reset"))
    if resets_at:
        info["resets_at"] = resets_at

    as_of = _fmt_epoch(quota.get("updated_at"))
    if as_of:
        info["as_of"] = as_of

    info["note"] = "reflects the last API call, not a live value"
    return info


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
    # Surface the cached quota too — read from local state, no extra API call.
    result["cached_quota"] = _format_quota(get_cached_quota())
    output(result)


@auth.command("quota")
@handle_error
def auth_quota():
    """Show cached API quota (remaining calls, reset time) from the last call.

    Reads only from local state — makes no API request.
    """
    output(_format_quota(get_cached_quota()))


@auth.command("logout")
@handle_error
def auth_logout():
    """Remove all saved credentials."""
    result = auth_mod.logout()
    output(result, "Credentials removed.")


def register(cli_group):
    cli_group.add_command(auth)
