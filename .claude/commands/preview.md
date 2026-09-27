---
description: Render a short local preview of what the display will show
argument-hint: [frames]
---

Run `python lenia_trmnl.py render-day --n ${1:-60} --outdir /tmp/preview --build preview`,
then assemble every 10th frame into a GIF (Pillow) at /tmp/preview/preview.gif and show me a
contact sheet of 6 frames. Report species shown, file sizes (must stay < 90 KB) and render time.
