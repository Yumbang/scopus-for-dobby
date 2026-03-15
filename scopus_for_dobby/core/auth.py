"""Authentication management for Scopus API.

Scopus uses API key authentication (not OAuth). Two tiers:
- Free: API key only (STANDARD view)
- Institutional: API key + Institutional Token (COMPLETE view)

Credentials are stored in ~/.scopus-for-dobby/config.json (chmod 600),
never inside the project directory.
"""

import re

from scopus_for_dobby.utils.api_client import (
    CONFIG_DIR,
    api_get,
    load_config,
    save_config,
)

# Elsevier API keys are 32-character hex strings
_API_KEY_PATTERN = re.compile(r"^[0-9a-fA-F]{32}$")


def _validate_api_key(api_key: str) -> str:
    """Validate and normalize an Elsevier API key.

    Elsevier API keys are 32-character hexadecimal strings.

    Raises:
        ValueError: If the key format is invalid.
    """
    key = api_key.strip()
    if not key:
        raise ValueError("API key cannot be empty.")
    if not _API_KEY_PATTERN.match(key):
        raise ValueError(
            f"Invalid API key format. Elsevier API keys are 32 hex characters "
            f"(got {len(key)} chars). Get yours at https://dev.elsevier.com"
        )
    return key


def _validate_inst_token(token: str) -> str:
    """Validate an institutional token (non-empty, no whitespace-only)."""
    t = token.strip()
    if not t:
        raise ValueError("Institutional token cannot be empty.")
    return t


def setup(api_key: str, inst_token: str | None = None) -> dict:
    """Save API credentials.

    Args:
        api_key: Elsevier API key from dev.elsevier.com (32 hex chars).
        inst_token: Optional institutional token for COMPLETE view access.

    Returns:
        Configuration status dict.

    Raises:
        ValueError: If API key format is invalid.
    """
    validated_key = _validate_api_key(api_key)

    config = load_config()
    config["api_key"] = validated_key
    if inst_token:
        config["inst_token"] = _validate_inst_token(inst_token)
        config["tier"] = "institutional"
    else:
        config.pop("inst_token", None)
        config["tier"] = "free"

    save_config(config)

    return {
        "status": "configured",
        "tier": config["tier"],
        "config_path": str(CONFIG_DIR / "config.json"),
    }


def set_inst_token(inst_token: str) -> dict:
    """Add or update institutional token to existing config.

    Returns:
        Updated configuration status.
    """
    config = load_config()
    if not config.get("api_key"):
        raise RuntimeError(
            "API key not configured yet. Run: auth setup --api-key YOUR_KEY"
        )
    config["inst_token"] = _validate_inst_token(inst_token)
    config["tier"] = "institutional"
    save_config(config)
    return {
        "status": "upgraded",
        "tier": "institutional",
        "message": "Institutional token saved. COMPLETE view now available.",
    }


def remove_inst_token() -> dict:
    """Remove institutional token, downgrade to free tier.

    Returns:
        Updated configuration status.
    """
    config = load_config()
    config.pop("inst_token", None)
    config["tier"] = "free"
    save_config(config)
    return {
        "status": "downgraded",
        "tier": "free",
        "message": "Institutional token removed. Using STANDARD view.",
    }


def get_status() -> dict:
    """Check current authentication status by making a test API call.

    Returns:
        Dict with auth status, tier, and API connectivity.
    """
    config = load_config()
    result = {
        "configured": bool(config.get("api_key")),
        "tier": config.get("tier", "none"),
        "has_inst_token": bool(config.get("inst_token")),
    }

    if not config.get("api_key"):
        result["message"] = "Not configured. Run: auth setup --api-key YOUR_KEY"
        return result

    # Test API connectivity with a minimal search
    try:
        resp = api_get(
            "/content/search/scopus",
            params={"query": "TITLE(test)", "count": "1", "view": "STANDARD"},
            config=config,
        )
        total = resp.get("search-results", {}).get("opensearch:totalResults", "0")
        result["api_connected"] = True
        result["message"] = f"API key valid. Scopus has {total} results for test query."

        rate = resp.get("_rate_limit", {})
        if rate:
            result["rate_limit_remaining"] = rate.get("remaining")

    except RuntimeError as e:
        result["api_connected"] = False
        result["error"] = str(e)

    return result


def logout() -> dict:
    """Remove all saved credentials.

    Returns:
        Confirmation dict.
    """
    config_file = CONFIG_DIR / "config.json"
    if config_file.exists():
        config_file.unlink()
    return {"status": "logged_out", "message": "Credentials removed."}
