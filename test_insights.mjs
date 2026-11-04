import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleUrl = (source) => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const stubs = moduleUrl(`
  export const createStore = (_, value) => value;
  export const store = {};
  export const toastFrontendError = () => {};
  export const toastFrontendSuccess = () => {};
`);
let source = await readFile(new URL("./webui/insights-store.js", import.meta.url), "utf8");
for (const path of ["/js/AlpineStore.js", "/js/api.js", "./visor-store.js", "/components/notifications/notification-store.js"]) {
  source = source.replace(JSON.stringify(path), JSON.stringify(stubs));
}
const { store } = await import(moduleUrl(source));
const today = new Date().toISOString().slice(0, 10);
const yesterday = new Date(Date.now() - 86400000).toISOString().slice(0, 10);

store.days = [
  { date: yesterday, credits: 0.5, requests: null, tokens_input: null, tokens_output: null },
  { date: today, credits: 1.5, requests: null, tokens_input: null, tokens_output: null },
];
assert.equal(store.hasData(), true);
assert.equal(store.hasDetailedData(), false);
assert.equal(store.totalCredits(), 2);
assert.equal(store.activeDays(), 2);
assert.equal(store.streaks().current, 2);
const cell = store.heatmapWeeks().flat().find((entry) => entry.key === today);
assert.equal(cell.value, 1.5);
assert.ok(cell.level > 0);
assert.match(store.cellTitle(cell), /credits/);
assert.doesNotMatch(store.cellTitle(cell), /tokens/);
assert.equal(store.modelAggregates().length, 0);

store.days.unshift({ date: "2020-01-01", requests: 3, tokens_input: 50, tokens_output: 20, credits: 0.25, models: { legacy: { name: "Legacy model", tokens_input: 50, tokens_output: 20 } } });
assert.equal(store.hasDetailedData(), true);
assert.equal(store.totalRequests(), 3);
assert.equal(store.totalTokens(), 70);
assert.equal(store.modelAggregates()[0].name, "Legacy model");
store.range = "7d";
assert.equal(store.hasDetailedData(), false);
assert.equal(store.totalCredits(), 2);
assert.equal(store.modelAggregates().length, 0);
console.log("Credit-only and legacy usage insights checks passed.");
