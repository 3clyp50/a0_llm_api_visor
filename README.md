# LLM API Visor

LLM API Visor shows remaining Agent Zero API credits, today's spend, key status,
daily reset, and the public quota multiplier in the sidebar. It supports main
API keys and custom keys with daily limits.

The plugin automatically reads the saved **Agent Zero API** provider key from
Agent Zero model settings. It sends that key server-side in an Authorization
header to the official status endpoint. No wallet address or additional key
entry is needed. Keys, wallet identity, and user-defined key labels are never
returned to the browser. Private responses are not cached.

## Configuration

Open the **settings button on the sidebar widget**.

- **Show API key balance** displays the configured key's remaining allowance.
  Disable it for the public global pool view.
- **Sidebar position** and **Personalization** control placement, colors, the
  progress bar, multiplier, usage/reset row, details, and key-status line.
- **Usage insights** records the configured key's daily credit spend whenever
  the visor refreshes, including when the widget shows the global pool. Opening
  insights also refreshes the current spend. The credit heatmap, active days and
  streaks include these new records. Existing history is preserved; request,
  token and model statistics remain available for older records only because
  the key status endpoint does not supply those counters.

History is collected while Agent Zero's WebUI is open and the visor is mounted.
Missed days cannot be reconstructed from the current-day status endpoint.

The status endpoint must be deployed before using this plugin update. The old
anonymous wallet lookup is no longer used. Existing wallet-address and private
cache settings are ignored. A disabled or expired key displays its status;
missing or invalid credentials display an unavailable state.

## Community Plugin Layout

This directory is ready to be used as the root of a standalone community plugin
repository:

```text
plugin.yaml
default_config.yaml
README.md
LICENSE
api/
extensions/
helpers/
screenshots/
webui/
```

For Agent Zero Plugin Index submission, the `plugin.yaml` `name` field and the
index folder name should both be `a0_llm_api_visor`.
