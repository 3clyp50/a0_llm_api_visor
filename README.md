# LLM API Visor

LLM API Visor adds a compact Agent Zero LLM API status panel to Agent Zero's
left sidebar. It is designed around the wallet-specific **Free Daily API
Credits** number from the dashboard: remaining daily credits, current dynamic
quota, base quota, used quota, request usage, reset-cycle progress, and the
current quota multiplier.

The plugin reads the official Agent Zero API dashboard endpoints through a small
Agent Zero backend proxy. No LLM API key is stored or displayed by this plugin.

## What It Shows

- Wallet remaining daily API credits as the primary sidebar value.
- Wallet base quota, current dynamic quota, used quota, and request count.
- Current quota multiplier and reset-cycle progress.
- Optional public wallet A0T, ETH, stake score, and API stake total.
- Explicit global pool view when wallet metrics are disabled.
- Top wallet model usage when the dashboard returns it.
- Optional local usage insights for daily requests, token totals, credits used,
  model split, streaks, peak hour, and a lightweight activity heatmap.
- Sidebar personalization for accent color, panel background, progress bar,
  multiplier, usage row, quota details, and wallet line visibility.

## Configuration

Open **Settings -> External Services -> LLM API Visor**.

- **Wallet address**: Base/Ethereum-style `0x...` public address used to load
  the personal daily credits shown on the dashboard.
- **Show wallet metrics**: keeps wallet daily credits as the primary sidebar
  value. When disabled, the visor shows an explicit global pool view instead.
- **Sidebar position**: places the visor in the upper sidebar or near the lower
  sidebar controls.
- **Personalization**: controls the sidebar accent color, background style, and
  which rows are visible.
- **Usage insights**: optional local-only tracking. It stores aggregate usage
  statistics in the plugin's own `data/` folder and never records prompts,
  messages, API keys, or secrets.

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
