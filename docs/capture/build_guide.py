"""Build "Setup Guide.html" (one self-contained file: images and video inlined) from docs/src/guide.html.

    .venv\\Scripts\\python.exe docs\\capture\\build_guide.py
"""
import base64
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shoot  # noqa: E402

SRC = shoot.DOCS / "src" / "guide.html"
OUT = shoot.VA / "Setup Guide.html"
TYPES = {".png": "image/png", ".mp4": "video/mp4", ".jpg": "image/jpeg"}


def data_uri(rel: str) -> str:
    p = (SRC.parent / rel).resolve()
    return f"data:{TYPES[p.suffix]};base64," + base64.b64encode(p.read_bytes()).decode()


def main():
    frames = shoot.storage.CACHE / "video_frames"
    poster = shoot.IMG / "poster.png"
    if (frames / "title_000.png").exists():
        poster.write_bytes((frames / "title_000.png").read_bytes())
    html = SRC.read_text(encoding="utf-8")
    html = re.sub(r'(src|poster)="(\.\./[^"]+\.(?:png|mp4|jpg))"', lambda m: f'{m[1]}="{data_uri(m[2])}"', html)
    html = re.sub(r"<!-- Source for (Setup Guide|SETUP).html.*?-->\n", "", html, flags=re.S)
    OUT.write_text(html, encoding="utf-8")
    left = re.findall(r'(?:src|poster)="\.\./', html)
    print(f"ok {OUT.name}  {OUT.stat().st_size / 1e6:.1f} MB  (unresolved refs: {len(left)})")


if __name__ == "__main__":
    main()
