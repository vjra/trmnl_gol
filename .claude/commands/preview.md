---
description: Render a short local preview of what the display will show
argument-hint: [frames]
---

Run `python lenia_trmnl.py render-day --n ${1:-60} --device x --outdir /tmp/preview --build preview`
(the deployed device is a TRMNL X; pass `--device og` instead if previewing the 800x480 target),
then assemble every 10th frame into a GIF (Pillow) at /tmp/preview/preview.gif and show me a
contact sheet of 6 frames. Report species shown, file sizes (< 90 KB on og; no confirmed limit on x,
flag anything over a few hundred KB) and render time.
