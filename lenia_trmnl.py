#!/usr/bin/env python3
"""
lenia_trmnl.py - continuous "Game of Life" creatures (Lenia) for a TRMNL e-ink display.

Lenia (Bert Chan, 2018) replaces Conway's discrete rules with:
    A(t+dt) = clip( A + dt * G(K * A), 0, 1 )
where A is a continuous field in [0,1], K a smooth ring-shaped kernel and
G a bell-shaped growth function. Some parameter sets produce stable, moving
"creatures" (e.g. Orbium, the continuous cousin of the glider).

Subcommands
    search    find original species: harvest solitons from random multi-ring soups,
              then a MAP-Elites walk through rule space (seeded with Orbium),
              binned by speed / size / pulsing / ring count, long-run verified
    examples  overview plot + TRMNL-ready 800x480 1-bit PNGs (+ optional GIF preview)
    init      start a persistent world for the display (state in world.npz)
    render-day  pre-render a loop of frames + manifest.json for static hosting
              (GitHub Pages + Cloudflare Worker + TRMNL Redirect plugin, 1 frame/min)
    tick      advance a persistent world one frame, optionally POST it to TRMNL
              (Webhook Image plugin, max 12/h). Both rotate to the next species on
              extinction, overgrowth, or after --epoch frames

Quickstart
    pip install numpy pillow scipy matplotlib requests
    python lenia_trmnl.py search --soup 300 --n 1500      # ~3-4 min on one core -> species.json
    python lenia_trmnl.py examples --gif                   # -> examples/
    python lenia_trmnl.py render-day --n 1440 --outdir site   # ~3 min, ~18 MB

TRMNL OG: 800x480, 1-bit PNG is the safe format (2-bit via --levels 4 is experimental).
Webhook Image plugin accepts PNG/JPEG/BMP up to 5 MB, max 12 uploads per hour.
"""
from __future__ import annotations

import argparse
import json
import math
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

# --------------------------------------------------------------------------
# Rule definition
# --------------------------------------------------------------------------

@dataclass
class Rule:
    name: str = "unnamed"
    R: int = 13                    # kernel radius (cells)
    T: int = 10                    # time resolution, dt = 1/T
    b: list = field(default_factory=lambda: [1.0])   # ring heights
    m: float = 0.15                # growth centre
    s: float = 0.015               # growth width
    kn: int = 1                    # kernel core: 1 = exponential bump, 2 = polynomial, 3 = step
    gn: int = 1                    # growth: 1 = gaussian, 2 = polynomial, 3 = step

    @property
    def dt(self) -> float:
        return 1.0 / self.T


def kernel_core(r: np.ndarray, kn: int) -> np.ndarray:
    r = np.clip(r, 1e-9, 1 - 1e-9)
    if kn == 1:
        return np.exp(4 - 1 / (r * (1 - r)))
    if kn == 2:
        return (4 * r * (1 - r)) ** 4
    return ((r > 0.25) & (r < 0.75)).astype(float)


def growth(u: np.ndarray, m: float, s: float, gn: int) -> np.ndarray:
    if gn == 1:
        return 2 * np.exp(-((u - m) ** 2) / (2 * s * s)) - 1
    if gn == 2:
        return 2 * np.maximum(0, 1 - (u - m) ** 2 / (9 * s * s)) ** 4 - 1
    return 2 * (np.abs(u - m) <= s) - 1.0


class World:
    """Toroidal Lenia world, FFT convolution."""

    def __init__(self, rule: Rule, shape=(128, 128), A: np.ndarray | None = None):
        self.rule = rule
        self.shape = shape
        self.A = np.zeros(shape) if A is None else A.astype(float)
        self.t = 0
        self._build_kernel()

    def _build_kernel(self):
        h, w = self.shape
        y = np.fft.fftfreq(h, 1 / h)[:, None]
        x = np.fft.fftfreq(w, 1 / w)[None, :]
        D = np.sqrt(x * x + y * y) / self.rule.R
        B = len(self.rule.b)
        Br = B * D
        ring = np.minimum(Br.astype(int), B - 1)
        heights = np.asarray(self.rule.b, float)[ring]
        K = (D < 1) * heights * kernel_core(Br % 1, self.rule.kn)
        K /= K.sum()
        self.fK = np.fft.fft2(K)

    def potential(self) -> np.ndarray:
        return np.real(np.fft.ifft2(self.fK * np.fft.fft2(self.A)))

    def step(self, n: int = 1):
        r = self.rule
        for _ in range(n):
            U = self.potential()
            self.A = np.clip(self.A + r.dt * growth(U, r.m, r.s, r.gn), 0, 1)
            self.t += 1
        return self

    # --- helpers -----------------------------------------------------------
    def mass(self) -> float:
        return float(self.A.sum())

    def centroid(self) -> tuple[float, float]:
        """Centroid on a torus (circular mean), returns (y, x)."""
        h, w = self.shape
        m = self.A.sum() + 1e-12
        out = []
        for axis, n in ((0, h), (1, w)):
            prof = self.A.sum(axis=1 - axis)
            ang = 2 * np.pi * np.arange(n) / n
            c = np.angle((prof * np.exp(1j * ang)).sum() / m)
            out.append((c % (2 * np.pi)) * n / (2 * np.pi))
        return out[0], out[1]


# --------------------------------------------------------------------------
# Known species (parameters from Chan's Lenia work)
# --------------------------------------------------------------------------

