"""Local, opt-in usage history tracker for the LLM API Visor plugin.

All data is stored inside the plugin's own directory
(`<plugin>/data/usage_history.json`) so removing the plugin leaves
nothing behind. Only aggregate numbers (requests, tokens, credits,
per-model splits) are stored - never prompts or message content.
"""

from __future__ import annotations

import json
import os
import tempfile
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DATA_DIR = Path(__file__).resolve().parent.parent / "data"
HISTORY_FILE = DATA_DIR / "usage_history.json"
SCHEMA_VERSION = 1

_LOCK = threading.Lock()


def _empty_history() -> dict[str, Any]:
    return {"version": SCHEMA_VERSION, "last": None, "days": {}}


def load_history() -> dict[str, Any]:
    with _LOCK:
        return _load_unlocked()


def _load_unlocked() -> dict[str, Any]:
    try:
        with open(HISTORY_FILE, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        if not isinstance(data, dict) or not isinstance(data.get("days"), dict):
            return _empty_history()
        data.setdefault("version", SCHEMA_VERSION)
        data.setdefault("last", None)
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return _empty_history()


def _save_unlocked(history: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=str(DATA_DIR), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(history, handle, separators=(",", ":"))
        os.replace(tmp_path, HISTORY_FILE)
    except OSError:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def clear_history() -> None:
    with _LOCK:
        try:
            HISTORY_FILE.unlink(missing_ok=True)
        except OSError:
            pass


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def record_snapshot(user_dashboard: dict[str, Any]) -> None:
    """Merge one API dashboard snapshot into the local history.

    The remote API reports cumulative values for the current epoch
    (UTC day, reset 00:00 UTC), so per-day totals are merged with
    element-wise max. Hourly activity is derived from deltas between
    consecutive snapshots inside the same epoch.
    """
    if not isinstance(user_dashboard, dict):
        return

    usage = user_dashboard.get("usage")
    user_usage = usage.get("user_usage") if isinstance(usage, dict) else None
    if not isinstance(user_usage, dict):
        return

    epoch = int(_num(user_usage.get("epoch")))
    requests = _num(user_usage.get("requests"))
    tokens_input = _num(user_usage.get("tokens_input"))
    tokens_output = _num(user_usage.get("tokens_output"))
    credits = _num(user_usage.get("credits"))

    if requests <= 0 and tokens_input <= 0 and tokens_output <= 0:
        return

    by_model = user_dashboard.get("usageByModel")
    by_model = by_model if isinstance(by_model, list) else []

    now = datetime.now(timezone.utc)
    day_key = now.strftime("%Y-%m-%d")
    hour_key = str(now.hour)

    with _LOCK:
        history = _load_unlocked()
        days = history["days"]
        day = days.get(day_key)
        if not isinstance(day, dict):
            day = {
                "epoch": epoch,
                "requests": 0,
                "tokens_input": 0,
                "tokens_output": 0,
                "credits": 0.0,
                "hours": {},
                "models": {},
            }
            days[day_key] = day

        day["epoch"] = epoch
        day["requests"] = max(_num(day.get("requests")), requests)
        day["tokens_input"] = max(_num(day.get("tokens_input")), tokens_input)
        day["tokens_output"] = max(_num(day.get("tokens_output")), tokens_output)
        day["credits"] = max(_num(day.get("credits")), credits)

        # Hourly delta vs previous snapshot of the same epoch.
        last = history.get("last")
        if isinstance(last, dict) and int(_num(last.get("epoch"))) == epoch:
            delta_requests = requests - _num(last.get("requests"))
            delta_tokens = (tokens_input + tokens_output) - (
                _num(last.get("tokens_input")) + _num(last.get("tokens_output"))
            )
        else:
            delta_requests = requests
            delta_tokens = tokens_input + tokens_output

        if delta_requests > 0 or delta_tokens > 0:
            hours = day.setdefault("hours", {})
            bucket = hours.get(hour_key)
            if not isinstance(bucket, dict):
                bucket = {"requests": 0, "tokens": 0}
                hours[hour_key] = bucket
            bucket["requests"] = _num(bucket.get("requests")) + max(0.0, delta_requests)
            bucket["tokens"] = _num(bucket.get("tokens")) + max(0.0, delta_tokens)

        # Per-model cumulative merge for the current day.
        models = day.setdefault("models", {})
        for entry in by_model:
            if not isinstance(entry, dict):
                continue
            model_id = str(entry.get("model") or "").strip()
            if not model_id or model_id.startswith("_"):
                continue
            record = models.get(model_id)
            if not isinstance(record, dict):
                record = {
                    "name": "",
                    "requests": 0,
                    "tokens_input": 0,
                    "tokens_output": 0,
                    "credits": 0.0,
                }
                models[model_id] = record
            record["name"] = str(entry.get("modelName") or record.get("name") or model_id)
            record["requests"] = max(_num(record.get("requests")), _num(entry.get("requests")))
            record["tokens_input"] = max(
                _num(record.get("tokens_input")), _num(entry.get("tokens_input"))
            )
            record["tokens_output"] = max(
                _num(record.get("tokens_output")), _num(entry.get("tokens_output"))
            )
            record["credits"] = max(_num(record.get("credits")), _num(entry.get("credits")))

        history["last"] = {
            "epoch": epoch,
            "requests": requests,
            "tokens_input": tokens_input,
            "tokens_output": tokens_output,
            "ts": now.replace(microsecond=0).isoformat().replace("+00:00", "Z"),
        }

        _save_unlocked(history)
