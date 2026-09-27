# lenia-trmnl

Continuous Game of Life creatures (Lenia) on a TRMNL OG e-ink display, one new frame per minute.
Owner: Sono (data scientist, fluent in Python/numpy; no need to explain basics).

## Architecture

```
GitHub Actions (daily 02:30 UTC)        GitHub Pages                 Cloudflare Worker            TRMNL
python lenia_trmnl.py render-day  -->  site/manifest.json   <----  GET manifest (60 s cache) <-- Redirect plugin polls
  1440 frames, 1-bit 800x480 PNG        site/frames/<build>/NNNN.png  returns {filename,url,         every refresh_rate s
                                                                       refresh_rate}  ---------> downloads url, redraws
                                                                                                  if filename changed
```

- Simulation is deterministic, so everything is pre-rendered. No live server.
- Frame index = `floor((now - manifest.start) / interval) % n`, so the loop keeps playing if a daily build fails.
- Quiet hours (default 23-7 Europe/Vienna) are handled in the Worker by returning a long `refresh_rate`.

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

## Hard constraints (TRMNL OG)

- Image: exactly 800x480, 1-bit PNG (mode "1") or 1-bit BMP. Keep under 90 KB. 2-bit (`--levels 4`) only with firmware >= 1.6 and untested here.
- Redirect JSON: `{filename, url, refresh_rate}`. Respond within 2 s. `refresh_rate` >= 60. Screen only redraws when `filename` changes.
- Image host must send `content-length` (GitHub Pages does).
- Battery: ~13k refreshes per 2500 mAh charge -> ~9 days at 1/min. Quiet hours or USB power matter.
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
- [ ] `worker/wrangler.toml` SITE_URL set, Worker deployed, `curl <worker-url>` returns valid JSON
- [ ] TRMNL: Redirect plugin added with the Worker URL, placed in playlist, device refresh set
- [ ] Watched it change on the device for 10 minutes

## Backlog / ideas

- Flow-Lenia (mass-conserving) to avoid the overgrowth -> reseed cycle.
- Score rotation/replication in `search`; add a "rotation" niche axis.
- Multi-channel Lenia (several species interacting in one world).
- Show a tiny species card (rule, age) in a corner instead of the footer.
- TRMNL X (1872x1404, 16 greys): add `--device x` with its size and 4-bit output.
