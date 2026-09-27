---
description: First-time deployment - GitHub Pages, Cloudflare Worker, TRMNL Redirect plugin
---

Walk me through deploying lenia-trmnl end to end. Work in order, verify each step before moving on,
and tick the checklist in CLAUDE.md as steps complete. Stop and tell me exactly what to click
whenever a step needs my login or the TRMNL web app.

1. Sanity: `pip install -r requirements.txt`, `pytest -q`, `node --test worker/test/*.test.mjs`.
   Render 20 frames locally and show me 2 of them.
2. GitHub: `git init -b main` and make the first commit with my git identity. Check `gh auth status`.
   If logged in, ask me for the repo name (default `lenia-trmnl`),
   then `gh repo create --public --source . --push`. Enable Pages with source GitHub Actions
   (`gh api -X POST repos/{owner}/{repo}/pages -f build_type=workflow`; if it already exists use PUT).
3. Trigger `gh workflow run render -f n=1440`, watch it (`gh run watch`), then curl
   `https://{owner}.github.io/{repo}/manifest.json` and one frame URL. Confirm content-length header.
4. Worker: put the Pages URL into `worker/wrangler.toml` (SITE_URL), confirm TZ and QUIET_HOURS with me.
   `cd worker && npx wrangler login` (I do the browser part), `npx wrangler deploy`.
   Curl the worker URL twice a minute apart: filename must change, url must return a PNG, response < 2 s.
   Commit the wrangler.toml change.
5. TRMNL (manual, give me the steps): Plugins -> Redirect -> paste the Worker URL
   (`https://` root URL exactly: workers.dev also answers plain http, other paths 404) -> save ->
   add it to the playlist (alone, or with duration set) -> device refresh to 1 min.
   Mention the battery trade-off (~9 days at 1/min on 2500 mAh) and TRMNL's own Sleep Mode.
6. Optional: set CLOUDFLARE_API_TOKEN and CLOUDFLARE_ACCOUNT_ID repo secrets so
   deploy-worker.yml redeploys on changes. Token: custom, this account only, "Workers Scripts: Edit",
   no zone resources, with an expiry. Keep the action SHAs in the workflows pinned.

If anything in TRMNL's behaviour differs from docs/trmnl-notes.md, check their current help pages
and update the notes.
