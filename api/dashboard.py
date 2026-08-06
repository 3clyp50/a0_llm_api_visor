from __future__ import annotations

from datetime import datetime, timezone
import json
import re
import time
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request as UrlRequest, urlopen

from helpers.api import ApiHandler, Request, Response
from helpers import plugins

from usr.plugins.a0_llm_api_visor.helpers import usage_tracker
from usr.plugins.a0_llm_api_visor.helpers.eip55 import to_checksum_address


PLUGIN_NAME = "a0_llm_api_visor"
PLUGIN_TITLE = "LLM API Visor"
ALLOWED_API_HOSTS = {"api.agent-zero.ai", "tapi.agent-zero.ai"}
WALLET_ADDRESS_RE = re.compile(r"^0x[a-fA-F0-9]{40}$")

DEFAULT_CONFIG = {
    "api_base_url": "https://api.agent-zero.ai",
    "dashboard_url": "https://www.agent-zero.ai/p/community/api-dashboard/",
    "wallet_address": "",
    "show_wallet_metrics": True,
    "refresh_interval_seconds": 300,
    "cache_seconds": 45,
    # Personalization
    "accent_color": "#66b8ff",
    "background_style": "default",
    "custom_background_color": "",
    "show_progress_bar": True,
    "show_multiplier": True,
    "show_usage_row": True,
    "show_detail_line": True,
    "show_wallet_line": True,
    # Usage insights (opt-in local stats tracking)
    "usage_insights_enabled": False,
}

PERSONALIZATION_KEYS = (
    "accent_color",
    "background_style",
    "custom_background_color",
    "show_progress_bar",
    "show_multiplier",
    "show_usage_row",
    "show_detail_line",
    "show_wallet_line",
)

HEX_COLOR_RE = re.compile(r"^#[0-9a-fA-F]{6}$")
BACKGROUND_STYLES = {"default", "flat", "custom"}

_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


