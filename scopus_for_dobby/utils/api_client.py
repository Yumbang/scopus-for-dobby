"""Scopus API client — handles authentication, rate limiting, and HTTP requests.

All Scopus REST API calls go through this module. It reads credentials
from ~/.scopus-for-dobby/config.json and respects Elsevier rate limits.

Base URL: https://api.elsevier.com
"""

import contextlib
import json
import logging
import time
from pathlib import Path

import requests

logger = logging.getLogger(__name__)

CONFIG_DIR = Path.home() / ".scopus-for-dobby"
CONFIG_FILE = CONFIG_DIR / "config.json"

BASE_URL = "https://api.elsevier.com"

# Per-endpoint throttle intervals (seconds between requests)
_THROTTLE = {
    "/content/search/scopus": 0.12,  # 9 req/sec
    "/content/abstract": 0.12,  # 9 req/sec
    "/content/article": 0.11,  # ScienceDirect Article Retrieval: 10 req/sec
    "/content/object": 0.11,  # object (figure) retrieval: same 10 req/sec ceiling
    "/content/author/author_id": 0.35,  # 3 req/sec
    "/content/search/author": 0.55,  # 2 req/sec
    "/content/abstract/citations": 0.12,  # ~9 req/sec
}

_last_call: dict[str, float] = {}


class QuotaExceeded(RuntimeError):
    """Weekly API quota exhausted (HTTP 429 with QUOTA_EXCEEDED)."""

    def __init__(self, message: str, reset: str | None = None):
        super().__init__(message)
        self.reset = reset


# ── Config I/O ────────────────────────────────────────────────────────────────


def _ensure_config_dir():
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)


def load_config() -> dict:
    """Load saved configuration (API key, insttoken, tier)."""
    if CONFIG_FILE.exists():
        return json.loads(CONFIG_FILE.read_text())
    return {}


def save_config(config: dict):
    """Persist configuration to disk."""
    _ensure_config_dir()
    CONFIG_FILE.write_text(json.dumps(config, indent=2))
    CONFIG_FILE.chmod(0o600)


def _quota_bucket(endpoint: str) -> str:
    """Name the Elsevier quota this endpoint draws from.

    Quotas are per API, not per key. Mixing Article Retrieval remaining into
    the Scopus Abstract figure would tell an agent the wrong budget.
    """
    if "/content/article" in endpoint and "/content/abstract" not in endpoint:
        return "sciencedirect-article"
    if "/content/abstract" in endpoint:
        return "scopus-abstract"
    if "/content/search/scopus" in endpoint:
        return "scopus-search"
    return "scopus"


def _cache_quota(remaining: int, reset: str | None, *, bucket: str = "scopus"):
    """Cache the latest rate-limit headers to config so other commands can
    report quota without making an API call. Best-effort: failures are ignored.
    """
    try:
        config = load_config()
        entry = {
            "remaining": remaining,
            "reset": reset,
            "updated_at": int(time.time()),
            "api": bucket,
        }
        # Last call overall — what `auth quota` has always shown.
        config["last_quota"] = entry
        buckets = config.get("last_quotas") or {}
        buckets[bucket] = entry
        config["last_quotas"] = buckets
        save_config(config)
    except OSError as e:
        logger.debug("Failed to cache quota: %s", e)


def get_cached_quota() -> dict | None:
    """Return the last cached rate-limit info, or None if never recorded.

    Reads only from local config — makes no API call.
    """
    return load_config().get("last_quota")


# ── Rate limiter ──────────────────────────────────────────────────────────────


def _throttle(endpoint: str):
    """Sleep if needed to respect per-endpoint rate limits."""
    for prefix, interval in _THROTTLE.items():
        if prefix in endpoint:
            last = _last_call.get(prefix, 0)
            elapsed = time.time() - last
            if elapsed < interval:
                time.sleep(interval - elapsed)
            _last_call[prefix] = time.time()
            return


# ── Core request ──────────────────────────────────────────────────────────────


def _build_headers(config: dict, accept: str = "application/json") -> dict:
    """Build auth headers from config."""
    api_key = config.get("api_key", "")
    if not api_key:
        raise RuntimeError(
            "API key not configured. Run: scopus-for-dobby auth setup --api-key YOUR_KEY"
        )

    headers = {
        "X-ELS-APIKey": api_key,
        "Accept": accept,
    }

    inst_token = config.get("inst_token", "")
    if inst_token:
        headers["X-ELS-Insttoken"] = inst_token

    return headers


