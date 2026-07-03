"""Usage insights endpoint for the LLM API Visor plugin.

Returns locally tracked usage history (opt-in) aggregated for the
insights UI, and supports clearing the stored history.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from helpers.api import ApiHandler, Request, Response
from helpers import plugins

from usr.plugins.a0_llm_api_visor.helpers import usage_tracker

PLUGIN_NAME = "a0_llm_api_visor"


class Insights(ApiHandler):
    async def process(self, input: dict, request: Request) -> dict | Response:
        config = plugins.get_plugin_config(PLUGIN_NAME, agent=None) or {}
        tracking_enabled = bool(config.get("usage_insights_enabled", False))

        action = str(input.get("action") or "get").lower()
        if action == "clear":
            usage_tracker.clear_history()
            return {"ok": True, "cleared": True, "tracking_enabled": tracking_enabled}

        history = usage_tracker.load_history()
        days = history.get("days") or {}

        day_list: list[dict[str, Any]] = []
        for day_key in sorted(days.keys()):
            day = days.get(day_key)
            if not isinstance(day, dict):
                continue
            models_out = {}
            models = day.get("models") or {}
            if isinstance(models, dict):
                for model_id, record in models.items():
                    if not isinstance(record, dict):
                        continue
                    models_out[model_id] = {
                        "name": str(record.get("name") or model_id),
                        "requests": _num(record.get("requests")),
                        "tokens_input": _num(record.get("tokens_input")),
                        "tokens_output": _num(record.get("tokens_output")),
                        "credits": _num(record.get("credits")),
                    }
            hours_out = {}
            hours = day.get("hours") or {}
            if isinstance(hours, dict):
                for hour_key, bucket in hours.items():
                    if not isinstance(bucket, dict):
                        continue
                    hours_out[str(hour_key)] = {
                        "requests": _num(bucket.get("requests")),
                        "tokens": _num(bucket.get("tokens")),
                    }
            day_list.append(
                {
                    "date": day_key,
                    "requests": _num(day.get("requests")),
                    "tokens_input": _num(day.get("tokens_input")),
                    "tokens_output": _num(day.get("tokens_output")),
                    "credits": _num(day.get("credits")),
                    "hours": hours_out,
                    "models": models_out,
                }
            )

        return {
            "ok": True,
            "tracking_enabled": tracking_enabled,
            "as_of": datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z"),
            "days": day_list,
        }


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0
