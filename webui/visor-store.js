import { createStore } from "/js/AlpineStore.js";
import * as api from "/js/api.js";
import { toastFrontendError } from "/components/notifications/notification-store.js";

const PLUGIN_NAME = "a0_llm_api_visor";
const SOURCE_TITLE = "LLM API Visor";

export const store = createStore("a0LlmApiVisor", {
  loading: false,
  loaded: false,
  error: "",
  response: null,
  pollTimer: null,
  refreshIntervalMs: 300000,

  init() {},

  onOpen() {
    this.refresh({ silent: true });
  },

  cleanup() {
    this.clearPoll();
  },

  clearPoll() {
    if (this.pollTimer) {
      globalThis.clearTimeout(this.pollTimer);
      this.pollTimer = null;
    }
  },

  schedulePoll() {
    this.clearPoll();
    if (!this.refreshIntervalMs) return;
    this.pollTimer = globalThis.setTimeout(() => {
      this.refresh({ silent: true });
    }, this.refreshIntervalMs);
  },

  async refresh({ force = false, silent = false } = {}) {
    if (this.loading) return;
    this.loading = true;
    this.error = "";

    try {
      const result = await api.callJsonApi("plugins/a0_llm_api_visor/dashboard", { force });
      if (!result?.ok) {
        throw new Error(result?.error || "Could not load Agent Zero LLM API data.");
      }

      this.response = result;
      this.loaded = true;
      const seconds = Number(result?.config?.refresh_interval_seconds || 300);
      this.refreshIntervalMs = Math.max(30, Math.min(3600, seconds)) * 1000;
      this.schedulePoll();
    } catch (error) {
      this.error = error?.message || "Could not load Agent Zero LLM API data.";
      if (!silent) void toastFrontendError(this.error, SOURCE_TITLE);
      this.schedulePoll();
    } finally {
      this.loading = false;
    }
  },

  summary() {
    return this.response?.summary || {};
  },

  openDashboard() {
    const url =
      this.response?.config?.dashboard_url ||
      "https://www.agent-zero.ai/p/community/api-dashboard/";
    globalThis.open(url, "_blank", "noopener,noreferrer");
  },

  async openSettings() {
    const { store } = await import("/components/plugins/plugin-settings-store.js");
    await store.openConfig(PLUGIN_NAME);
  },

  async openInsights() {
    const { openModal } = await import("/js/modals.js");
    await openModal("/plugins/a0_llm_api_visor/webui/insights.html");
  },

  // ----- personalization -----

  personalization() {
    return this.response?.config || {};
  },

  accentColor() {
    const value = String(this.personalization().accent_color || "");
    return /^#[0-9a-fA-F]{6}$/.test(value) ? value : "#66b8ff";
  },

  panelStyle() {
    const config = this.personalization();
    const style = { "--a0-visor-accent": this.accentColor() };
    if (config.background_style === "flat") {
      style.background = "var(--color-panel)";
    } else if (
      config.background_style === "custom" &&
      /^#[0-9a-fA-F]{6}$/.test(String(config.custom_background_color || ""))
    ) {
      style.background = config.custom_background_color;
    }
    return style;
  },

  showProgressBar() {
    return this.personalization().show_progress_bar !== false;
  },

  showMultiplier() {
    return this.personalization().show_multiplier !== false;
  },

  showUsageRow() {
    return this.personalization().show_usage_row !== false;
  },

  insightsEnabled() {
    return this.personalization().usage_insights_enabled === true;
  },

  quotaLabel() {
    if (!this.loaded) return this.loading ? "..." : "--";
    const summary = this.summary();
    if (summary.mode === "needs_wallet") return "Set wallet";
    if (summary.mode === "wallet_unavailable") return "--";
    if (summary.mode === "wallet") {
      return this.formatMoney(summary.user_remaining_quota, 2);
    }
    const remaining = Number(summary.remaining_quota || 0);
    const base = Number(summary.base_quota || 0);
    if (base <= 0) return `${this.formatMoney(remaining, 2)}`;
    return `${this.formatMoney(remaining, 0)} / ${this.formatMoney(base, 0)}`;
  },

  quotaWidth() {
    const summary = this.summary();
    const percent =
      summary.mode === "wallet"
        ? Number(summary.user_quota_percent || 0)
        : Number(summary.quota_percent || 0);
    return `${Math.max(0, Math.min(100, percent)).toFixed(0)}%`;
  },

  multiplierLabel() {
    if (!this.loaded) return "--";
    return `${Number(this.summary().real_multiplier || 0).toFixed(2)}x`;
  },

  usageLabel() {
    if (!this.loaded) return "Usage --";
    const summary = this.summary();
    if (summary.mode === "needs_wallet") return "Wallet required";
    if (summary.mode === "wallet_unavailable") return "Wallet unavailable";
    const requests = summary.mode === "wallet" ? summary.user_requests : summary.global_requests;
    return `${this.formatCompact(requests)} req`;
  },

  resetLabel() {
    if (!this.loaded) return "Reset --";
    return "Reset 00:00 UTC";
  },

  showWalletLine() {
    if (this.personalization().show_wallet_line === false) return false;
    const summary = this.summary();
    return !!summary.wallet_address && (summary.mode === "wallet" || !!summary.wallet_error);
  },

  showDetailLine() {
    if (this.personalization().show_detail_line === false) return false;
    const summary = this.summary();
    return ["wallet", "needs_wallet", "wallet_unavailable", "global"].includes(summary.mode);
  },

  detailLabel() {
    const summary = this.summary();
    if (summary.mode === "wallet") {
      const base = this.formatMoney(summary.user_base_quota, 2);
      const daily = this.formatMoney(summary.user_current_quota, 2);
      const used = this.formatMoney(summary.user_used_quota, 2);
      return `Base ${base} / Daily ${daily} / Used ${used}`;
    }
    if (summary.mode === "needs_wallet") return "Add your public wallet address in settings";
    if (summary.mode === "wallet_unavailable") return summary.wallet_error || "Wallet quota could not be loaded";
    if (summary.mode === "global") return "Global pool view";
    return "";
  },

  walletLabel() {
    const summary = this.summary();
    if (summary.wallet_error) return "Wallet unavailable";
    return summary.wallet_label || "Wallet";
  },

  walletStakeLabel() {
    const summary = this.summary();
    if (summary.wallet_error) return "";
    if (Number(summary.api_stake_sum || 0) > 0) {
      return `${this.formatCompact(summary.api_stake_sum)} AOT`;
    }
    if (Number(summary.stake_score || 0) > 0) {
      return `${this.formatCompact(summary.stake_score)} score`;
    }
    return "";
  },

  formatMoney(value, decimals = 0) {
    const number = Number(value || 0);
    return `${number.toLocaleString(undefined, {
      minimumFractionDigits: decimals,
      maximumFractionDigits: decimals,
    })} $`;
  },

  formatCompact(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return "0";
    if (Math.abs(number) >= 1000000) return `${(number / 1000000).toFixed(number >= 10000000 ? 0 : 1)}M`;
    if (Math.abs(number) >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}K`;
    return Math.round(number).toLocaleString();
  },
});
