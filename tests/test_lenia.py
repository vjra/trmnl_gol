import contextlib
import functools
import http.server
import json
import subprocess
import sys
import threading
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


@contextlib.contextmanager
def serve(root: Path):
    """Static HTTP server on a free localhost port, standing in for the live Pages site."""
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *a):
            pass
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), functools.partial(Quiet, directory=str(root)))
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}/"
    finally:
        srv.shutdown()
        srv.server_close()


def fake_site(root: Path, build="old", n=3, path=None):
    (root / "frames" / build).mkdir(parents=True)
    for i in range(n):
        Image.new("1", (8, 8), i % 2).save(root / "frames" / build / f"{i:04d}.png")
    (root / "manifest.json").write_text(json.dumps(
        {"build": build, "n": n, "interval": 60, "start": 0, "path": path or f"frames/{build}"}))


def test_render_day_keeps_previous_build_frames(tmp_path):
    live, out = tmp_path / "live", tmp_path / "site"
    fake_site(live)
    with serve(live) as url:
        subprocess.run([sys.executable, str(ROOT / "lenia_trmnl.py"), "render-day", "--n", "2",
                        "--steps", "5", "--species", str(ROOT / "species.json"), "--outdir", str(out),
                        "--build", "new", "--keep-previous", url], check=True)
    m = json.loads((out / "manifest.json").read_text())
    assert m["build"] == "new" and m["previous"] == "old"
    for i in range(3):
        name = f"frames/old/{i:04d}.png"
        assert (out / name).read_bytes() == (live / name).read_bytes()
    assert len(list((out / "frames" / "new").glob("*.png"))) == 2


def test_keep_previous_skips_same_build_bad_manifests_and_dead_sites(tmp_path):
    live = tmp_path / "live"
    fake_site(live, build="same")
    with serve(live) as url:
        assert L.keep_previous(url, tmp_path / "a", "same") is None          # nothing to carry
    for bad in ("../../escape", "frames/../../escape", "/abs", "frames/a/b", "other/x"):
        root = tmp_path / f"bad{abs(hash(bad))}"
        fake_site(root, build="x", path=bad)
        with serve(root) as url:
            assert L.keep_previous(url, tmp_path / "b", "new") is None, bad
    assert not (tmp_path / "b").exists() and not (tmp_path / "escape").exists()
    assert L.keep_previous("http://127.0.0.1:9", tmp_path / "c", "new") is None   # nothing listening
