from __future__ import annotations

from datetime import datetime, timezone
import json
import re
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import HTTPRedirectHandler, Request as UrlRequest, build_opener

from helpers.api import ApiHandler, Request, Response
from helpers import plugins
import models
from usr.plugins.a0_llm_api_visor.helpers import usage_tracker

PLUGIN_NAME = "a0_llm_api_visor"
PLUGIN_TITLE = "LLM API Visor"
PLUGIN_VERSION = "0.3.2"
ALLOWED_API_HOSTS = {"api.agent-zero.ai", "tapi.agent-zero.ai"}

DEFAULT_CONFIG = {
    "api_base_url": "https://api.agent-zero.ai",
    "dashboard_url": "https://www.agent-zero.ai/p/community/api-dashboard/",
    "show_wallet_metrics": True,
    "refresh_interval_seconds": 300,
    # Personalization
    "sidebar_position": "top",
    "accent_color": "#66b8ff",
    "background_style": "default",
    "custom_background_color": "",
    "show_progress_bar": True,
    "show_multiplier": True,
    "show_usage_row": True,
    "show_detail_line": True,
    "show_wallet_line": True,
    # Local usage insights viewer
    "usage_insights_enabled": False,
}

PERSONALIZATION_KEYS = (
    "sidebar_position",
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


class Dashboard(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        config = _load_config()

        try:
            api_base_url = _normalize_api_base_url(str(config["api_base_url"]))
        except ValueError as exc:
            return _error_response(str(exc), config)

        show_wallet_metrics = bool(config.get("show_wallet_metrics", True))
        track_usage = bool(config.get("usage_insights_enabled", False))
        api_key = (models.get_api_key("a0_venice") or "").strip() if show_wallet_metrics or track_usage else ""
        if api_key == "None":
            api_key = ""
        try:
            public_dashboard = _request_json(api_base_url, "get-api-dashboard-public", {})
            key_status = None
            key_error = ""
            if api_key:
                try:
                    key_status = _request_json(api_base_url, "v1/api-key/status", api_key=api_key)
                except Exception as exc:
                    key_error = str(exc)

            tracking_error = ""
            if key_status and track_usage:
                try:
                    usage_tracker.record_key_snapshot(key_status)
                except OSError:
                    tracking_error = "Could not save local credit history."

            response = {
                "ok": True,
                "title": PLUGIN_TITLE,
                "as_of": _utc_now(),
                "cached": False,
                "tracking_error": tracking_error,
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
                    key_status=key_status,
                    key_requested=show_wallet_metrics,
                    key_configured=bool(api_key),
                    key_error=key_error,
                ),
            }
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
        "sidebar_position": (
            "bottom" if str(config.get("sidebar_position") or "").strip().lower() == "bottom" else "top"
        ),
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
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.port not in (None, 443):
        raise ValueError("API base URL must be an official HTTPS API root.")
    return f"https://{parsed.hostname}"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        # A redirect must never forward the saved API key to another URL.
        return None


def _request_json(api_base_url: str, endpoint: str, payload: dict[str, Any] | None = None, *, api_key: str = "") -> dict[str, Any]:
    url = urljoin(f"{api_base_url.rstrip('/')}/", endpoint.lstrip("/"))
    headers = {"Accept": "application/json", "User-Agent": f"Agent-Zero-LLM-API-Visor/{PLUGIN_VERSION}"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    request = UrlRequest(url, data=json.dumps(payload).encode("utf-8") if payload is not None else None, headers=headers)
    try:
        with build_opener(_NoRedirect).open(request, timeout=10) as response:
            data = response.read(1024 * 1024).decode("utf-8")
    except HTTPError as exc:
        raise RuntimeError(f"{endpoint} returned HTTP {exc.code}.") from exc
    except URLError as exc:
        raise RuntimeError(f"{endpoint} could not be reached.") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"{endpoint} request failed.") from exc
    parsed = json.loads(data)
    if not isinstance(parsed, dict) or parsed.get("error"):
        raise RuntimeError(f"{endpoint} returned an unexpected response.")
    return parsed


def _build_summary(
    *,
    public_dashboard: dict[str, Any],
    key_status: dict[str, Any] | None,
    key_requested: bool,
    key_configured: bool,
    key_error: str,
) -> dict[str, Any]:
    public_quota = _dict(public_dashboard.get("quota"))
    public_usage = _dict(public_dashboard.get("usage"))
    status = key_status or {}
    mode = "key" if key_status else "key_unavailable" if key_configured else "needs_key"
    if not key_requested:
        mode = "global"
    spent = _number(status.get("spent"))
    remaining = _number(status.get("effectiveRemaining"))
    global_remaining = _number(public_quota.get("globalRemainingQuota"))
    global_base = _number(public_quota.get("globalBaseQuota"))
    return {
        "mode": mode,
        "key_status": status.get("status", ""),
        "key_error": key_error,
        "reset_at": status.get("resetAt", ""),
        "real_multiplier": _number(public_quota.get("realMultiplier")),
        "remaining_quota": global_remaining if mode == "global" else remaining,
        "base_quota": global_base if mode == "global" else spent + remaining,
        "quota_percent": _percent(global_remaining, global_base) if mode == "global" else _percent(remaining, spent + remaining),
        "epoch_phase": _number(public_quota.get("epochPhase")),
        "user_remaining_quota": remaining,
        "user_used_quota": spent,
        "global_remaining_quota": global_remaining,
        "global_base_quota": global_base,
        "global_stake_score": _number(public_dashboard.get("globalStake")),
        "global_requests": _number(public_usage.get("requests")),
        "global_tokens_input": _number(public_usage.get("tokens_input")),
        "global_tokens_output": _number(public_usage.get("tokens_output")),
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
