"""Render the guide's screenshots and video frames with headless Edge (no bridge, mic or sound needed).

    .venv\\Scripts\\python.exe docs\\capture\\shoot.py window      # docs/img/window-*.png (real ui.html, scripted states)
    .venv\\Scripts\\python.exe docs\\capture\\shoot.py page <file.html> <out.png> <w> <h> [budget_ms]

Edge's profile and temp files go to the cache folder, never C:.
"""
import os
import struct
import subprocess
import sys
import time
import zlib
from pathlib import Path

CAP = Path(__file__).resolve().parent
DOCS = CAP.parent
VA = DOCS.parent
IMG = DOCS / "img"
sys.path.insert(0, str(VA))
import storage  # noqa: E402

EDGE = Path(r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe")
PROFILE = storage.CACHE / "edge-shots"
SCENES = ["asleep", "listening", "hearing", "working", "speaking", "settings", "lite"]
TRANSPARENT = False
MIN_W = 516  # headless Edge won't size a window narrower; a smaller width just crops the page
PNG_SIG = bytes([0x89, 0x50, 0x4E, 0x47, 0x0D, 0x0A, 0x1A, 0x0A])


def build_window_page() -> Path:
    """ui.html with scenes.js injected before its own script."""
    html = (VA / "ui.html").read_text(encoding="utf-8")
    inj = (CAP / "scenes.js").read_text(encoding="utf-8")
    out = CAP / "_window.html"
    out.write_text(html.replace("<script>", "<script>\n" + inj + "\n</script>\n<script>", 1), encoding="utf-8")
    return out


def read_png(path: Path):
    import av
    with av.open(str(path)) as c:
        return next(c.decode(video=0)).to_ndarray(format="rgb24")


def write_png(path: Path, rgb):
    h, w, _ = rgb.shape
    raw = b"".join(bytes([0]) + rgb[y].tobytes() for y in range(h))

    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    path.write_bytes(PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0))
                     + chunk(b"IDAT", zlib.compress(raw, 6)) + chunk(b"IEND", b""))


def shoot(url: str, out: Path, w: int, h: int, budget: int = 2500, scale: int = 2):
    """Screenshot `url` at w x h CSS pixels, saved at `scale`x. Headless Edge windows are at least 516 wide."""
    return _shoot(url, out, max(w, MIN_W), h, budget, scale)


def _shoot(url: str, out: Path, w: int, h: int, budget: int, scale: int):
    out.parent.mkdir(parents=True, exist_ok=True)
    if out.exists():
        out.unlink()
    cmd = [str(EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--disable-extensions", "--disable-sync", f"--user-data-dir={PROFILE}",
           f"--window-size={w},{h}", f"--force-device-scale-factor={scale}",
           f"--virtual-time-budget={budget}", f"--screenshot={out}", url]
    if TRANSPARENT:
        cmd.insert(1, "--default-background-color=00000000")
    subprocess.run(cmd, capture_output=True, timeout=60, env=dict(os.environ))
    # msedge.exe hands off to a background process and returns early: wait for the file to settle
    t0, last = time.time(), -1
    while time.time() - t0 < 60:
        size = out.stat().st_size if out.exists() else -1
        if size > 0 and size == last:
            return out
        last = size
        time.sleep(0.4)
    raise SystemExit(f"screenshot failed: {out}")


def main():
    storage.apply_env()
    what = sys.argv[1] if len(sys.argv) > 1 else "window"
    if what == "window":
        page = build_window_page().as_uri()
        for s in SCENES:
            p = shoot(f"{page}#{s}", IMG / f"window-{s}.png", 516, 800)
            print("ok", p.name)
    elif what == "page":
        src, out, w, h = sys.argv[2], sys.argv[3], int(sys.argv[4]), int(sys.argv[5])
        budget = int(sys.argv[6]) if len(sys.argv) > 6 else 1500
        print("ok", shoot(Path(src).resolve().as_uri(), Path(out).resolve(), w, h, budget, scale=1).name)


if __name__ == "__main__":
    main()