class Dashboard(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        config = _load_config()

        try:
            api_base_url = _normalize_api_base_url(str(config["api_base_url"]))
        except ValueError as exc:
            return _error_response(str(exc), config)

        explicit_wallet = input.get("wallet_address")
        wallet_source = explicit_wallet if explicit_wallet is not None else config.get("wallet_address", "")
        wallet_address = _normalize_wallet_address(str(wallet_source or ""))
        if wallet_source and not wallet_address:
            return _error_response("Wallet address must be a 0x address with 40 hexadecimal characters.", config)

        show_wallet_metrics = bool(config.get("show_wallet_metrics", True))
        cache_seconds = _int_in_range(config.get("cache_seconds"), minimum=0, maximum=300, default=45)
        cache_key = json.dumps(
            {
                "api_base_url": api_base_url,
                "wallet_address": wallet_address if show_wallet_metrics and wallet_address else "",
                "show_wallet_metrics": show_wallet_metrics,
                "usage_insights_enabled": bool(config.get("usage_insights_enabled", False)),
                **_personalization(config),
            },
            sort_keys=True,
        )

        if not input.get("force") and cache_seconds > 0:
            cached = _CACHE.get(cache_key)
            if cached and time.monotonic() - cached[0] < cache_seconds:
                response = dict(cached[1])
                response["cached"] = True
                return response

        try:
            public_dashboard = _post_json(api_base_url, "get-api-dashboard-public", {})
            user_dashboard = None
            public_wallet = None
            wallet_error = ""

            if show_wallet_metrics and wallet_address:
                try:
                    user_dashboard = _post_json(
                        api_base_url,
                        "get-api-dashboard-info",
                        {"address": wallet_address},
                    )
                    public_wallet = _post_json(
                        api_base_url,
                        "get-public-wallet-info",
                        {"address": wallet_address},
                    )
                except Exception as exc:
                    wallet_error = str(exc)

            if user_dashboard and bool(config.get("usage_insights_enabled", False)):
                try:
                    usage_tracker.record_snapshot(user_dashboard)
                except Exception:
                    pass  # tracking must never break the dashboard

            response = {
                "ok": True,
                "title": PLUGIN_TITLE,
                "as_of": _utc_now(),
                "cached": False,
                "config": {
                    "dashboard_url": str(config.get("dashboard_url") or DEFAULT_CONFIG["dashboard_url"]),
                    "refresh_interval_seconds": _int_in_range(
                        config.get("refresh_interval_seconds"),
                        minimum=30,
                        maximum=3600,
                        default=300,
                    ),
                    "show_wallet_metrics": show_wallet_metrics,
                    "api_host": urlparse(api_base_url).hostname or "",
                    "usage_insights_enabled": bool(config.get("usage_insights_enabled", False)),
                    **_personalization(config),
                },
                "summary": _build_summary(
                    public_dashboard=public_dashboard,
                    user_dashboard=user_dashboard,
                    public_wallet=public_wallet,
                    wallet_address=wallet_address if show_wallet_metrics else "",
                    wallet_requested=show_wallet_metrics,
                    wallet_error=wallet_error,
                ),
                "public_dashboard": public_dashboard,
                "user_dashboard": user_dashboard,
                "public_wallet": public_wallet,
                "wallet_error": wallet_error,
            }
            _CACHE[cache_key] = (time.monotonic(), response)
            return response
        except Exception as exc:
            return _error_response(str(exc), config)


def _load_config() -> dict[str, Any]:
    settings = plugins.get_plugin_config(PLUGIN_NAME, agent=None) or {}
    config = {**DEFAULT_CONFIG, **settings}
    config["refresh_interval_seconds"] = _int_in_range(
        config.get("refresh_interval_seconds"),
        minimum=30,
        maximum=3600,
        default=300,
    )
    config["cache_seconds"] = _int_in_range(
        config.get("cache_seconds"),
        minimum=0,
        maximum=300,
        default=45,
    )
    return config


def _personalization(config: dict[str, Any]) -> dict[str, Any]:
    accent = str(config.get("accent_color") or "").strip()
    if not HEX_COLOR_RE.match(accent):
        accent = str(DEFAULT_CONFIG["accent_color"])

    style = str(config.get("background_style") or "default").strip().lower()
    if style not in BACKGROUND_STYLES:
        style = "default"

    custom_bg = str(config.get("custom_background_color") or "").strip()
    if not HEX_COLOR_RE.match(custom_bg):
        custom_bg = ""
    if style == "custom" and not custom_bg:
        style = "default"

    return {
        "accent_color": accent,
        "background_style": style,
        "custom_background_color": custom_bg,
        "show_progress_bar": bool(config.get("show_progress_bar", True)),
        "show_multiplier": bool(config.get("show_multiplier", True)),
        "show_usage_row": bool(config.get("show_usage_row", True)),
        "show_detail_line": bool(config.get("show_detail_line", True)),
        "show_wallet_line": bool(config.get("show_wallet_line", True)),
    }


def _normalize_api_base_url(value: str) -> str:
    parsed = urlparse(value.strip().rstrip("/"))
    if parsed.scheme != "https":
        raise ValueError("API base URL must use https.")
    if not parsed.hostname or parsed.hostname not in ALLOWED_API_HOSTS:
        raise ValueError("API base URL must be api.agent-zero.ai or tapi.agent-zero.ai.")
    if parsed.path and parsed.path != "/":
        raise ValueError("API base URL must point to the API root.")
    netloc = parsed.hostname
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    return f"https://{netloc}"


def _normalize_wallet_address(value: str) -> str:
    """Validate and EIP-55 checksum a wallet address.

    The upstream API keys stake and quota records by the exact checksummed
    string, so a lowercase address returns HTTP 200 with all-zero values
    instead of an error. Normalising here makes input casing irrelevant.
    """
    candidate = value.strip()
    if not candidate:
        return ""
    if candidate[:2].lower() == "0x":
        candidate = "0x" + candidate[2:]
    if not WALLET_ADDRESS_RE.match(candidate):
        return ""
    return to_checksum_address(candidate) or candidate


def _post_json(api_base_url: str, endpoint: str, payload: dict[str, Any]) -> dict[str, Any]:
    url = urljoin(f"{api_base_url.rstrip('/')}/", endpoint.lstrip("/"))
    body = json.dumps(payload).encode("utf-8")
    request = UrlRequest(
        url,
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json",
            "User-Agent": "Agent-Zero-LLM-API-Visor/0.2.0",
        },
    )

    try:
        with urlopen(request, timeout=10) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            data = response.read(1024 * 1024).decode(charset)
    except HTTPError as exc:
        detail = exc.read(4096).decode("utf-8", errors="replace")
        raise RuntimeError(f"{endpoint} returned HTTP {exc.code}: {detail}") from exc
    except URLError as exc:
        raise RuntimeError(f"{endpoint} could not be reached: {exc.reason}") from exc

    parsed = json.loads(data)
    if not isinstance(parsed, dict):
        raise RuntimeError(f"{endpoint} returned an unexpected response.")
    if parsed.get("error"):
        raise RuntimeError(str(parsed["error"]))
    return parsed


