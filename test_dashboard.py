"""Run with python3 -m unittest test_dashboard.py; no credentials or network."""
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch
from urllib.error import HTTPError

tracker_spec = importlib.util.spec_from_file_location("visor_usage_tracker", Path(__file__).parent / "helpers/usage_tracker.py")
usage_tracker = importlib.util.module_from_spec(tracker_spec)
tracker_spec.loader.exec_module(usage_tracker)

plugins = types.SimpleNamespace(get_plugin_config=Mock(return_value={}))
models = types.SimpleNamespace(get_api_key=Mock(return_value="sk-a0-fixture"))
with patch.dict(sys.modules, {
    "helpers": types.SimpleNamespace(plugins=plugins),
    "helpers.api": types.SimpleNamespace(ApiHandler=object, Request=object, Response=object),
    "models": models,
    "usr.plugins.a0_llm_api_visor.helpers": types.SimpleNamespace(usage_tracker=usage_tracker),
}):
    spec = importlib.util.spec_from_file_location("visor_dashboard", Path(__file__).parent / "api/dashboard.py")
    dashboard = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(dashboard)
    insights_spec = importlib.util.spec_from_file_location("visor_insights", Path(__file__).parent / "api/insights.py")
    insights = importlib.util.module_from_spec(insights_spec)
    insights_spec.loader.exec_module(insights)

PUBLIC = {"quota": {"globalBaseQuota": 100, "globalRemainingQuota": 75, "epochPhase": 0.5}, "usage": {"requests": 42}}
STATUS = {"enabled": True, "status": "active", "dailyUsdCap": 5, "percentageCap": 100, "spent": 0.5, "effectiveRemaining": 4.5, "limitingState": "combined", "resetAt": "2026-10-29T00:00:00.000Z"}


