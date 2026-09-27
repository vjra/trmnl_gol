import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import lenia_trmnl as L  # noqa: E402


def test_orbium_glides_and_keeps_its_mass():
    A = np.zeros((96, 96))
    A[30:50, 30:50] = np.array(L.ORBIUM)
    w = L.World(L.KNOWN["orbium"], (96, 96), A)
    w.step(50)
    m0, c0 = w.mass(), w.centroid()
    w.step(300)
    assert abs(w.mass() - m0) / m0 < 0.1
    assert np.hypot(c0[0] - w.centroid()[0], c0[1] - w.centroid()[1]) > 5


def test_species_file_loads_and_every_species_survives_briefly():
    for rule, cells in L.load_species(ROOT / "species.json"):
        res = L.evaluate(rule, cells, grid=112, steps=200)
        assert res["ok"], f"{rule.name}: {res.get('why')}"


def test_render_is_trmnl_format():
    A = np.random.default_rng(0).random((150, 266)) * 0.5
    for style in ("ink", "contour", "xray", "strobe"):
        img = L.render(A, style, ghosts=[A], trail=A, label="test")
        assert img.size == (800, 480) and img.mode == "1"


def test_render_day_writes_frames_and_manifest(tmp_path):
    out = tmp_path / "site"
    subprocess.run([sys.executable, str(ROOT / "lenia_trmnl.py"), "render-day", "--n", "3",
                    "--steps", "10", "--species", str(ROOT / "species.json"),
                    "--outdir", str(out), "--build", "test"], check=True)
    m = json.loads((out / "manifest.json").read_text())
    assert m["n"] == 3 and m["path"] == "frames/test" and m["interval"] >= 60
    frames = sorted((out / "frames" / "test").glob("*.png"))
    assert [f.name for f in frames] == ["0000.png", "0001.png", "0002.png"]
    im = Image.open(frames[0])
    assert im.size == (800, 480) and im.mode == "1"
    assert frames[0].stat().st_size < 90_000   # firmware rejects large images