def api_get(endpoint: str, params: dict | None = None, config: dict | None = None) -> dict:
    """Make a GET request to the Scopus API.

    Args:
        endpoint: API path (e.g., '/content/search/scopus').
        params: Query parameters.
        config: Override config (uses saved config if None).

    Returns:
        Parsed JSON response.

    Raises:
        RuntimeError: On HTTP errors with descriptive messages.
    """
    if config is None:
        config = load_config()

    headers = _build_headers(config)
    _throttle(endpoint)

    url = f"{BASE_URL}{endpoint}"
    resp = requests.get(url, headers=headers, params=params, timeout=30)

    # Rate limit info
    remaining = resp.headers.get("X-RateLimit-Remaining")
    reset = resp.headers.get("X-RateLimit-Reset")

    if resp.status_code == 429:
        reset_msg = ""
        if reset:
            try:
                reset_time = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(reset)))
                reset_msg = f" Quota resets at {reset_time}."
            except (ValueError, OSError):
                pass
        raise RuntimeError(f"Rate limit exceeded.{reset_msg}")

    if resp.status_code == 401:
        raise RuntimeError("Authentication failed (HTTP 401). Check your API key.")

    if resp.status_code == 403:
        raise RuntimeError(
            "Authorization error (HTTP 403). This endpoint may require "
            "an institutional token. Run: scopus-for-dobby auth setup --inst-token TOKEN"
        )

    if resp.status_code != 200:
        # Log the raw body for diagnostics only — never surface it to callers,
        # since upstream response bodies may carry sensitive or noisy content.
        logger.debug(
            "Scopus API error: HTTP %s on %s — body: %s",
            resp.status_code,
            endpoint,
            resp.text[:200],
        )
        raise RuntimeError(
            f"API error: HTTP {resp.status_code} on {endpoint} ({resp.reason or 'request failed'})."
        )

    result = resp.json()

    # Attach rate limit metadata
    if remaining is not None:
        result["_rate_limit"] = {
            "remaining": int(remaining),
            "reset": reset,
        }
        _cache_quota(int(remaining), reset, bucket=_quota_bucket(endpoint))

    return result


def api_get_raw(
    endpoint: str,
    params: dict | None = None,
    config: dict | None = None,
    *,
    accept: str = "application/json",
    timeout: int = 30,
) -> requests.Response:
    """Make a GET request and return the raw response (for header inspection)."""
    if config is None:
        config = load_config()

    headers = _build_headers(config, accept=accept)
    _throttle(endpoint)

    url = f"{BASE_URL}{endpoint}"
    return requests.get(url, headers=headers, params=params, timeout=timeout)


def request_elsevier(
    endpoint: str,
    params: dict | None = None,
    *,
    accept: str = "text/xml",
    timeout: int = 60,
    config: dict | None = None,
) -> dict:
    """GET an Elsevier endpoint and return status+body without raising on 4xx.

    401/403/404 are per-document outcomes for Article Retrieval (not entitled,
    not an Elsevier paper). 429 still raises: the rest of a batch cannot
    usefully continue.

    Returns ``{"status": int, "text": str, "remaining": int|None, "reset": str|None}``.
    """
    resp = api_get_raw(endpoint, params=params, config=config, accept=accept, timeout=timeout)
    remaining = resp.headers.get("X-RateLimit-Remaining")
    reset = resp.headers.get("X-RateLimit-Reset")
    if remaining is not None:
        with contextlib.suppress(ValueError, TypeError):
            _cache_quota(int(remaining), reset, bucket=_quota_bucket(endpoint))

    if resp.status_code == 429:
        reset_msg = ""
        if reset:
            try:
                reset_time = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(int(reset)))
                reset_msg = f" Quota resets at {reset_time}."
            except (ValueError, OSError):
                pass
        raise QuotaExceeded(f"Rate limit exceeded.{reset_msg}", reset=reset)

    return {
        "status": resp.status_code,
        "text": resp.text or "",
        "remaining": int(remaining) if remaining is not None else None,
        "reset": reset,
    }
