# lenia-trmnl

Continuous Game of Life creatures (Lenia) on a TRMNL e-ink display, one new frame per minute.
Owner: Sono (data scientist, fluent in Python/numpy; no need to explain basics).
The deployed device is a **TRMNL X** (1872x1404, 4-bit/16 greys) -> `render-day --device x` in render.yml.
`--device og` (800x480, 1-bit, the default) is the original/smaller target; keep both working.

## Architecture

```
GitHub Actions (daily 02:30 UTC)        GitHub Pages                 Cloudflare Worker            TRMNL
python lenia_trmnl.py render-day  -->  site/manifest.json   <----  GET manifest (60 s cache) <-- Redirect plugin polls
  --device x: 1440 frames,              site/frames/<build>/NNNN.png  returns {filename,url,         every refresh_rate s
  4-bit 1872x1404 PNG                                                 refresh_rate}  ---------> downloads url, redraws
                                                                                                  if filename changed
```

- Simulation is deterministic, so everything is pre-rendered. No live server.
- Frame index = `floor((now - manifest.start) / interval) % n`, so the loop keeps playing if a daily build fails.
- `Display` rotates species every `--epoch` frames (default 60, i.e. 1 h at 1/min), or sooner on
  extinction/overgrowth. Measured: most species reach their steady state within ~10-40 frames and then
  just sit there unchanged (several plateau around 20-35% occupancy, well under the 45% overgrowth
  threshold, so that detector alone never rotates them) - `--epoch` is the real ceiling on how long any
  one creature, growing or not, stays on screen. Don't raise it back toward hours without re-checking that.
- Quiet hours (default 23-7 Europe/Vienna) are handled in the Worker by returning a long `refresh_rate`.
- Weekday office hours (default 10-17, Mon-Fri) get a reduced-frequency `refresh_rate` (default 1800 s)
  instead of full sleep; night quiet takes precedence if the windows ever overlap.
- Each Pages deploy also ships the previously live build's frames (`render-day --keep-previous`): a deploy
  replaces the whole site, but the old manifest stays cached up to 10 min and would otherwise point at 404s.
- The Worker only answers GET/HEAD on `/` and validates the manifest; errors return a generic 502
  (details via `npx wrangler tail`). CI actions are SHA-pinned because deploy-worker holds the Cloudflare token.

## Code map

- `lenia_trmnl.py` - single-file engine + CLI. Sections: Rule/World (FFT Lenia on a torus), KNOWN + ORBIUM,
  search (soup harvest + MAP-Elites), render (dither/contour/strobe), examples, Display (rotation loop), CLI.
- `species.json` - the display rotation (13 curated species): rule params + cropped body (`cells`).
- `species_all.json` - every species found so far (28), including near-duplicates and sessile ones.
- `worker/src/index.js` - Redirect endpoint. `pick()` is pure and unit-tested.
- `.github/workflows/` - `render.yml` (daily render -> Pages), `test.yml`, `deploy-worker.yml` (optional).
- `docs/trmnl-notes.md` - platform facts and limits with sources. Read before changing output format or timing.

## Commands

```
pip install -r requirements.txt
pytest -q                                          # engine, species, render format, render-day
node --test worker/test/*.test.mjs                 # worker logic
python lenia_trmnl.py render-day --n 20 --outdir site   # quick local check, look at site/index.html
python lenia_trmnl.py examples --gif               # overview.png, per-species frames, preview GIF
python lenia_trmnl.py overview --species species_all.json --names A,B --reference --out x.png
python lenia_trmnl.py gifs --scale 6 --count 1 --follow     # creature portraits (camera tracks it)
python lenia_trmnl.py gifs --scale 3 --count 4              # ecosystems: collisions, replication
python lenia_trmnl.py search --soup 300 --n 1500 --seed N --prefix Name   # new species, ~4 min
cd worker && npx wrangler dev                      # local worker; npx wrangler deploy to ship
```

## Hard constraints

- Image, OG: exactly 800x480, 1-bit PNG (mode "1") or 1-bit BMP. Keep under 90 KB (firmware limit).
- Image, X: exactly 1872x1404, 4-bit/16-grey PNG (`--device x` gives both automatically). No confirmed
  KB limit from TRMNL for X - `render()`'s true-bit-depth palette PNGs measure ~9-25 KB in practice,
  comfortably under the Webhook Image plugin's unrelated 5 MB cap; revisit if that changes.
- `--device x` also defaults `--scale` to 6 (vs. OG's 3): at OG's finer grid, render-day's 1440-frame
  loop takes ~38 min on X's larger canvas, over the render.yml job's 30 min budget: measured ~13 min at
  scale 6. If you add a third device or change scale, re-time a full `render-day -n 1440` before shipping.
- Redirect JSON: `{filename, url, refresh_rate}`. Respond within 2 s. `refresh_rate` >= 60. Screen only redraws when `filename` changes.
- Image host must send `content-length` (GitHub Pages does).
- Battery: ~13k refreshes per 2500 mAh charge (OG's figure; X unconfirmed) -> ~9 days at 1/min. Quiet hours or USB power matter.
- Webhook Image plugin (`tick --push`) is capped at 12 uploads/h; it is the fallback, not the main path.

## Conventions

- Keep the engine dependency-light (numpy, pillow, scipy). No torch/jax.
- Any change to rendering: regenerate `docs/examples/` and eyeball them; check the 90 KB limit via pytest.
- Any change to species.json: `pytest` must pass (every species must survive 200 steps in isolation).
- Plain, concise copy in docs and labels.

## Setup status

Run `/setup` to walk through first-time deployment. Steps that need Sono's accounts (GitHub login,
Cloudflare login, TRMNL web app) must be handed to her; don't fake them. Track progress here:

- [x] GitHub repo created and pushed (Pages requires a public repo on the free plan) -> github.com/vjra/trmnl_gol
- [x] Pages source set to GitHub Actions, first `render` run green, `<SITE_URL>/manifest.json` reachable -> https://vjra.github.io/trmnl_gol/
- [x] `worker/wrangler.toml` SITE_URL set, Worker deployed, `curl <worker-url>` returns valid JSON -> https://lenia-trmnl.oliver-leingang-public.workers.dev/
- [x] TRMNL: Redirect plugin added with the Worker URL, placed in playlist
- [ ] Lenia given its own playlist (or made dominant in the shared one) - it was sharing "The day ahead"
  with 6 other items and only came up ~1x/12h, defeating the 1/min animation
- [ ] Watched it change on the device for 10 minutes, at the correct 1872x1404 TRMNL X size

## Backlog / ideas

- Flow-Lenia (mass-conserving) to avoid the overgrowth -> reseed cycle.
- Score rotation/replication in `search`; add a "rotation" niche axis.
- Multi-channel Lenia (several species interacting in one world).
- Show a tiny species card (rule, age) in a corner instead of the footer.
- X's default `--count` (3) looks sparse on its much bigger canvas at the same species density as OG;
  consider a device-specific default, or scoring "coverage" in `search` the way `--max-occ` already caps it.