KNOWN = {
    "orbium": Rule("Orbium", R=13, T=10, b=[1], m=0.15, s=0.015),
    "hydrogeminium": Rule("Hydrogeminium natans", R=18, T=2, b=[0.5, 1, 0.667], m=0.26, s=0.036),
}

# Orbium body (Chan's reference pattern, 20x20)
ORBIUM = [[0,0,0,0,0,0,0.1,0.14,0.1,0,0,0.03,0.03,0,0,0.3,0,0,0,0],
[0,0,0,0,0,0.08,0.24,0.3,0.3,0.18,0.14,0.15,0.16,0.15,0.09,0.2,0,0,0,0],
[0,0,0,0,0,0.15,0.34,0.44,0.46,0.38,0.18,0.14,0.11,0.13,0.19,0.18,0.45,0,0,0],
[0,0,0,0,0.06,0.13,0.39,0.5,0.5,0.37,0.06,0,0,0,0.02,0.16,0.68,0,0,0],
[0,0,0,0.11,0.17,0.17,0.33,0.4,0.38,0.28,0.14,0,0,0,0,0,0.18,0.42,0,0],
[0,0,0.09,0.18,0.13,0.06,0.08,0.26,0.32,0.32,0.27,0,0,0,0,0,0,0.82,0,0],
[0.27,0,0.16,0.12,0,0,0,0.25,0.38,0.44,0.45,0.34,0,0,0,0,0,0.22,0.17,0],
[0,0.07,0.2,0.02,0,0,0,0.31,0.48,0.57,0.6,0.57,0,0,0,0,0,0,0.49,0],
[0,0.59,0.19,0,0,0,0,0.2,0.57,0.69,0.76,0.76,0.49,0,0,0,0,0,0.36,0],
[0,0.58,0.19,0,0,0,0,0,0.67,0.83,0.9,0.92,0.87,0.12,0,0,0,0,0.22,0.07],
[0,0,0.46,0,0,0,0,0,0.7,0.93,1,1,1,0.61,0,0,0,0,0.18,0.11],
[0,0,0.82,0,0,0,0,0,0.47,1,1,0.98,1,0.96,0.27,0,0,0,0.19,0.1],
[0,0,0.46,0,0,0,0,0,0.25,1,1,0.84,0.92,0.97,0.54,0.14,0.04,0.1,0.21,0.05],
[0,0,0,0.4,0,0,0,0,0.09,0.8,1,0.82,0.8,0.85,0.63,0.31,0.18,0.19,0.2,0.01],
[0,0,0,0.36,0.1,0,0,0,0.05,0.54,0.86,0.79,0.74,0.72,0.6,0.39,0.28,0.24,0.13,0],
[0,0,0,0.01,0.3,0.07,0,0,0.08,0.36,0.64,0.7,0.64,0.6,0.51,0.39,0.29,0.19,0.04,0],
[0,0,0,0,0.1,0.24,0.14,0.1,0.15,0.29,0.45,0.53,0.52,0.46,0.4,0.31,0.21,0.08,0,0],
[0,0,0,0,0,0.08,0.21,0.21,0.22,0.29,0.36,0.39,0.37,0.33,0.26,0.18,0.09,0,0,0],
[0,0,0,0,0,0,0.03,0.13,0.19,0.22,0.24,0.24,0.23,0.18,0.13,0.05,0,0,0,0],
[0,0,0,0,0,0,0,0,0.02,0.06,0.08,0.09,0.07,0.05,0.01,0,0,0,0,0]]



