import { test } from "node:test";
import assert from "node:assert/strict";
import { pick, quietSeconds } from "../src/index.js";

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

test("fetch handler: reads manifest, returns Redirect JSON; 502 on failure", async () => {
  const { default: worker } = await import("../src/index.js");
  const realFetch = globalThis.fetch;
  globalThis.fetch = async () => new Response(JSON.stringify({ ...manifest, start: Math.floor(Date.now() / 1000) }));
  const ok = await worker.fetch(new Request("https://w.dev/"), env);
  const body = await ok.json();
  assert.equal(ok.status, 200);
  assert.match(body.filename, /^lenia-20260922-0300-000[01]$/);
  globalThis.fetch = async () => new Response("nope", { status: 404 });
  const bad = await worker.fetch(new Request("https://w.dev/"), env);
  assert.equal(bad.status, 502);
  globalThis.fetch = realFetch;
});