def _build_summary(
    *,
    public_dashboard: dict[str, Any],
    user_dashboard: dict[str, Any] | None,
    public_wallet: dict[str, Any] | None,
    wallet_address: str,
    wallet_requested: bool,
    wallet_error: str,
) -> dict[str, Any]:
    public_quota = _dict(public_dashboard.get("quota"))
    public_usage = _dict(public_dashboard.get("usage"))
    user_quota = _dict(user_dashboard.get("quota") if user_dashboard else None)
    user_usage = _dict(_dict(user_dashboard.get("usage") if user_dashboard else None).get("user_usage"))
    global_usage = _dict(
        _dict(user_dashboard.get("usage") if user_dashboard else None).get("global_usage")
    ) or public_usage
    wallet = _dict(public_wallet)
    wallet_data = _dict(wallet.get("walletData"))
    usage_by_model = user_dashboard.get("usageByModel") if user_dashboard else []
    usage_by_model = usage_by_model if isinstance(usage_by_model, list) else []

    has_wallet_quota = bool(user_dashboard and user_quota)
    wallet_unavailable = bool(wallet_address and wallet_error and not has_wallet_quota)
    needs_wallet = bool(wallet_requested and not wallet_address)
    mode = "wallet"
    if not wallet_requested:
        mode = "global"
    elif needs_wallet:
        mode = "needs_wallet"
    elif wallet_unavailable:
        mode = "wallet_unavailable"
    elif not has_wallet_quota:
        mode = "wallet_unavailable"

    user_base_quota = _number(user_quota.get("userBaseQuota"))
    user_current_quota = _number(user_quota.get("userCurrentQuota"))
    user_remaining_quota = _number(user_quota.get("userRemainingQuota"))
    user_used_quota = _number(user_quota.get("userUsedQuota"))
    global_remaining_quota = _number(public_quota.get("globalRemainingQuota"))
    global_base_quota = _number(public_quota.get("globalBaseQuota"))
    global_used_quota = _number(public_quota.get("globalUsedQuota"))

    if mode == "wallet":
        remaining_quota = user_remaining_quota
        base_quota = user_current_quota
        used_quota = user_used_quota
    elif mode == "global":
        remaining_quota = global_remaining_quota
        base_quota = global_base_quota
        used_quota = global_used_quota
    else:
        remaining_quota = 0.0
        base_quota = 0.0
        used_quota = 0.0

    return {
        "mode": mode,
        "wallet_address": wallet_address,
        "wallet_label": wallet_data.get("nickname") or _short_wallet(wallet_address),
        "wallet_error": wallet_error,
        "wallet_required": needs_wallet,
        "real_multiplier": _number(public_quota.get("realMultiplier")),
        "remaining_quota": remaining_quota,
        "base_quota": base_quota,
        "used_quota": used_quota,
        "quota_percent": _percent(remaining_quota, base_quota),
        "epoch_phase": _number(public_quota.get("epochPhase")),
        "user_base_quota": user_base_quota,
        "user_current_quota": user_current_quota,
        "user_remaining_quota": user_remaining_quota,
        "user_used_quota": user_used_quota,
        "user_quota_percent": _percent(user_remaining_quota, user_current_quota),
        "global_remaining_quota": global_remaining_quota,
        "global_base_quota": global_base_quota,
        "global_used_quota": global_used_quota,
        "global_quota_percent": _percent(
            global_remaining_quota,
            global_base_quota,
        ),
        "global_stake": _number(public_dashboard.get("globalStake")),
        "global_requests": _number(global_usage.get("requests")),
        "global_tokens_input": _number(global_usage.get("tokens_input")),
        "global_tokens_output": _number(global_usage.get("tokens_output")),
        "user_requests": _number(user_usage.get("requests")),
        "user_tokens_input": _number(user_usage.get("tokens_input")),
        "user_tokens_output": _number(user_usage.get("tokens_output")),
        "balance_a0t": _number(wallet.get("balanceA0T")),
        "balance_eth": _number(wallet.get("balanceEth")),
        "stake_score": _number(wallet.get("stakeScore")),
        "total_stake": _number(wallet.get("stakeSum")),
        "api_stake_sum": _number(user_dashboard.get("apiStakeSum") if user_dashboard else 0),
        "top_model": usage_by_model[0] if usage_by_model else None,
    }


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _percent(value: float, total: float) -> float:
    if total <= 0:
        return 0.0
    return max(0.0, min(100.0, (value / total) * 100.0))


def _int_in_range(value: Any, *, minimum: int, maximum: int, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(minimum, min(maximum, parsed))


def _short_wallet(address: str) -> str:
    if not address:
        return ""
    return f"{address[:6]}...{address[-4:]}"


def _utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _error_response(message: str, config: dict[str, Any]) -> dict[str, Any]:
    return {
        "ok": False,
        "title": PLUGIN_TITLE,
        "as_of": _utc_now(),
        "cached": False,
        "error": message,
        "config": {
            "dashboard_url": str(config.get("dashboard_url") or DEFAULT_CONFIG["dashboard_url"]),
            "refresh_interval_seconds": _int_in_range(
                config.get("refresh_interval_seconds"),
                minimum=30,
                maximum=3600,
                default=300,
            ),
            "show_wallet_metrics": False,
            "api_host": "",
        },
        "summary": {},
    }
