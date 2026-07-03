import { createStore } from "/js/AlpineStore.js";
import * as api from "/js/api.js";
import {
  toastFrontendError,
  toastFrontendSuccess,
} from "/components/notifications/notification-store.js";

const SOURCE_TITLE = "LLM API Visor";

const MODEL_COLORS = [
  "#66b8ff",
  "#3d7fdb",
  "#8fd0ff",
  "#2a5fb0",
  "#b7e0ff",
  "#1c4585",
  "#d9ecff",
];

export const store = createStore("a0LlmApiVisorInsights", {
  loading: false,
  loaded: false,
  trackingEnabled: false,
  days: [],
  tab: "overview",
  range: "all",

  init() {},

  onOpen() {
    this.refresh();
  },

  cleanup() {},

  async refresh() {
    if (this.loading) return;
    this.loading = true;
    try {
      const result = await api.callJsonApi("plugins/a0_llm_api_visor/insights", {});
      if (!result?.ok) throw new Error(result?.error || "Could not load usage insights.");
      this.trackingEnabled = !!result.tracking_enabled;
      this.days = Array.isArray(result.days) ? result.days : [];
      this.loaded = true;
    } catch (error) {
      toastFrontendError(error?.message || "Could not load usage insights.", SOURCE_TITLE);
    } finally {
      this.loading = false;
    }
  },

  async clearHistory() {
    if (!globalThis.confirm("Delete all locally tracked usage statistics?")) return;
    try {
      const result = await api.callJsonApi("plugins/a0_llm_api_visor/insights", {
        action: "clear",
      });
      if (!result?.ok) throw new Error(result?.error || "Could not clear usage history.");
      this.days = [];
      toastFrontendSuccess("Usage history cleared.", SOURCE_TITLE);
    } catch (error) {
      toastFrontendError(error?.message || "Could not clear usage history.", SOURCE_TITLE);
    }
  },

  setTab(tab) {
    this.tab = tab;
  },

  setRange(range) {
    this.range = range;
  },

  // ----- data selection -----

  rangeDays() {
    if (this.range === "all") return this.days;
    const span = this.range === "30d" ? 30 : 7;
    const cutoff = new Date();
    cutoff.setUTCDate(cutoff.getUTCDate() - (span - 1));
    const cutoffKey = cutoff.toISOString().slice(0, 10);
    return this.days.filter((day) => day.date >= cutoffKey);
  },

  // ----- overview stats -----

  totalRequests() {
    return this.rangeDays().reduce((sum, d) => sum + (d.requests || 0), 0);
  },

  totalTokensIn() {
    return this.rangeDays().reduce((sum, d) => sum + (d.tokens_input || 0), 0);
  },

  totalTokensOut() {
    return this.rangeDays().reduce((sum, d) => sum + (d.tokens_output || 0), 0);
  },

  totalTokens() {
    return this.totalTokensIn() + this.totalTokensOut();
  },

  totalCredits() {
    return this.rangeDays().reduce((sum, d) => sum + (d.credits || 0), 0);
  },

  activeDays() {
    return this.rangeDays().filter((d) => (d.requests || 0) > 0).length;
  },

  streaks() {
    const active = new Set(
      this.days.filter((d) => (d.requests || 0) > 0).map((d) => d.date),
    );
    if (!active.size) return { current: 0, longest: 0 };

    const sorted = [...active].sort();
    let longest = 0;
    let run = 0;
    let previous = null;
    for (const key of sorted) {
      if (previous && this.dayDiff(previous, key) === 1) run += 1;
      else run = 1;
      if (run > longest) longest = run;
      previous = key;
    }

    let current = 0;
    const cursor = new Date();
    if (!active.has(cursor.toISOString().slice(0, 10))) {
      cursor.setUTCDate(cursor.getUTCDate() - 1);
    }
    while (active.has(cursor.toISOString().slice(0, 10))) {
      current += 1;
      cursor.setUTCDate(cursor.getUTCDate() - 1);
    }
    return { current, longest };
  },

  dayDiff(a, b) {
    return Math.round((new Date(`${b}T00:00:00Z`) - new Date(`${a}T00:00:00Z`)) / 86400000);
  },

  peakHourLabel() {
    const totals = {};
    for (const day of this.rangeDays()) {
      for (const [hour, bucket] of Object.entries(day.hours || {})) {
        totals[hour] = (totals[hour] || 0) + (bucket.tokens || 0);
      }
    }
    const entries = Object.entries(totals);
    if (!entries.length) return "--";
    entries.sort((a, b) => b[1] - a[1]);
    const hour = Number(entries[0][0]);
    const period = hour >= 12 ? "PM" : "AM";
    const display = hour % 12 === 0 ? 12 : hour % 12;
    return `${display} ${period} UTC`;
  },

  favoriteModel() {
    const models = this.modelAggregates();
    return models.length ? models[0].name : "--";
  },

  // ----- heatmap -----

  heatmapWeeks() {
    const totalsByDate = new Map(
      this.days.map((d) => [d.date, (d.tokens_input || 0) + (d.tokens_output || 0)]),
    );
    const weeksCount = this.range === "7d" ? 2 : this.range === "30d" ? 6 : 20;

    const today = new Date();
    const end = new Date(Date.UTC(today.getUTCFullYear(), today.getUTCMonth(), today.getUTCDate()));
    // Align columns to weeks ending on the current day's week (Sunday start).
    const daysToSaturday = 6 - end.getUTCDay();
    end.setUTCDate(end.getUTCDate() + daysToSaturday);

    const values = [];
    let max = 0;
    for (const value of totalsByDate.values()) if (value > max) max = value;

    const weeks = [];
    for (let w = weeksCount - 1; w >= 0; w--) {
      const week = [];
      for (let d = 0; d < 7; d++) {
        const cell = new Date(end);
        cell.setUTCDate(end.getUTCDate() - (w * 7 + (6 - d)));
        const key = cell.toISOString().slice(0, 10);
        const value = totalsByDate.get(key) || 0;
        const future = cell > today;
        let level = 0;
        if (value > 0 && max > 0) {
          const ratio = value / max;
          level = ratio > 0.75 ? 4 : ratio > 0.5 ? 3 : ratio > 0.25 ? 2 : 1;
        }
        week.push({ key, value, level, future });
        values.push(value);
      }
      weeks.push(week);
    }
    return weeks;
  },

  cellTitle(cell) {
    if (cell.future) return "";
    return `${cell.key}: ${this.formatCompact(cell.value)} tokens`;
  },

  // ----- models tab -----

  modelAggregates() {
    const byModel = new Map();
    for (const day of this.rangeDays()) {
      for (const [id, record] of Object.entries(day.models || {})) {
        const agg = byModel.get(id) || {
          id,
          name: record.name || id,
          requests: 0,
          tokens_input: 0,
          tokens_output: 0,
          credits: 0,
        };
        agg.name = record.name || agg.name;
        agg.requests += record.requests || 0;
        agg.tokens_input += record.tokens_input || 0;
        agg.tokens_output += record.tokens_output || 0;
        agg.credits += record.credits || 0;
        byModel.set(id, agg);
      }
    }
    const list = [...byModel.values()];
    const total = list.reduce((s, m) => s + m.tokens_input + m.tokens_output, 0);
    list.sort((a, b) => b.tokens_input + b.tokens_output - (a.tokens_input + a.tokens_output));
    return list.map((model, index) => ({
      ...model,
      color: MODEL_COLORS[index % MODEL_COLORS.length],
      percent: total > 0 ? ((model.tokens_input + model.tokens_output) / total) * 100 : 0,
    }));
  },

  modelBars() {
    const models = this.modelAggregates();
    const colorById = new Map(models.map((m) => [m.id, m.color]));
    const days = this.rangeDays().filter(
      (d) => (d.tokens_input || 0) + (d.tokens_output || 0) > 0,
    );
    const shown = days.slice(-30);
    let max = 0;
    for (const day of shown) {
      const total = (day.tokens_input || 0) + (day.tokens_output || 0);
      if (total > max) max = total;
    }
    return shown.map((day) => {
      const total = (day.tokens_input || 0) + (day.tokens_output || 0);
      const segments = Object.entries(day.models || {})
        .map(([id, record]) => ({
          id,
          tokens: (record.tokens_input || 0) + (record.tokens_output || 0),
          color: colorById.get(id) || MODEL_COLORS[0],
        }))
        .filter((s) => s.tokens > 0)
        .sort((a, b) => b.tokens - a.tokens);
      return {
        date: day.date,
        label: this.shortDate(day.date),
        total,
        heightPercent: max > 0 ? (total / max) * 100 : 0,
        title: `${day.date}: ${this.formatCompact(total)} tokens`,
        segments: segments.map((s) => ({
          ...s,
          percent: total > 0 ? (s.tokens / total) * 100 : 0,
        })),
      };
    });
  },

  chartAxisMax() {
    const bars = this.modelBars();
    let max = 0;
    for (const bar of bars) if (bar.total > max) max = bar.total;
    return this.formatCompact(max);
  },

  shortDate(key) {
    const date = new Date(`${key}T00:00:00Z`);
    return date.toLocaleDateString(undefined, {
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });
  },

  hasData() {
    return this.rangeDays().some(
      (d) => (d.requests || 0) > 0 || (d.tokens_input || 0) + (d.tokens_output || 0) > 0,
    );
  },

  formatCompact(value) {
    const number = Number(value || 0);
    if (!Number.isFinite(number)) return "0";
    if (Math.abs(number) >= 1000000)
      return `${(number / 1000000).toFixed(number >= 10000000 ? 0 : 1)}M`;
    if (Math.abs(number) >= 1000) return `${(number / 1000).toFixed(number >= 10000 ? 0 : 1)}K`;
    return Math.round(number).toLocaleString();
  },

  formatMoney(value) {
    return `${Number(value || 0).toLocaleString(undefined, {
      minimumFractionDigits: 2,
      maximumFractionDigits: 2,
    })} $`;
  },
});
