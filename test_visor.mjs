import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const moduleUrl = (source) => `data:text/javascript;base64,${Buffer.from(source).toString("base64")}`;
const stubs = moduleUrl(`
  export const createStore = (_, value) => value;
  export const callJsonApi = (...args) => globalThis.visorApi(...args);
  export const toastFrontendError = () => {};
`);
let source = await readFile(new URL("./webui/visor-store.js", import.meta.url), "utf8");
for (const path of ["/js/AlpineStore.js", "/js/api.js", "/components/notifications/notification-store.js"]) {
  source = source.replace(JSON.stringify(path), JSON.stringify(stubs));
}
const { store } = await import(moduleUrl(source));
const setTimeout = globalThis.setTimeout;
const clearTimeout = globalThis.clearTimeout;
const timers = new Map();
globalThis.setTimeout = (callback, delay) => {
  const id = Symbol();
  timers.set(id, { callback, delay });
  return id;
};
globalThis.clearTimeout = (id) => timers.delete(id);
let finishLate;
globalThis.visorApi = () => new Promise((resolve) => { finishLate = resolve; });

try {
  const pending = store.refresh({ silent: true });
  assert.equal(store.loading, true);
  assert.equal(store.quotaLabel(), "...");
  const deadline = [...timers.values()].find((timer) => timer.delay === 30000);
  assert.ok(deadline);
  deadline.callback();
  await pending;
  assert.equal(store.loading, false);
  assert.equal(store.loaded, false);
  assert.match(store.detailLabel(), /timed out/);
  assert.ok(![...timers.values()].some((timer) => timer.delay === 30000));
  assert.ok(store.pollTimer);

  const response = { ok: true, config: {}, summary: { mode: "key", user_remaining_quota: 4.5 } };
  globalThis.visorApi = async (endpoint, payload) => {
    assert.equal(endpoint, "plugins/a0_llm_api_visor/dashboard");
    assert.deepEqual(payload, { force: true });
    return response;
  };
  await store.refresh({ force: true, silent: true });
  assert.equal(store.loading, false);
  assert.equal(store.loaded, true);
  assert.equal(store.error, "");
  assert.equal(store.summary().user_remaining_quota, 4.5);
  finishLate({ ok: true, summary: { user_remaining_quota: 999 } });
  await Promise.resolve();
  assert.equal(store.response, response);

  globalThis.visorApi = async () => ({ ok: false, error: "API could not be reached." });
  await store.refresh({ silent: true });
  assert.equal(store.loading, false);
  assert.equal(store.loaded, false);
  assert.equal(store.detailLabel(), "API could not be reached.");
  assert.ok(![...timers.values()].some((timer) => timer.delay === 30000));
} finally {
  store.clearPoll();
  globalThis.setTimeout = setTimeout;
  globalThis.clearTimeout = clearTimeout;
  delete globalThis.visorApi;
}
console.log("Visor refresh timeout, retry, and error checks passed.");
