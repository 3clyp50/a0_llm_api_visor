# LLM API Visor

## Purpose

Standalone Agent Zero sidebar plugin for the configured API key's remaining allowance.

## Ownership

- `api/dashboard.py` reads `models.get_api_key("a0_venice")` on the server, fetches
  public aggregate data and Bearer-authenticated key status, and projects UI fields.
- `webui/visor-store.js`, `visor.html`, and `config.html` own balance/status rendering
  and settings. Legacy `show_wallet_metrics`/`show_wallet_line` flags now control
  the key balance/status views, preserving saved visibility preferences.
- `api/insights.py`, `helpers/usage_tracker.py`, and `webui/insights*` own separate
  local analytics. Preserve their data. The balance widget no longer records
  remote wallet snapshots; it does not fabricate missing request/model counters.

## Local Contracts

Keep `plugin.yaml` version and `api/dashboard.py` `PLUGIN_VERSION` in sync.

Only official HTTPS API roots on port 443 are accepted. Credential-bearing
requests must not follow redirects. Never return keys, labels, wallet identities,
raw upstream errors, or full status responses to the browser. Do not cache private
responses or accept a wallet/key override from request input. Keep the plugin's
existing framework authentication and CSRF protection.

## Verification

`python3 -m unittest test_dashboard.py` checks saved-key selection, safe output,
missing/rotated credentials, public-only mode, and the HTTP trust boundary using
mocks. `node --check webui/visor-store.js` checks browser-module syntax.
