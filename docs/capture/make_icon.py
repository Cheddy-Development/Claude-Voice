"""Render docs/src/icon.html into claude_voice.ico (16-256 px) and docs/img/icon.png."""
import struct
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shoot  # noqa: E402

shoot.storage.apply_env()
shoot.TRANSPARENT = True
raw = shoot.IMG / "_icon_raw.png"
shoot._shoot((shoot.DOCS / "src" / "icon.html").as_uri(), raw, 516, 516, 500, 1)
import av  # noqa: E402
with av.open(str(raw)) as c:
    rgba = next(c.decode(video=0)).to_ndarray(format="rgba")
raw.unlink()
img = rgba[2:514, 2:514].astype(np.float32)  # the 512 px svg


def resize(a, n):  # area-average downscale with premultiplied alpha
    f = a.shape[0] // n
    a = a[: n * f, : n * f]
    al = a[..., 3:4] / 255.0
    pm = np.concatenate([a[..., :3] * al, a[..., 3:4]], -1)
    pm = pm.reshape(n, f, n, f, 4).mean((1, 3))
    al2 = pm[..., 3:4] / 255.0
    rgb = np.where(al2 > 0, pm[..., :3] / np.maximum(al2, 1e-6), 0)
    return np.concatenate([rgb, pm[..., 3:4]], -1).clip(0, 255).astype(np.uint8)


def png_bytes(a):
    import zlib
    h, w, _ = a.shape
    raw = b"".join(bytes([0]) + a[y].tobytes() for y in range(h))
    def chunk(t, d):
        return struct.pack(">I", len(d)) + t + d + struct.pack(">I", zlib.crc32(t + d) & 0xFFFFFFFF)
    return (shoot.PNG_SIG + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(raw, 9)) + chunk(b"IEND", b""))


sizes = [256, 128, 64, 48, 32, 16]
pngs = [png_bytes(resize(img, s)) for s in sizes]
head = struct.pack("<HHH", 0, 1, len(sizes))
off = 6 + 16 * len(sizes)
dirs = b""
for s, p in zip(sizes, pngs):
    dirs += struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(p), off)
    off += len(p)
(shoot.VA / "claude_voice.ico").write_bytes(head + dirs + b"".join(pngs))
(shoot.IMG / "icon.png").write_bytes(png_bytes(resize(img, 256)))
print("ok claude_voice.ico + docs/img/icon.png")
