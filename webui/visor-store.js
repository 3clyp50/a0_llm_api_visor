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
  mountCount: 0,
  refreshIntervalMs: 300000,

  init() {},

  onOpen() {
    this.mountCount += 1;
    this.refresh({ silent: true });
  },

  cleanup() {
    this.mountCount = Math.max(0, this.mountCount - 1);
    if (this.mountCount === 0) this.clearPoll();
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
    let timeout;

    try {
      const result = await Promise.race([
        api.callJsonApi("plugins/a0_llm_api_visor/dashboard", { force }),
        new Promise((_, reject) => {
          timeout = globalThis.setTimeout(() => reject(new Error("Balance request timed out. Please retry.")), 30000);
        }),
      ]);
      if (!result?.ok) {
        throw new Error(result?.error || "Could not load Agent Zero LLM API data.");
      }

      this.response = result;
      this.loaded = true;
      const seconds = Number(result?.config?.refresh_interval_seconds || 300);
      this.refreshIntervalMs = Math.max(30, Math.min(3600, seconds)) * 1000;
      this.schedulePoll();
    } catch (error) {
      this.response = null;
      this.loaded = false;
      this.error = error?.message || "Could not load Agent Zero LLM API data.";
      if (!silent) void toastFrontendError(this.error, SOURCE_TITLE);
      this.schedulePoll();
    } finally {
      globalThis.clearTimeout(timeout);
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

  sidebarPosition() {
    return this.personalization().sidebar_position === "bottom" ? "bottom" : "top";
  },

  showAt(position) {
    return this.sidebarPosition() === position;
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
    if (summary.mode === "needs_key") return "Set API key";
    if (summary.mode === "key_unavailable") return "--";
    if (summary.mode === "key") {
      if (["disabled", "expired", "not-yet-valid"].includes(summary.key_status)) return this.statusLabel();
      return this.formatMoney(summary.user_remaining_quota, 2);
    }
    const remaining = Number(summary.remaining_quota || 0);
    const base = Number(summary.base_quota || 0);
    if (base <= 0) return `${this.formatMoney(remaining, 2)}`;
    return `${this.formatMoney(remaining, 0)} / ${this.formatMoney(base, 0)}`;
  },

  quotaWidth() {
    const summary = this.summary();
    const percent = ["disabled", "expired", "not-yet-valid"].includes(summary.key_status)
      ? 0 : Number(summary.quota_percent || 0);
    return `${Math.max(0, Math.min(100, percent)).toFixed(0)}%`;
  },

  multiplierLabel() {
    if (!this.loaded) return "--";
    return `${Number(this.summary().real_multiplier || 0).toFixed(2)}x`;
  },

  usageLabel() {
    if (!this.loaded) return "Usage --";
    const summary = this.summary();
    if (summary.mode === "needs_key") return "API key required";
    if (summary.mode === "key_unavailable") return "API key unavailable";
    if (summary.mode === "key") return `${this.formatMoney(summary.user_used_quota, 2)} used`;
    return `${this.formatCompact(summary.global_requests)} req`;
  },

  resetLabel() {
    if (!this.loaded) return "Reset --";
    const phase = Math.max(0, Math.min(1, Number(this.summary().epoch_phase || 0)));
    const resetAt = Date.parse(this.summary().reset_at || "");
    const minutes = Number.isFinite(resetAt)
      ? Math.max(0, Math.ceil((resetAt - Date.now()) / 60000))
      : Math.round((1 - phase) * 24 * 60);
    if (minutes <= 0) return "Reset soon";
    const hours = Math.floor(minutes / 60);
    const rest = minutes % 60;
    if (hours && rest) return `Reset in ${hours}h ${rest}m`;
    if (hours) return `Reset in ${hours}h`;
    return `Reset in ${rest}m`;
  },

  showWalletLine() {
    return this.personalization().show_wallet_line !== false && this.summary().mode === "key";
  },

  showDetailLine() {
    return this.personalization().show_detail_line !== false;
  },

  detailLabel() {
    if (this.error) return this.error;
    const summary = this.summary();
    if (summary.mode === "key") return `Remaining today: ${this.formatMoney(summary.user_remaining_quota, 2)}`;
    if (summary.mode === "needs_key") return "Configure the Agent Zero API key in model settings";
    if (summary.mode === "key_unavailable") return summary.key_error || "API key status could not be loaded";
    if (summary.mode === "global") return "Global pool view";
    return "";
  },

  statusLabel() {
    const status = this.summary().key_status || "";
    return status.replaceAll("-", " ").replace(/^./, (letter) => letter.toUpperCase());
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