def seed_patch(shape, size, rng, density=1.0, pos=None):
    """Random square patch - the 'primordial soup' creatures condense out of."""
    A = np.zeros(shape)
    h, w = shape
    cy, cx = pos if pos else (h // 2, w // 2)
    patch = rng.random((size, size)) * density
    # soften edges so we don't start with hard squares
    yy, xx = np.mgrid[:size, :size]
    d = np.sqrt((yy - size / 2) ** 2 + (xx - size / 2) ** 2) / (size / 2)
    patch *= np.clip(1.2 - d, 0, 1)
    ys = (np.arange(size) + cy - size // 2) % h
    xs = (np.arange(size) + cx - size // 2) % w
    A[np.ix_(ys, xs)] = patch
    return A


def seed_soup(shape, rng, n_patches, size):
    A = np.zeros(shape)
    for _ in range(n_patches):
        pos = (rng.integers(shape[0]), rng.integers(shape[1]))
        A = np.maximum(A, seed_patch(shape, size, rng, pos=pos))
    return A


# --------------------------------------------------------------------------
# Search for original creatures: MAP-Elites walk through rule space
# --------------------------------------------------------------------------
# Random rules almost never produce creatures from noise (they die or explode).
# Instead we do what Chan did by hand, automatically: start from a living
# creature, nudge the rule a little, let the body re-settle, keep it if it
# survives. An archive binned by (speed, size) keeps the zoo diverse; within a
# bin the more intricate / more dynamic creature wins.

def resize_cells(cells: np.ndarray, factor: float) -> np.ndarray:
    if abs(factor - 1) < 1e-3:
        return cells
    h, w = cells.shape
    size = (max(3, round(w * factor)), max(3, round(h * factor)))
    im = Image.fromarray(cells.astype(np.float32), "F").resize(size, Image.BILINEAR)
    return np.clip(np.asarray(im), 0, 1)


def mutate(rule: Rule, rng) -> Rule:
    r = Rule(**asdict(rule))
    r.b = list(r.b)
    k = rng.random()
    if k < 0.35:
        r.m = float(np.clip(r.m * np.exp(rng.normal(0, 0.06)), 0.05, 0.45))
        r.s = float(np.clip(r.s * np.exp(rng.normal(0, 0.06)), 0.004, 0.08))
    elif k < 0.55:
        r.s = float(np.clip(r.s * np.exp(rng.normal(0, 0.08)), 0.004, 0.08))
    elif k < 0.75:
        i = int(rng.integers(len(r.b)))
        r.b[i] = float(np.clip(r.b[i] + rng.normal(0, 0.12), 0.05, 1))
    elif k < 0.85 and len(r.b) < 4:             # grow a new (weak) ring
        r.b.append(float(rng.uniform(0.05, 0.3)) if rng.random() < .5 else r.b[-1])
    elif k < 0.90 and len(r.b) > 1:
        r.b.pop(int(rng.integers(len(r.b))))
    elif k < 0.96:
        r.R = int(np.clip(r.R + rng.choice([-2, -1, 1, 2]), 8, 22))
    else:
        r.T = int(np.clip(r.T + rng.choice([-3, 3]), 2, 20))
    mx = max(r.b)
    r.b = [round(v / mx, 3) for v in r.b]
    r.m, r.s = round(r.m, 4), round(r.s, 4)
    return r


def perimeter_ratio(A: np.ndarray) -> float:
    """Isoperimetric ratio of the thresholded body: 1 = disc, larger = more intricate."""
    B = A > 0.2
    area = B.sum()
    if area < 5:
        return 0.0
    per = (B[:-1] != B[1:]).sum() + (B[:, :-1] != B[:, 1:]).sum()
    return float(per ** 2 / (4 * np.pi * area))


def evaluate(rule: Rule, cells: np.ndarray, grid=112, steps=360) -> dict:
    """Place a body, run it, measure survival, size, speed, pulsing and shape."""
    A = np.zeros((grid, grid))
    c = cells[:grid - 4, :grid - 4]
    y0, x0 = (grid - c.shape[0]) // 2, (grid - c.shape[1]) // 2
    A[y0:y0 + c.shape[0], x0:x0 + c.shape[1]] = c
    w = World(rule, (grid, grid), A)
    masses, cents = [], []
    for i in range(0, steps, 4):
        w.step(4)
        ms = w.mass()
        masses.append(ms)
        occ = (w.A > 0.1).mean()
        if ms < 5:
            return {"ok": False, "why": "died"}
        if occ > 0.16:
            return {"ok": False, "why": "exploded"}
        if i >= steps // 3:
            cents.append(w.centroid())
    masses = np.array(masses)
    tail = masses[len(masses) // 3:]
    if tail[-10:].mean() < 0.6 * tail[:10].mean() or tail[-10:].mean() > 1.6 * tail[:10].mean():
        return {"ok": False, "why": "drifting"}
    c = np.array(cents)
    d = np.diff(c, axis=0)
    d = (d + grid / 2) % grid - grid / 2
    speed = float(np.linalg.norm(d.sum(0)) / (len(d) * 4))
    path = float(np.linalg.norm(d, axis=1).sum() / (len(d) * 4))
    pulse = float(tail.std() / tail.mean())
    size = float(tail.mean() / rule.R ** 2)
    shape = perimeter_ratio(w.A)
    fitness = 3 * np.log1p(shape) + 8 * pulse + 3 * max(0.0, path - speed) + 4 * min(speed, 0.5)
    return {"ok": True, "rings": rule.b, "speed": speed, "size": size, "pulse": pulse, "shape": shape,
            "fitness": fitness, "cells": extract_creature(w.A)}


def extract_creature(A: np.ndarray, pad=4) -> np.ndarray:
    """Crop the heaviest single body (torus-safe). Replicators leave several; keep one."""
    from scipy import ndimage
    h, w = A.shape
    # roll the heaviest blob's peak to the centre so it can't straddle the border
    lab, n = ndimage.label(ndimage.binary_dilation(A > 0.02, iterations=2))
    if n == 0:
        return A
    masses = ndimage.sum(A, lab, range(1, n + 1))
    k = int(np.argmax(masses)) + 1
    py, px = np.unravel_index(np.argmax(np.where(lab == k, A, 0)), A.shape)
    A = np.roll(A, (h // 2 - py, w // 2 - px), (0, 1))
    lab, _ = ndimage.label(ndimage.binary_dilation(A > 0.02, iterations=2))
    keep = lab == lab[h // 2, w // 2]
    A = A * keep
    ys, xs = np.where(A > 0.01)
    y0, y1 = max(ys.min() - pad, 0), min(ys.max() + pad + 1, h)
    x0, x1 = max(xs.min() - pad, 0), min(xs.max() + pad + 1, w)
    return A[y0:y1, x0:x1]


def niche(res) -> tuple:
    sb = int(np.digitize(res["speed"], [0.02, 0.1, 0.25, 0.5, 0.8]))
    zb = int(np.digitize(res["size"], [0.25, 0.4, 0.6, 0.9, 1.4]))
    pb = int(res["pulse"] > 0.02)
    return (sb, zb, pb, len(res["rings"]))


def random_soup_rule(rng) -> Rule:
    """Multi-ring rules in the region where soups tend to condense into solitons."""
    B = int(rng.choice([2, 3]))
    b = list(np.round(rng.uniform(0.3, 1, B), 3)); b[int(rng.integers(B))] = 1.0
    m = float(rng.uniform(0.2, 0.36))
    s = float(m * rng.uniform(0.11, 0.18))
    return Rule("soup", R=int(rng.integers(12, 20)), T=int(rng.choice([2, 5, 10])),
                b=[float(v) for v in b], m=round(m, 4), s=round(s, 4))


def soup_discovery(rng, n_trials, grid=128):
    """Phase A: drop random soups into random multi-ring rules, harvest isolated blobs."""
    from scipy import ndimage
    parents = []
    for _ in range(n_trials):
        r = random_soup_rule(rng)
        w = World(r, (grid, grid), seed_soup((grid, grid), rng, 6, int(r.R * 2.2)))
        alive = True
        for _ in range(4):
            w.step(10 * r.T)
            if w.mass() < 5 or (w.A > 0.1).mean() > 0.12:
                alive = False
                break
        if not alive:
            continue
        lab, n = ndimage.label(ndimage.binary_dilation(w.A > 0.02, iterations=3))
        for sl in ndimage.find_objects(lab)[:4]:
            hh, ww = sl[0].stop - sl[0].start, sl[1].stop - sl[1].start
            if max(hh, ww) > grid // 2 or min(hh, ww) < r.R:
                continue
            cells = w.A[sl] * (lab[sl] > 0)
            res = evaluate(r, cells)
            if res["ok"]:
                parents.append((r, res))
                break
    return parents


def cmd_search(args):
    rng = np.random.default_rng(args.seed)
    orbium = KNOWN["orbium"]
    first = evaluate(orbium, np.array(ORBIUM))
    archive = {niche(first): (first["fitness"], orbium, first)}
    t0 = time.time()
    if args.soup:
        found = soup_discovery(rng, args.soup)
        for r, res in found:
            key = niche(res)
            if key not in archive or res["fitness"] > archive[key][0]:
                archive[key] = (res["fitness"], r, res)
        print(f"  soup phase: {len(found)} solitons from {args.soup} soups, "
              f"niches={len(archive)}  {time.time()-t0:.0f}s")
    stats = {}
    for i in range(args.n):
        keys = list(archive)
        _, prule, pres = archive[keys[int(rng.integers(len(keys)))]]
        child = prule
        for _ in range(int(rng.integers(1, 3))):
            child = mutate(child, rng)
        cells = resize_cells(pres["cells"], child.R / prule.R)
        cells = np.clip(cells + rng.normal(0, 0.02, cells.shape) * (cells > 0), 0, 1)
        res = evaluate(child, cells)
        stats[res.get("why", "ok")] = stats.get(res.get("why", "ok"), 0) + 1
        if res["ok"]:
            key = niche(res)
            if key not in archive or res["fitness"] > archive[key][0]:
                archive[key] = (res["fitness"], child, res)
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{args.n}  niches={len(archive)}  {stats}  {time.time()-t0:.0f}s")

    # pick the final zoo: best per niche, far enough from Orbium and each other
    # round-robin over speed classes so the zoo has both wanderers and sessile forms
    by_speed = {}
    for key, v in archive.items():
        by_speed.setdefault(key[0], []).append(v)
    queues = [sorted(v, key=lambda x: -x[0]) for _, v in sorted(by_speed.items(), reverse=True)]
    items = []
    while any(queues):
        for q in queues:
            if q:
                items.append(q.pop(0))
    kept = []
    for fit, rule, res in items:
        rd = lambda a, b: (abs(a.m - b.m) / .02 + abs(a.s - b.s) / .003
                           + abs(len(a.b) - len(b.b)) + abs(a.R - b.R) / 3)
        if rd(rule, orbium) < 3:          # just an Orbium variant
            continue
        if not all(rd(rule, k[1]) > 1.0 for k in kept):
            continue
        # long-run check on a bigger torus: must survive ~6x longer than in the search
        long = evaluate(rule, res["cells"], grid=176, steps=2000)
        if long["ok"]:
            kept.append((fit, rule, long))
        if len(kept) >= args.keep:
            break
    out = []
    for j, (fit, rule, res) in enumerate(kept):
        rule.name = f"{args.prefix}-{j+1:02d}"
        out.append({"rule": asdict(rule), "fitness": round(fit, 3),
                    **{k: round(res[k], 4) for k in ("speed", "size", "pulse", "shape")},
                    "cells": np.round(res["cells"], 3).tolist()})
        print(f"{rule.name}: fit={fit:.2f} speed={res['speed']:.3f} pulse={res['pulse']:.3f} "
              f"shape={res['shape']:.2f} R={rule.R} b={rule.b} m={rule.m} s={rule.s}")
    Path(args.out).write_text(json.dumps(out))
    print(f"saved {len(out)} species -> {args.out}")


def load_species(path) -> list[tuple[Rule, np.ndarray]]:
    data = json.loads(Path(path).read_text())
    return [(Rule(**d["rule"]), np.array(d["cells"])) for d in data]


# --------------------------------------------------------------------------
# E-ink rendering (800x480, 1-bit or 2-bit)
# --------------------------------------------------------------------------

W, H = 800, 480
FOOTER = 28


def upscale(A: np.ndarray, size) -> np.ndarray:
    im = Image.fromarray((A * 255).astype(np.uint8)).resize(size, Image.BICUBIC)
    return np.asarray(im, float) / 255


def contours(F: np.ndarray, levels=7) -> np.ndarray:
    """1-px iso-lines: pixels where the quantised level changes."""
    q = np.floor(F * levels * 0.999 + 0.35).astype(int)
    e = np.zeros_like(q, bool)
    e[:-1] |= q[:-1] != q[1:]
    e[:, :-1] |= q[:, :-1] != q[:, 1:]
    return e


def floyd(F: np.ndarray, levels=2) -> np.ndarray:
    """Floyd-Steinberg via PIL (fast). levels=2 -> 1-bit, 4 -> 2-bit."""
    im = Image.fromarray((np.clip(F, 0, 1) * 255).astype(np.uint8), "L")
    if levels == 2:
        return np.asarray(im.convert("1"), float)
    pal = Image.new("P", (1, 1))
    g = [int(255 * i / (levels - 1)) for i in range(levels)]
    pal.putpalette(sum(([v, v, v] for v in g), []) + [0] * (768 - 3 * levels))
    q = im.convert("RGB").quantize(palette=pal, dither=Image.Dither.FLOYDSTEINBERG)
    return np.asarray(q, float) / (levels - 1)


def render(A: np.ndarray, style="xray", ghosts=None, trail=None,
           label: str = "", levels=2) -> Image.Image:
    """
    Compose in greyscale, dither once at the end, draw crisp lines on top.

    style:
      ink      dithered density: dark creature on white paper
      contour  topographic iso-lines only (crispest on e-ink)
      xray     iso-lines over a light dithered body
      strobe   current body as iso-lines + past positions as dotted outlines
               (chronophotography: shows motion in a single still frame)
    ghosts: list of past fields (oldest first) for 'strobe'
    trail:  decayed max of past fields, drawn as a faint wake (ink / xray)
    """
    fh = H - FOOTER
    F = upscale(A, (W, fh))
    gray = np.ones_like(F)
    if trail is not None and style in ("ink", "xray"):
        gray -= 0.22 * np.clip(upscale(trail, (W, fh)) * 1.5, 0, 1)
    if style == "ink":
        gray -= 0.78 * F ** 0.8
    elif style == "xray":
        gray -= 0.45 * np.clip(F * 1.4, 0, 1)
    img = floyd(np.clip(gray, 0, 1), levels)

    lines = np.zeros_like(F, bool)
    if style in ("contour", "xray"):
        lines |= contours(F, 8 if style == "contour" else 6)
    if style == "strobe":
        lines |= contours(F, 6)
        yy, xx = np.mgrid[:fh, :W]
        for k, G in enumerate(ghosts or []):
            edge = contours(np.clip(upscale(G, (W, fh)) * 4, 0, 1.5), 1)
            period = 2 + (len(ghosts) - k)            # older = sparser dots
            lines |= edge & (((xx + yy) % period) == 0)
    img = np.where(lines, 0.0, img)

    canvas = Image.new("L", (W, H), 255)
    canvas.paste(Image.fromarray((img * 255).astype(np.uint8)), (0, 0))
    d = ImageDraw.Draw(canvas)
    d.line([(0, fh), (W, fh)], fill=0, width=1)
    try:
        font = ImageFont.truetype("DejaVuSansMono.ttf", 14)
    except OSError:
        font = ImageFont.load_default()
    d.text((10, fh + 6), label, fill=0, font=font)
    if levels == 2:
        return canvas.convert("1", dither=Image.Dither.NONE)
    return canvas


# --------------------------------------------------------------------------
# Examples
# --------------------------------------------------------------------------

def place(world_shape, cells, rng, n=1, rotate=True):
    """Stamp n copies, spread across the width so they don't start overlapping."""
    A = np.zeros(world_shape)
    h, w = world_shape
    for k in range(n):
        c = np.rot90(cells, int(rng.integers(4))) if rotate else cells
        x = int((k + 0.5) * w / n - c.shape[1] / 2 + rng.integers(-w // (6 * n) - 1, w // (6 * n) + 1))
        y = int(rng.integers(h))
        ys = (np.arange(c.shape[0]) + y) % h
        xs = (np.arange(c.shape[1]) + x) % w
        A[np.ix_(ys, xs)] = np.maximum(A[np.ix_(ys, xs)], c)
    return A


def advance(world: World, steps: int, n_ghosts=4, trail=None, decay=0.93):
    """Advance `steps`, returning evenly spaced snapshots (ghosts) and a decayed wake."""
    trail = np.zeros_like(world.A) if trail is None else trail
    ghosts = []
    chunk = max(1, steps // (n_ghosts + 1))
    done = 0
    while done < steps:
        k = min(chunk, steps - done)
        while k > 0:
            s = min(5, k)
            world.step(s)
            trail = np.maximum(trail * decay ** (s / 5), world.A)
            k -= s
            done += s
        if done < steps:
            ghosts.append(world.A.copy())
    return ghosts[-n_ghosts:], trail


def label_for(rule: Rule, t) -> str:
    return f"{rule.name}   R={rule.R} T={rule.T} b={rule.b} m={rule.m} s={rule.s}   t={t:.0f}"


def make_overview(species, path, title="Lenia creatures: Orbium reference + originals from rule-space search",
                  cols=6):
    """Science sheet: each species centred on a torus, time slices + decayed wake."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    n = len(species)
    fig, axes = plt.subplots(n, cols, figsize=(1.9 * cols, 2.0 * n), squeeze=False)
    for i, (rule, cells, kind) in enumerate(species):
        g = 128
        A0 = np.zeros((g, g))
        c = cells[:g, :g]
        y0, x0 = (g - c.shape[0]) // 2, (g - c.shape[1]) // 2
        A0[y0:y0 + c.shape[0], x0:x0 + c.shape[1]] = c
        wd = World(rule, (g, g), A0)
        trail = np.zeros_like(wd.A)
        for j in range(cols - 1):
            axes[i, j].imshow(wd.A, cmap="bone_r", vmin=0, vmax=1)
            axes[i, j].set_title(f"t={wd.t * rule.dt:.0f}", fontsize=7)
            _, trail = advance(wd, max(20, 8 * rule.T), trail=trail, decay=0.9)
        axes[i, -1].imshow(trail, cmap="magma")
        axes[i, -1].set_title("wake", fontsize=7)
        axes[i, 0].set_ylabel(f"{rule.name}\n{kind}", fontsize=8)
        for ax in axes[i]:
            ax.set_xticks([]); ax.set_yticks([])
    fig.suptitle(title, y=1.0)
    fig.tight_layout()
    fig.savefig(path, dpi=90, bbox_inches="tight")
    plt.close(fig)
    print("wrote", path)


def cmd_overview(args):
    species = [(r, c, "") for r, c in load_species(args.species)]
    if args.names:
        keep = args.names.split(",")
        species = sorted([s for s in species if s[0].name in keep], key=lambda s: keep.index(s[0].name))
    if args.reference:
        species.insert(0, (KNOWN["orbium"], np.array(ORBIUM), "reference"))
    make_overview(species, args.out, args.title)


def cmd_examples(args):

    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    wshape = ((H - FOOTER) // args.scale, W // args.scale)

    species = [(KNOWN["orbium"], np.array(ORBIUM), "reference")]
    if args.species and Path(args.species).exists():
        for rule, cells in load_species(args.species)[: args.max_species]:
            species.append((rule, cells, "original"))

    make_overview(species, out / "overview.png")

    # 2) one TRMNL frame per species (strobe: motion visible in a still)
    for rule, cells, kind in species:
        wd = World(rule, wshape, place(wshape, cells, rng, n=args.count))
        advance(wd, 20 * rule.T)                      # settle
        ghosts, trail = advance(wd, args.steps)
        style = args.style
        render(wd.A, style, ghosts, trail, label_for(rule, wd.t * rule.dt)).save(
            out / f"trmnl_{rule.name.lower()}_{style}.png")
        print("wrote", out / f"trmnl_{rule.name.lower()}_{style}.png")

    # 3) style comparison on one creature
    rule, cells, _ = species[min(args.showcase, len(species) - 1)]
    wd = World(rule, wshape, place(wshape, cells, rng, n=args.count))
    advance(wd, 20 * rule.T)
    ghosts, trail = advance(wd, args.steps)
    for style in ("ink", "contour", "xray", "strobe"):
        render(wd.A, style, ghosts, trail, label_for(rule, wd.t * rule.dt) + f"   [{style}]").save(
            out / f"style_{style}.png")

    # 4) full-screen soup of Hydrogeminium natans
    hg = KNOWN["hydrogeminium"]
    wd = World(hg, wshape, seed_soup(wshape, rng, 6, int(hg.R * 2.2)))
    advance(wd, 60)
    ghosts, trail = advance(wd, 40)
    render(wd.A, "ink", ghosts, trail, label_for(hg, wd.t * hg.dt)).save(out / "trmnl_hydrogeminium_ink.png")

    # 5) animated preview of what the display would show over ~1 hour (12 refreshes)
    if args.gif:
        rule, cells, _ = species[min(args.showcase, len(species) - 1)]
        wd = World(rule, wshape, place(wshape, cells, rng, n=args.count))
        advance(wd, 20 * rule.T)
        frames = []
        for _ in range(12):
            ghosts, _ = advance(wd, args.steps)
            frames.append(render(wd.A, "strobe", ghosts, None,
                                 label_for(rule, wd.t * rule.dt)).convert("L"))
        frames[0].save(out / "display_preview.gif", save_all=True, append_images=frames[1:],
                       duration=700, loop=0)
        print("wrote", out / "display_preview.gif")


# --------------------------------------------------------------------------
# Display loop (persistent world)
# --------------------------------------------------------------------------

def zoo(species_path) -> list[tuple[Rule, np.ndarray | None]]:
    """Display rotation: Orbium, every discovered species, Hydrogeminium soup."""
    z = [(KNOWN["orbium"], np.array(ORBIUM))]
    if species_path and Path(species_path).exists():
        z += load_species(species_path)
    z.append((KNOWN["hydrogeminium"], None))           # None = start from soup
    return z


def populate(rule, cells, shape, rng, count):
    if cells is None:
        return seed_soup(shape, rng, 6, int(rule.R * 2.2))
    return place(shape, cells, rng, n=count)


class Display:
    """The display loop: one world, advanced frame by frame, rotating through the zoo."""

    def __init__(self, species_path, shape, count=3, steps=40, style="auto", levels=2,
                 epoch=360, max_occ=0.45, start=0, seed=None):
        self.zoo = zoo(species_path)
        self.shape, self.count, self.steps = shape, count, steps
        self.style, self.levels, self.epoch_len, self.max_occ = style, levels, epoch, max_occ
        self.rng = np.random.default_rng(seed)
        self.idx = start % len(self.zoo)
        self._new_world()

    def _new_world(self):
        rule, cells = self.zoo[self.idx]
        self.wd = World(rule, self.shape, populate(rule, cells, self.shape, self.rng, self.count))
        self.trail = np.zeros(self.shape)
        self.epoch, self.crowded = 0, 0

    def frame(self, clock: str = "") -> tuple[Image.Image, dict]:
        ghosts, self.trail = advance(self.wd, self.steps, trail=self.trail)
        self.epoch += 1
        occ = float((self.wd.A > 0.1).mean())
        self.crowded = self.crowded + 1 if occ > self.max_occ else 0
        # epoch over: extinction, overgrown for a while, or time's up -> next species
        if self.wd.mass() < 1 or self.crowded >= 3 or self.epoch >= self.epoch_len:
            self.idx = (self.idx + 1) % len(self.zoo)
            self._new_world()
            ghosts, self.trail = advance(self.wd, self.steps)
            occ = float((self.wd.A > 0.1).mean())
        style = self.style
        if style == "auto":            # strobe while sparse, contours once crowded
            style = "strobe" if occ < 0.15 else "contour"
        r = self.wd.rule
        lab = f"{r.name}   t={self.wd.t * r.dt:.0f}" + (f"   {clock}" if clock else "")
        img = render(self.wd.A, style, ghosts, self.trail, lab, self.levels)
        return img, {"species": r.name, "occ": round(occ, 3), "style": style}

    # persistence for the cron/tick workflow
    def save(self, path):
        np.savez_compressed(path, A=self.wd.A, trail=self.trail, t=self.wd.t,
                            rule=json.dumps(asdict(self.wd.rule)), idx=self.idx,
                            epoch=self.epoch, crowded=self.crowded)

    def load(self, path):
        z = np.load(path)
        rule = Rule(**json.loads(str(z["rule"])))
        self.wd = World(rule, z["A"].shape, z["A"])
        self.wd.t = int(z["t"])
        self.trail, self.idx = z["trail"], int(z["idx"])
        self.epoch, self.crowded = int(z["epoch"]), int(z["crowded"])
        self.shape = self.wd.shape


def cmd_gifs(args):
    """One animated GIF per species: what the display shows over n refreshes."""
    out = Path(args.outdir)
    out.mkdir(parents=True, exist_ok=True)
    rng = np.random.default_rng(args.seed)
    wshape = world_shape(args.scale)
    species = load_species(args.species)
    if args.names:
        keep = set(args.names.split(","))
        species = [s for s in species if s[0].name in keep]
    for rule, cells in species:
        t0 = time.time()
        wd = World(rule, wshape, place(wshape, cells, rng, n=args.count))
        advance(wd, 10 * rule.T)                          # let bodies settle
        trail = None
        frames = []
        for _ in range(args.frames):
            ghosts, trail = advance(wd, args.steps, trail=trail)
            occ = float((wd.A > 0.1).mean())
            style = args.style if args.style != "auto" else ("strobe" if occ < 0.15 else "contour")
            lab = label_for(rule, wd.t * rule.dt)
            A = wd.A
            if args.follow:                     # camera keeps the creature centred
                cy, cx = wd.centroid()
                sh = (int(wd.shape[0] / 2 - cy), int(wd.shape[1] / 2 - cx))
                A = np.roll(A, sh, (0, 1))
                ghosts = [np.roll(G, sh, (0, 1)) for G in ghosts]
                trail_v = np.roll(trail, sh, (0, 1))
            else:
                trail_v = trail
            frames.append(render(A, style, ghosts, trail_v, lab).convert("L"))
            if wd.mass() < 1:
                break
        path = out / f"{rule.name.lower()}.gif"
        frames[0].save(path, save_all=True, append_images=frames[1:], duration=args.ms, loop=0,
                       optimize=True)
        print(f"wrote {path}  {len(frames)} frames  {path.stat().st_size // 1024} KB  "
              f"{time.time() - t0:.0f}s")


def world_shape(scale):
    return ((H - FOOTER) // scale, W // scale)


def cmd_init(args):
    d = Display(args.species, world_shape(args.scale), args.count, start=args.start, seed=args.seed)
    d.save(args.state)
    print(f"initialised {d.wd.rule.name} on {d.shape} ({len(d.zoo)} species in rotation) -> {args.state}")


def cmd_tick(args):
    d = Display(args.species, world_shape(3), args.count, args.steps, args.style, args.levels,
                args.epoch, args.max_occ)
    d.load(args.state)
    img, meta = d.frame(time.strftime("%d.%m. %H:%M"))
    d.save(args.state)
    img.save(args.png)
    print(f"wrote {args.png}  {meta}")
    if args.push:
        import requests
        with open(args.png, "rb") as f:
            r = requests.post(args.push, data=f.read(),
                              headers={"Content-Type": "image/png"}, timeout=30)
        print("TRMNL:", r.status_code, r.text[:200])


def cmd_render_day(args):
    """Pre-render a loop of frames for static hosting (GitHub Pages + Redirect plugin)."""
    import datetime as dt
    now = dt.datetime.now(dt.timezone.utc)
    build = args.build or now.strftime("%Y%m%d-%H%M")
    seed = args.seed if args.seed is not None else int(now.strftime("%Y%m%d"))
    d = Display(args.species, world_shape(args.scale), args.count, args.steps, args.style,
                args.levels, args.epoch, args.max_occ, start=args.start if args.start >= 0 else seed,
                seed=seed)
    out = Path(args.outdir)
    fdir = out / "frames" / build
    fdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    frames = []
    for i in range(args.n):
        img, meta = d.frame()
        img.save(fdir / f"{i:04d}.png", optimize=True)
        frames.append(meta["species"])
        if (i + 1) % 100 == 0:
            print(f"  {i+1}/{args.n}  {meta}  {time.time()-t0:.0f}s")
    manifest = {
        "build": build,
        "n": args.n,
        "interval": args.interval,
        "start": int(now.timestamp()),      # frame 0 is shown at this unix time
        "path": f"frames/{build}",
        "species": sorted(set(frames)),
    }
    (out / "manifest.json").write_text(json.dumps(manifest, indent=1))
    (out / "index.html").write_text(
        f"<!doctype html><meta charset=utf-8><title>lenia-trmnl</title>"
        f"<body style='font-family:monospace'><h3>build {build}</h3>"
        f"<p>{args.n} frames, species: {', '.join(manifest['species'])}</p>"
        f"<img src='frames/{build}/0000.png'> <img src='frames/{build}/{args.n // 2:04d}.png'>")
    print(f"wrote {args.n} frames to {fdir} and manifest.json in {time.time()-t0:.0f}s")


def main():
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search"); s.set_defaults(fn=cmd_search)
    s.add_argument("--n", type=int, default=300)
    s.add_argument("--keep", type=int, default=6)
    s.add_argument("--seed", type=int, default=0)
    s.add_argument("--out", default="species.json")
    s.add_argument("--soup", type=int, default=300, help="random multi-ring soups to harvest first")
    s.add_argument("--prefix", default="Sono", help="name prefix for discovered species")

    e = sub.add_parser("examples"); e.set_defaults(fn=cmd_examples)
    e.add_argument("--species", default="species.json")
    e.add_argument("--max-species", type=int, default=4)
    e.add_argument("--outdir", default="examples")
    e.add_argument("--scale", type=int, default=3, help="screen pixels per cell")
    e.add_argument("--count", type=int, default=3, help="creatures per screen")
    e.add_argument("--steps", type=int, default=120, help="sim steps between refreshes")
    e.add_argument("--style", default="strobe", choices=["ink", "contour", "xray", "strobe"])
    e.add_argument("--showcase", type=int, default=1, help="species index for style sheet / gif")
    e.add_argument("--gif", action="store_true")
    e.add_argument("--seed", type=int, default=1)

    i = sub.add_parser("init"); i.set_defaults(fn=cmd_init)
    i.add_argument("--start", type=int, default=0, help="species index in the rotation (0 = Orbium)")
    i.add_argument("--species", default="species.json")
    i.add_argument("--state", default="world.npz")
    i.add_argument("--scale", type=int, default=3)
    i.add_argument("--count", type=int, default=3)
    i.add_argument("--seed", type=int, default=0)

    rd = sub.add_parser("render-day", help="pre-render a frame loop for static hosting")
    rd.set_defaults(fn=cmd_render_day)
    rd.add_argument("--n", type=int, default=1440, help="frames in the loop (1440 = 1/min for 24 h)")
    rd.add_argument("--interval", type=int, default=60, help="seconds per frame (Redirect minimum is 60)")
    rd.add_argument("--steps", type=int, default=40, help="sim steps per frame")
    rd.add_argument("--epoch", type=int, default=360, help="frames per species before rotating")
    rd.add_argument("--max-occ", type=float, default=0.45)
    rd.add_argument("--style", default="auto", choices=["auto", "ink", "contour", "xray", "strobe"])
    rd.add_argument("--levels", type=int, default=2, choices=[2, 4])
    rd.add_argument("--scale", type=int, default=3)
    rd.add_argument("--count", type=int, default=3)
    rd.add_argument("--start", type=int, default=-1, help="first species index (-1 = rotate by date)")
    rd.add_argument("--seed", type=int, default=None)
    rd.add_argument("--build", default=None)
    rd.add_argument("--species", default="species.json")
    rd.add_argument("--outdir", default="site")

    o = sub.add_parser("overview", help="science sheet of species over time")
    o.set_defaults(fn=cmd_overview)
    o.add_argument("--species", default="species.json")
    o.add_argument("--names", default="")
    o.add_argument("--out", default="examples/overview.png")
    o.add_argument("--title", default="Lenia species")
    o.add_argument("--reference", action="store_true", help="prepend Orbium")

    g = sub.add_parser("gifs", help="one animated preview GIF per species")
    g.set_defaults(fn=cmd_gifs)
    g.add_argument("--species", default="species.json")
    g.add_argument("--names", default="", help="comma-separated subset")
    g.add_argument("--outdir", default="examples/gifs")
    g.add_argument("--frames", type=int, default=24)
    g.add_argument("--steps", type=int, default=40, help="sim steps per frame (= per display refresh)")
    g.add_argument("--ms", type=int, default=350, help="GIF frame duration")
    g.add_argument("--style", default="auto", choices=["auto", "ink", "contour", "xray", "strobe"])
    g.add_argument("--scale", type=int, default=3)
    g.add_argument("--count", type=int, default=3)
    g.add_argument("--follow", action="store_true", help="camera tracks the creature (use with --count 1)")
    g.add_argument("--seed", type=int, default=3)

    t = sub.add_parser("tick"); t.set_defaults(fn=cmd_tick)
    t.add_argument("--state", default="world.npz")
    t.add_argument("--steps", type=int, default=120, help="sim steps between screen updates")
    t.add_argument("--species", default="species.json")
    t.add_argument("--count", type=int, default=3)
    t.add_argument("--style", default="auto", choices=["auto", "ink", "contour", "xray", "strobe"])
    t.add_argument("--epoch", type=int, default=72, help="refreshes per species (72 x 5 min = 6 h)")
    t.add_argument("--max-occ", type=float, default=0.45, help="overgrowth threshold")
    t.add_argument("--levels", type=int, default=2, choices=[2, 4])
    t.add_argument("--png", default="trmnl.png")
    t.add_argument("--push", default=None, help="TRMNL Webhook Image URL")

    a = p.parse_args()
    a.fn(a)


if __name__ == "__main__":
    main()
