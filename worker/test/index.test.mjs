import { test } from "node:test";
import assert from "node:assert/strict";
import { pick, quietSeconds, workSeconds, validManifest } from "../src/index.js";

const manifest = { build: "20260922-0300", n: 1440, interval: 60, start: 1_000_000, path: "frames/20260922-0300" };
const env = { SITE_URL: "https://me.github.io/lenia-trmnl/", TZ: "UTC", QUIET_HOURS: "" };

test("frame 0 at start, advances once per interval", () => {
  const a = pick(manifest, 1_000_000 * 1000, env);
  const b = pick(manifest, (1_000_000 + 61) * 1000, env);
  assert.equal(a.url, "https://me.github.io/lenia-trmnl/frames/20260922-0300/0000.png");
  assert.equal(b.filename, "lenia-20260922-0300-0001");
  assert.equal(a.refresh_rate, 60);
});

test("wraps around after n frames", () => {
  const r = pick(manifest, (1_000_000 + 1440 * 60 + 5) * 1000, env);
  assert.equal(r.filename, "lenia-20260922-0300-0000");
});

test("quiet hours: sleep until the end, not in quiet hours: 0", () => {
  const t0200 = Date.UTC(2026, 8, 22, 2, 0, 0);
  const t1200 = Date.UTC(2026, 8, 22, 12, 0, 0);
  assert.equal(quietSeconds(t0200, "UTC", "23-7"), 5 * 3600);
  assert.equal(quietSeconds(t1200, "UTC", "23-7"), 0);
  assert.equal(pick(manifest, t0200, { ...env, QUIET_HOURS: "23-7" }).refresh_rate, 5 * 3600);
});

test("work hours: reduced refresh weekdays only, clamped to window end", () => {
  const mon1000 = Date.UTC(2026, 8, 28, 10, 0, 0);   // Monday 10:00, window just opened
  const mon1650 = Date.UTC(2026, 8, 28, 16, 50, 0);  // Monday 16:50, 10 min left in window
  const mon0959 = Date.UTC(2026, 8, 28, 9, 59, 0);   // Monday, just before the window
  const sat1200 = Date.UTC(2026, 8, 26, 12, 0, 0);   // Saturday, same hours, not a weekday

  assert.equal(workSeconds(mon1000, "UTC", "10-17", "1800"), 1800);
  assert.equal(workSeconds(mon1650, "UTC", "10-17", "1800"), 600);
  assert.equal(workSeconds(mon0959, "UTC", "10-17", "1800"), 0);
  assert.equal(workSeconds(sat1200, "UTC", "10-17", "1800"), 0);

  const workEnv = { ...env, WORK_HOURS: "10-17", WORK_REFRESH: "1800" };
  assert.equal(pick(manifest, mon1000, workEnv).refresh_rate, 1800);
  assert.equal(pick(manifest, sat1200, workEnv).refresh_rate, 60);
});

test("night quiet hours take precedence over the work-hours window", () => {
  const t = Date.UTC(2026, 8, 28, 0, 0, 0);          // Monday 00:00, inside both (synthetic overlap)
  const r = pick(manifest, t, { ...env, QUIET_HOURS: "23-7", WORK_HOURS: "0-1", WORK_REFRESH: "1800" });
  assert.equal(r.refresh_rate, 7 * 3600);
});

test("work hours: non-numeric WORK_REFRESH disables the window instead of returning NaN", () => {
  const mon1000 = Date.UTC(2026, 8, 28, 10, 0, 0);
  assert.equal(workSeconds(mon1000, "UTC", "10-17", "30min"), 0);
  assert.equal(pick(manifest, mon1000, { ...env, WORK_HOURS: "10-17", WORK_REFRESH: "30min" }).refresh_rate, 60);
});

test("validManifest: accepts the live manifest, rejects shapes that break pick()", () => {
  const live = {   // verbatim from https://vjra.github.io/trmnl_gol/manifest.json, 2026-09-27
    build: "20260927-0926", n: 1440, interval: 60, start: 1790501192, path: "frames/20260927-0926",
    species: ["Sono-B-06", "Sono-B-09", "Sono-C-01", "Sono-C-02", "Sono-C-07", "Sono-C-10"],
  };
  assert.ok(validManifest(live));
  assert.ok(validManifest(manifest));
  for (const bad of [
    null, [], { ...manifest, n: 0 }, { ...manifest, n: 1.5 }, { ...manifest, interval: 0 },
    { ...manifest, start: "now" }, { ...manifest, n: undefined }, { ...manifest, build: "a/b" },
    { ...manifest, path: "../x" }, { ...manifest, path: "frames/../x" }, { ...manifest, path: "//evil.example/x" },
    { ...manifest, path: "frames/<script>" },
  ]) assert.equal(validManifest(bad), false, JSON.stringify(bad));
});

test("fetch handler: reads manifest, returns Redirect JSON; 502 on failure", async () => {
  const { default: worker } = await import("../src/index.js");
  const realFetch = globalThis.fetch, realError = console.error;
  console.error = () => {};
  try {
    globalThis.fetch = async () => new Response(JSON.stringify({ ...manifest, start: Math.floor(Date.now() / 1000) }));
    const ok = await worker.fetch(new Request("https://w.dev/"), env);
    const body = await ok.json();
    assert.equal(ok.status, 200);
    assert.equal(ok.headers.get("x-content-type-options"), "nosniff");
    assert.match(body.filename, /^lenia-20260922-0300-000[01]$/);

    globalThis.fetch = async () => new Response("nope", { status: 404 });
    const bad = await worker.fetch(new Request("https://w.dev/"), env);
    assert.equal(bad.status, 502);
    assert.deepEqual(await bad.json(), { error: "manifest unavailable" });   // no internals leaked

    globalThis.fetch = async () => new Response(JSON.stringify({ ...manifest, n: 0 }));
    assert.equal((await worker.fetch(new Request("https://w.dev/"), env)).status, 502);
  } finally {
    globalThis.fetch = realFetch;
    console.error = realError;
  }
});

test("fetch handler: only GET/HEAD on / reach the manifest", async () => {
  const { default: worker } = await import("../src/index.js");
  const realFetch = globalThis.fetch;
  let calls = 0;
  globalThis.fetch = async () => { calls++; return new Response(JSON.stringify(manifest)); };
  try {
    assert.equal((await worker.fetch(new Request("https://w.dev/favicon.ico"), env)).status, 404);
    assert.equal((await worker.fetch(new Request("https://w.dev/../../etc/passwd"), env)).status, 404);
    const post = await worker.fetch(new Request("https://w.dev/", { method: "POST" }), env);
    assert.equal(post.status, 405);
    assert.equal(post.headers.get("allow"), "GET, HEAD");
    assert.equal((await worker.fetch(new Request("https://w.dev/", { method: "HEAD" }), env)).status, 200);
    assert.equal((await worker.fetch(new Request("https://w.dev/?utm=x"), env)).status, 200);
    assert.equal(calls, 2);                                               // HEAD / and /?utm=x only
  } finally {
    globalThis.fetch = realFetch;
  }
});
