# TRMNL notes (checked 2026-09-22)

## Device (OG)
- 7.5", 800x480, 4 grey levels, ~2 s refresh. https://trmnl.com/products/og/spec-sheet
- Images: 1-bit BMP (bmp3) or 1-bit PNG, 800x480. 2-bit PNG on firmware >= 1.6.x.
  https://help.trmnl.com/en/articles/10701448-alias-plugin
- Keep PNGs small; community BYOS libraries cite ~90 KB as the firmware limit. https://docs.rs/trmnl
- Battery: firmware README estimates ~13,400 refreshes per 2500 mAh charge.
  https://github.com/usetrmnl/trmnl-firmware

## Device (X) - the one actually deployed here
- 1872x1404, 16 grey levels (4-bit). Resolution per Sono, not yet cross-checked against a TRMNL spec
  page or the firmware repo above - confirm size/KB-limit/battery figures there before relying on them.
- Wrong size was the cause of the "small image, rest of the screen blank" bug: we were serving OG-sized
  (800x480) frames to an X device, which (per TRMNL's own Redirect troubleshooting page) does not scale
  a mismatched image to fill the screen. `render-day --device x` fixes this; see CLAUDE.md.

## Ways to get pixels onto it
| Plugin | How | Fastest | Notes |
|---|---|---|---|
| Redirect (used here) | TRMNL GETs our URL, we return `{filename, url, refresh_rate}` | 1/min | 2 s timeout; `filename` is the diff key; url may even be LAN. https://help.trmnl.com/en/articles/11035846-redirect-plugin |
| Alias | fixed image URL | playlist interval | no per-frame URL, so no animation |
| Webhook Image | POST PNG to private URL | 12/h | 5 MB max. https://help.trmnl.com/en/articles/13213669-webhook-image |
| BYOS | device talks to your own server | whatever you return | replaces TRMNL cloud entirely |

- Image host must send a `content-length` header (reported firmware requirement).
- Redirect/Alias/private plugins may require the Developer add-on on the account.
- TRMNL fetches from worker boxes (incl. Hetzner EU): don't geo-block the Worker.
- Refresh precedence: device refresh -> playlist item duration -> plugin minimum.
  https://help.trmnl.com/en/articles/10113695-how-refresh-rates-work
