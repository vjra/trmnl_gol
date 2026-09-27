// Cloudflare Worker: TRMNL "Redirect" plugin endpoint.
// TRMNL calls this URL; we answer which pre-rendered frame to show and how long to sleep.
// Contract (TRMNL docs): { filename, url, refresh_rate } — filename is the diff key,
// url must be an 800x480 1-bit PNG/BMP, refresh_rate >= 60 s, response within 2 s.

const pad = (i) => String(i).padStart(4, "0");
const HEADERS = { "cache-control": "no-store", "x-content-type-options": "nosniff" };
const SEGMENT = /^[\w-][\w.-]*$/;                  // no leading dot, so no "." / ".." / hidden names

/** Local hour/minute/second/weekday in a time zone (weekday must come from the same zone, not UTC). */
export function localTime(nowMs, tz) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23", weekday: "short",
  }).formatToParts(new Date(nowMs));
  const get = (t) => Number(parts.find((p) => p.type === t).value);
  return {
    h: get("hour"), m: get("minute"), s: get("second"),
    weekday: parts.find((p) => p.type === "weekday").value,
  };
}

/** Seconds until quiet hours end, or 0 if we're not in quiet hours. quiet = "23-7" or "". */
export function quietSeconds(nowMs, tz, quiet) {
  if (!quiet) return 0;
  const [start, end] = quiet.split("-").map(Number);
  const { h, m, s } = localTime(nowMs, tz);
  const inQuiet = start > end ? h >= start || h < end : h >= start && h < end;
  if (!inQuiet) return 0;
  const hoursLeft = (end - h + 24) % 24;
  return Math.max(60, hoursLeft * 3600 - m * 60 - s);
}

const WEEKDAYS = new Set(["Mon", "Tue", "Wed", "Thu", "Fri"]);

/**
 * Seconds to sleep for a reduced-frequency weekday window (e.g. office hours), or 0 outside it.
 * Weekends are never affected. Clamped to the window end, so a poll near the edge doesn't
 * oversleep past it. hours = "10-17", refresh = desired sleep in seconds (e.g. 1800).
 */
export function workSeconds(nowMs, tz, hours, refresh) {
  if (!hours || !(Number(refresh) > 0)) return 0;   // unset or non-numeric: window off, not NaN
  const [start, end] = hours.split("-").map(Number);
  const { h, m, s, weekday } = localTime(nowMs, tz);
  if (!WEEKDAYS.has(weekday)) return 0;
  const inWindow = start > end ? h >= start || h < end : h >= start && h < end;
  if (!inWindow) return 0;
  const hoursLeft = (end - h + 24) % 24;
  const secondsUntilEnd = hoursLeft * 3600 - m * 60 - s;
  return Math.max(60, Math.min(Number(refresh), secondsUntilEnd));
}

/** Manifest shape check: anything else would yield NaN frame indices or odd URLs. */
export function validManifest(m) {
  return m !== null && typeof m === "object"
    && Number.isInteger(m.n) && m.n > 0
    && Number.isFinite(m.interval) && m.interval > 0
    && Number.isFinite(m.start)
    && typeof m.build === "string" && SEGMENT.test(m.build)
    && typeof m.path === "string" && m.path.split("/").every((p) => SEGMENT.test(p));
}

/** Pure frame selection, unit-tested in test/index.test.mjs. */
export function pick(manifest, nowMs, env = {}) {
  const { n, interval, start, build, path } = manifest;
  const k = Math.floor((nowMs / 1000 - start) / interval);
  const idx = ((k % n) + n) % n;                   // loop forever if a daily build fails
  const base = (env.SITE_URL || "").replace(/\/$/, "");
  const tz = env.TZ || "UTC";
  const quiet = quietSeconds(nowMs, tz, env.QUIET_HOURS || "");
  const work = workSeconds(nowMs, tz, env.WORK_HOURS || "", env.WORK_REFRESH || "");
  const sleep = quiet || work;                     // night quiet takes precedence (windows don't overlap)
  return {
    filename: `lenia-${build}-${pad(idx)}`,
    url: `${base}/${path}/${pad(idx)}.png`,
    refresh_rate: sleep > 0 ? sleep : Math.max(60, interval),
  };
}

export default {
  async fetch(request, env) {
    // TRMNL only ever GETs the root; everything else is scanners, so skip the manifest fetch.
    if (new URL(request.url).pathname !== "/") {
      return new Response("not found\n", { status: 404, headers: HEADERS });
    }
    if (request.method !== "GET" && request.method !== "HEAD") {
      return new Response("method not allowed\n", { status: 405, headers: { ...HEADERS, allow: "GET, HEAD" } });
    }
    try {
      const res = await fetch(`${env.SITE_URL.replace(/\/$/, "")}/manifest.json`, {
        cf: { cacheTtl: 60, cacheEverything: true },   // short: new builds replace old frames
        signal: AbortSignal.timeout(1500),              // TRMNL gives us 2 s in total
      });
      if (!res.ok) throw new Error(`manifest ${res.status}`);
      const manifest = await res.json();
      if (!validManifest(manifest)) throw new Error("manifest has unexpected shape");
      return Response.json(pick(manifest, Date.now(), env), { headers: HEADERS });
    } catch (err) {
      console.error(err);                               // detail goes to `wrangler tail`, not the caller
      return Response.json({ error: "manifest unavailable" }, { status: 502, headers: HEADERS });
    }
  },
};
