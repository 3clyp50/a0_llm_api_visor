# LLM API Visor

## Purpose

Standalone Agent Zero sidebar plugin for the configured API key's remaining allowance.

## Ownership

- `api/dashboard.py` reads `models.get_api_key("a0_venice")` on the server, fetches
  public aggregate data and Bearer-authenticated key status, and projects UI fields.
- `webui/visor-store.js`, `visor.html`, and `config.html` own balance/status rendering
  and settings. Legacy `show_wallet_metrics`/`show_wallet_line` flags now control
  the key balance/status views, preserving saved visibility preferences.
- `api/insights.py`, `helpers/usage_tracker.py`, and `webui/insights*` own local
  analytics. Dashboard refreshes record opt-in daily credit spend from key status,
  including in global display mode. Use `resetAt` to identify the UTC usage day
  and merge cumulative spend by maximum. Preserve legacy history and never
  fabricate missing request, token or model counters; those fields stay null in
  new credit-only records. Recording errors must not break the balance response.

## Local Contracts

Keep `plugin.yaml` version and `api/dashboard.py` `PLUGIN_VERSION` in sync.
Bound sidebar refreshes to 30 seconds and show failures even when the optional
detail line is hidden. Late responses must not overwrite a newer refresh.

Only official HTTPS API roots on port 443 are accepted. Credential-bearing
requests must not follow redirects. Never return keys, labels, wallet identities,
raw upstream errors, or full status responses to the browser. Do not cache private
responses or accept a wallet/key override from request input. Keep the plugin's
existing framework authentication and CSRF protection.

## Verification

`python3 -m unittest test_dashboard.py` checks saved-key selection, safe output,
missing/rotated credentials, public-only mode, opt-in recording, UTC daily credit
merging, legacy preservation, and the HTTP trust boundary using mocks.
`node test_insights.mjs` checks credit-only views, activity, and legacy model data.
`node test_visor.mjs` checks refresh timeouts, retries, errors, and late responses.
`node --check webui/visor-store.js` checks browser-module syntax.