class DashboardTest(unittest.TestCase):
    def setUp(self):
        plugins.get_plugin_config.reset_mock()
        plugins.get_plugin_config.return_value = {}
        models.get_api_key.reset_mock()
        models.get_api_key.return_value = "sk-a0-fixture"

    def test_saved_key_only_and_response_has_no_identity_or_secret(self):
        with patch.object(dashboard, "_request_json", side_effect=[PUBLIC, {**STATUS, "label": "private label", "address": "private wallet"}]) as fetch:
            result = asyncio.run(dashboard.Dashboard().process({"wallet_address": "attacker", "api_key": "attacker"}, None))
        models.get_api_key.assert_called_once_with("a0_venice")
        self.assertEqual(fetch.call_args_list[1].args, ("https://api.agent-zero.ai", "v1/api-key/status"))
        self.assertEqual(fetch.call_args_list[1].kwargs, {"api_key": "sk-a0-fixture"})
        self.assertEqual(result["summary"]["mode"], "key")
        self.assertEqual(result["summary"]["user_remaining_quota"], 4.5)
        self.assertEqual(result["summary"]["user_used_quota"], 0.5)
        for secret in ("sk-a0-fixture", "private label", "private wallet", "attacker"):
            self.assertNotIn(secret, json.dumps(result))

    def test_missing_key_and_global_mode_do_not_query_private_data(self):
        models.get_api_key.return_value = "None"
        with patch.object(dashboard, "_request_json", return_value=PUBLIC) as fetch:
            result = asyncio.run(dashboard.Dashboard().process({}, None))
        self.assertEqual(result["summary"]["mode"], "needs_key")
        self.assertEqual(fetch.call_count, 1)
        plugins.get_plugin_config.return_value = {"show_wallet_metrics": False}
        models.get_api_key.reset_mock()
        with patch.object(dashboard, "_request_json", return_value=PUBLIC):
            result = asyncio.run(dashboard.Dashboard().process({}, None))
        models.get_api_key.assert_not_called()
        self.assertEqual(result["summary"]["mode"], "global")
        self.assertEqual(result["summary"]["remaining_quota"], 75)

    def test_key_rotation_and_revocation_do_not_reuse_private_cache(self):
        with patch.object(dashboard, "_request_json", side_effect=[PUBLIC, STATUS]):
            asyncio.run(dashboard.Dashboard().process({}, None))
        models.get_api_key.return_value = "sk-a0-new"
        with patch.object(dashboard, "_request_json", side_effect=[PUBLIC, RuntimeError("HTTP 401")]) as fetch:
            result = asyncio.run(dashboard.Dashboard().process({}, None))
        self.assertEqual(fetch.call_args.kwargs, {"api_key": "sk-a0-new"})
        self.assertEqual(result["summary"]["mode"], "key_unavailable")
        self.assertEqual(result["summary"]["user_remaining_quota"], 0)

    def test_opt_in_history_uses_key_status_even_in_global_view(self):
        plugins.get_plugin_config.return_value = {"usage_insights_enabled": True, "show_wallet_metrics": False}
        with patch.object(dashboard, "_request_json", side_effect=[PUBLIC, STATUS]), patch.object(usage_tracker, "record_key_snapshot") as record:
            result = asyncio.run(dashboard.Dashboard().process({}, None))
        record.assert_called_once_with(STATUS)
        self.assertEqual(result["summary"]["mode"], "global")

    def test_history_off_missing_or_invalid_key_does_not_record(self):
        for enabled, key, status in [(False, "sk-a0-fixture", STATUS), (True, "", None), (True, "sk-a0-fixture", RuntimeError("HTTP 401"))]:
            plugins.get_plugin_config.return_value = {"usage_insights_enabled": enabled}
            models.get_api_key.return_value = key
            with self.subTest(enabled=enabled, key=bool(key)), patch.object(dashboard, "_request_json", side_effect=[PUBLIC, status]), patch.object(usage_tracker, "record_key_snapshot") as record:
                asyncio.run(dashboard.Dashboard().process({}, None))
            record.assert_not_called()

    def test_history_write_failure_keeps_balance_and_reports_safe_error(self):
        plugins.get_plugin_config.return_value = {"usage_insights_enabled": True}
        with patch.object(dashboard, "_request_json", side_effect=[PUBLIC, STATUS]), patch.object(usage_tracker, "record_key_snapshot", side_effect=OSError("private filesystem details")):
            result = asyncio.run(dashboard.Dashboard().process({}, None))
        self.assertTrue(result["ok"])
        self.assertEqual(result["summary"]["user_remaining_quota"], 4.5)
        self.assertEqual(result["tracking_error"], "Could not save local credit history.")
        self.assertNotIn("private filesystem details", json.dumps(result))

    def test_bearer_is_sent_in_header_and_error_body_is_not_exposed(self):
        response = Mock()
        response.read.return_value = json.dumps(STATUS).encode()
        response.__enter__ = Mock(return_value=response)
        response.__exit__ = Mock(return_value=False)
        opener = Mock()
        opener.open.return_value = response
        with patch.object(dashboard, "build_opener", return_value=opener):
            self.assertEqual(dashboard._request_json("https://api.agent-zero.ai", "v1/api-key/status", api_key="sk-a0-fixture"), STATUS)
            req = opener.open.call_args.args[0]
            self.assertEqual(req.get_method(), "GET")
            self.assertEqual(req.get_header("Authorization"), "Bearer sk-a0-fixture")
            self.assertNotIn("sk-a0-fixture", req.full_url)
            self.assertIsNone(req.data)
            opener.open.side_effect = HTTPError(req.full_url, 401, "Unauthorized", {}, io.BytesIO(b"sk-a0-fixture"))
            with self.assertRaisesRegex(RuntimeError, "HTTP 401") as error:
                dashboard._request_json("https://api.agent-zero.ai", "v1/api-key/status", api_key="sk-a0-fixture")
            self.assertNotIn("sk-a0-fixture", str(error.exception))
            opener.open.side_effect = ValueError("Invalid header value: sk-a0-fixture")
            with self.assertRaisesRegex(RuntimeError, "request failed") as error:
                dashboard._request_json("https://api.agent-zero.ai", "v1/api-key/status", api_key="sk-a0-fixture")
            self.assertNotIn("sk-a0-fixture", str(error.exception))
        self.assertIsNone(dashboard._NoRedirect().redirect_request(None, None, 302, "", {}, "https://untrusted.invalid"))

    def test_only_official_https_roots(self):
        for url in ("http://api.agent-zero.ai", "https://untrusted.invalid", "https://api.agent-zero.ai:8443", "https://user:pass@api.agent-zero.ai", "https://api.agent-zero.ai?key=foo", "https://api.agent-zero.ai/path"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                dashboard._normalize_api_base_url(url)
        self.assertEqual(dashboard._normalize_api_base_url("https://tapi.agent-zero.ai/"), "https://tapi.agent-zero.ai")


class CreditHistoryTest(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.addCleanup(patch.stopall)
        patch.object(usage_tracker, "DATA_DIR", Path(folder.name)).start()
        patch.object(usage_tracker, "HISTORY_FILE", Path(folder.name) / "usage_history.json").start()

    def test_daily_spend_is_idempotent_preserves_legacy_and_rolls_over(self):
        legacy = {"epoch": 1, "requests": 4, "tokens_input": 120, "tokens_output": 80, "credits": 0.25, "hours": {"1": {"tokens": 200}}, "models": {"old-model": {"tokens_input": 120}}}
        initial = {"version": 1, "last": {"epoch": 1, "requests": 4}, "days": {"2026-10-27": legacy}}
        usage_tracker.HISTORY_FILE.write_text(json.dumps(initial))
        for spent in (0.5, 0.5, 0.3, 0.8):
            usage_tracker.record_key_snapshot({**STATUS, "spent": spent, "label": "private label", "secret": "sk-a0-secret"})
        usage_tracker.record_key_snapshot({**STATUS, "spent": 0.2, "resetAt": "2026-10-30T00:00:00Z"})
        history = usage_tracker.load_history()
        self.assertEqual(history["days"]["2026-10-27"], legacy)
        self.assertEqual(history["days"]["2026-10-28"], {"credits": 0.8})
        self.assertEqual(history["days"]["2026-10-29"], {"credits": 0.2})
        self.assertEqual(history["last"], initial["last"])
        self.assertNotIn("private label", json.dumps(history))
        self.assertNotIn("sk-a0-secret", json.dumps(history))

        with patch.object(insights.plugins, "get_plugin_config", return_value={"usage_insights_enabled": True}):
            result = asyncio.run(insights.Insights().process({}, None))
        self.assertEqual(result["days"][0]["requests"], 4)
        self.assertIsNone(result["days"][1]["requests"])
        self.assertIsNone(result["days"][1]["tokens_input"])
        self.assertEqual(result["days"][1]["credits"], 0.8)

    def test_invalid_or_empty_status_does_not_write_history(self):
        for status in ({}, {"spent": 1}, {**STATUS, "spent": -1}, {**STATUS, "spent": float("nan")}, {**STATUS, "spent": float("inf")}, {**STATUS, "spent": "bad"}, {**STATUS, "resetAt": "bad"}, {**STATUS, "resetAt": "2026-10-29T00:00:00"}):
            with self.subTest(status=status):
                usage_tracker.record_key_snapshot(status)
        self.assertFalse(usage_tracker.HISTORY_FILE.exists())


if __name__ == "__main__":
    unittest.main()
