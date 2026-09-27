// Cloudflare Worker: TRMNL "Redirect" plugin endpoint.
// TRMNL calls this URL; we answer which pre-rendered frame to show and how long to sleep.
// Contract (TRMNL docs): { filename, url, refresh_rate } — filename is the diff key,
// url must be an 800x480 1-bit PNG/BMP, refresh_rate >= 60 s, response within 2 s.

const pad = (i) => String(i).padStart(4, "0");

/** Local hour/minute/second in a time zone. */
export function localTime(nowMs, tz) {
  const parts = new Intl.DateTimeFormat("en-GB", {
    timeZone: tz, hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23",
  }).formatToParts(new Date(nowMs));
  const get = (t) => Number(parts.find((p) => p.type === t).value);
  return { h: get("hour"), m: get("minute"), s: get("second") };
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

/** Pure frame selection, unit-tested in test/index.test.mjs. */
export function pick(manifest, nowMs, env = {}) {
  const { n, interval, start, build, path } = manifest;
  const k = Math.floor((nowMs / 1000 - start) / interval);
  const idx = ((k % n) + n) % n;                   // loop forever if a daily build fails
  const base = (env.SITE_URL || "").replace(/\/$/, "");
  const sleep = quietSeconds(nowMs, env.TZ || "UTC", env.QUIET_HOURS || "");
  return {
    filename: `lenia-${build}-${pad(idx)}`,
    url: `${base}/${path}/${pad(idx)}.png`,
    refresh_rate: sleep > 0 ? sleep : Math.max(60, interval),
  };
}

export default {
  async fetch(request, env) {
    try {
      const res = await fetch(`${env.SITE_URL.replace(/\/$/, "")}/manifest.json`, {
        cf: { cacheTtl: 60, cacheEverything: true },   // short: new builds replace old frames
        signal: AbortSignal.timeout(1500),              // TRMNL gives us 2 s in total
      });
      if (!res.ok) throw new Error(`manifest ${res.status}`);
      const manifest = await res.json();
      return Response.json(pick(manifest, Date.now(), env), {
        headers: { "cache-control": "no-store" },
      });
    } catch (err) {
      return Response.json({ error: String(err) }, { status: 502 });
    }
  },
};
