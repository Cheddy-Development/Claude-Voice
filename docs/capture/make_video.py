"""Build docs/claude_voice_setup.mp4: narrated install + first-run walkthrough (1280x720, 30 fps).

    .venv\\Scripts\\python.exe docs\\capture\\make_video.py

Slides are docs/src/video.html#<scene>, rendered by headless Edge. Animated scenes render several frames at
increasing virtual time so the orb moves. The narration is the bridge's own Kokoro voice (am_michael).
Everything is made locally from what's already installed: Edge, Kokoro and PyAV (H.264 + AAC). Nothing downloads.
"""
import shutil
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import shoot  # noqa: E402

FPS, W, H, SR = 30, 1280, 720, 24000
ANIM_FPS = 10         # rendered frames per second for animated scenes (blended up to 30)
XFADE = 0.3           # seconds of crossfade between scenes
SCALE = 2             # frames render at 2x so zooms stay sharp
SPEED = 1.15          # narration speed (1.0 = Kokoro default)
ZOOM = False          # camera moves (FOCUS): off, the steady version reads better
OUT = shoot.DOCS / "claude_voice_setup.mp4"
FRAMES = shoot.storage.CACHE / "video_frames_2x"

# scene id (in video.html), animated?, narration
SCENES = [
    ("title", True, "This is Claude Voice. It lets you talk to Claude Code out loud, and hear it answer, "
                    "while you keep working."),
    ("folder", False, "First, put the Claude Voice folder on a drive other than C. For example, D, Tools, "
                      "Claude Voice. Then double click setup voice dot bat."),
    ("storage", False, "Setup asks where to keep the models and the cache. Just press Enter for the defaults, "
                       "or type a folder on another drive. Never use C."),
    ("packages", False, "Next it installs what it needs. Every step shows a progress bar and the time so far. "
                        "This usually takes three to ten minutes."),
    ("done", False, "Press Enter to download the realistic voice and the speech model. When you see one hundred "
                    "percent, done, setup is finished."),
    ("desktop", False, "You now have a Claude Voice shortcut on your desktop."),
    ("chat", False, "To start, type open voice in any Claude Code session. The window opens and links to that "
                    "session."),
    ("asleep", True, "The orb shows what it's doing. Grey and still means asleep, so it ignores what you say."),
    ("listening", True, "Say, let's talk. The orb turns teal. It's listening."),
    ("hearing", True, "Now just ask. For example, what does the sales report folder have in it?"),
    ("working", True, "Purple means Claude is working on it, right in your session."),
    ("speaking", True, "Amber means it's answering out loud. Say stop to cut it off, or cancel task to drop "
                       "the request."),
    ("ending", True, "When you're done, say, okay, let's end. It stops listening until you say let's talk again."),
    ("settings", False, "The gear lets you change the voice, the speed, and the speech model. "
                        "The Microsoft voice is lighter on your computer."),
    ("outro", True, "That's it. Type open voice, and start talking."),
]


# Camera moves per scene: keyframes (fraction of the scene, centre x, centre y, zoom), in 1280x720 slide pixels.
# Starts wide so the caption is readable, then eases in on where the action is.
WIDE = (640, 360, 1.0)
FOCUS = {
    "title":     [(0, *WIDE), (1, 640, 360, 1.08)],
    "folder":    [(0, *WIDE), (0.25, *WIDE), (0.7, 900, 410, 1.75), (1, 900, 410, 1.8)],
    "storage":   [(0, *WIDE), (0.2, *WIDE), (0.55, 780, 290, 1.9), (1, 790, 300, 1.95)],
    "packages":  [(0, *WIDE), (0.15, *WIDE), (0.4, 800, 205, 1.8), (0.65, 820, 375, 1.8), (1, 830, 380, 1.85)],
    "done":      [(0, *WIDE), (0.15, *WIDE), (0.4, 790, 260, 1.7), (0.7, 760, 470, 1.8), (1, 760, 475, 1.85)],
    "desktop":   [(0, *WIDE), (0.2, *WIDE), (0.7, 660, 370, 2.1), (1, 660, 370, 2.2)],
    "chat":      [(0, *WIDE), (0.15, *WIDE), (0.45, 1080, 250, 1.9), (0.8, 860, 300, 1.6), (1, 860, 300, 1.6)],
    "asleep":    [(0, *WIDE), (0.25, *WIDE), (0.8, 910, 225, 1.6), (1, 910, 225, 1.65)],
    "listening": [(0, 910, 300, 1.25), (0.6, 910, 225, 1.75), (1, 910, 225, 1.8)],
    "hearing":   [(0, 910, 225, 1.4), (0.45, 910, 500, 1.8), (1, 910, 505, 1.85)],
    "working":   [(0, 910, 330, 1.3), (0.5, 910, 225, 1.7), (1, 910, 540, 1.7)],
    "speaking":  [(0, 910, 225, 1.5), (0.4, 910, 225, 1.6), (0.75, 910, 595, 1.85), (1, 910, 595, 1.9)],
    "ending":    [(0, 910, 360, 1.2), (1, 910, 225, 1.5)],
    "settings":  [(0, *WIDE), (0.2, *WIDE), (0.6, 910, 230, 1.6), (1, 910, 240, 1.65)],
    "outro":     [(0, 640, 360, 1.1), (1, *WIDE)],
}


def camera(sid, f):
    """Smoothly eased camera (cx, cy, zoom) at fraction f of scene `sid`."""
    keys = FOCUS.get(sid) if ZOOM else None
    keys = keys or [(0, *WIDE), (1, *WIDE)]
    for (f0, *a), (f1, *b) in zip(keys, keys[1:]):
        if f <= f1:
            k = 0 if f1 == f0 else max(0.0, min(1.0, (f - f0) / (f1 - f0)))
            k = k * k * (3 - 2 * k)
            return [x + (y - x) * k for x, y in zip(a, b)]
    return keys[-1][1:]


def narrate():
    from kokoro_onnx import Kokoro
    k = shoot.VA / "models" / "kokoro"
    tts = Kokoro(str(k / "kokoro-v1.0.onnx"), str(k / "voices-v1.0.bin"))
    out = []
    for sid, _, text in SCENES:
        audio, sr = tts.create(text, voice="am_michael", speed=SPEED, lang="en-us")
        assert sr == SR
        out.append(np.asarray(audio, dtype=np.float32))
        print(f"  voice {sid}: {len(audio) / SR:.1f}s")
    return out




def main():
    shoot.storage.apply_env()
    shoot.build_window_page()
    FRAMES.mkdir(parents=True, exist_ok=True)
    print("narration ...")
    voices = narrate()
    lead, tail = 0.25, 0.45
    durs = [lead + len(v) / SR + tail for v in voices]

    print("frames ...")
    jobs, plan = [], []
    for (sid, anim, _), d in zip(SCENES, durs):
        n = max(2, int(d * ANIM_FPS) + 2) if anim else 1
        paths = []
        for i in range(n):
            p = FRAMES / f"{sid}_{i:03d}.png"
            jobs.append((sid, i, 1800 + i * (1000 // ANIM_FPS), p))
            paths.append(p)
        plan.append(paths)
    # parallel Edge processes each need their own profile folder (on the cache drive)
    import queue
    profs = queue.Queue()
    for k in range(4):
        profs.put(shoot.PROFILE.parent / f"edge-shots-{k}")

    def run(job):
        prof = profs.get()
        try:
            return _with_profile(job, prof)
        finally:
            profs.put(prof)
    with ThreadPoolExecutor(4) as ex:
        for n, _ in enumerate(ex.map(run, jobs), 1):
            if n % 25 == 0 or n == len(jobs):
                print(f"  {n}/{len(jobs)}")

    print("encoding ...")
    import av
    cont = av.open(str(OUT), "w")
    vs = cont.add_stream("libx264", rate=FPS)
    vs.width, vs.height, vs.pix_fmt = W, H, "yuv420p"
    vs.options = {"crf": "24", "preset": "slow"}
    aus = cont.add_stream("aac", rate=SR)
    aus.layout = "mono"

    cache = {}
    def img(p):
        if p not in cache:
            if len(cache) > 6:
                cache.clear()
            cache[p] = shoot.read_png(p)  # uint8, 2x size
        return cache[p]

    def view(a, cam):  # crop the 2x frame to the camera, scale to 1280x720
        cx, cy, z = cam
        cw, ch = W * SCALE / z, H * SCALE / z
        x0 = int(round(min(max(cx * SCALE - cw / 2, 0), W * SCALE - cw)))
        y0 = int(round(min(max(cy * SCALE - ch / 2, 0), H * SCALE - ch)))
        crop = np.ascontiguousarray(a[y0:y0 + int(ch), x0:x0 + int(cw)])
        fr = av.VideoFrame.from_ndarray(crop, format="rgb24").reformat(W, H, interpolation="AREA")
        return fr.to_ndarray(format="rgb24").astype(np.float32)

    def scene_frame(s, t):  # scene index, t seconds into the scene
        paths, cam = plan[s], camera(SCENES[s][0], min(1.0, t / durs[s]))
        if len(paths) == 1:
            return view(img(paths[0]), cam)
        x = min(t * ANIM_FPS, len(paths) - 1.001)
        a, f = int(x), x - int(x)
        return view(img(paths[a]), cam) * (1 - f) + view(img(paths[a + 1]), cam) * f

    track = []
    for v in voices:
        track += [np.zeros(int(lead * SR), np.float32), v, np.zeros(int(tail * SR), np.float32)]
    audio = np.concatenate(track)
    audio = (audio / max(1e-6, np.abs(audio).max()) * 0.9).astype(np.float32)

    starts = np.cumsum([0] + durs[:-1])
    total = sum(durs)
    nframes = int(total * FPS)
    for fi in range(nframes):
        t = fi / FPS
        s = int(np.searchsorted(starts, t, side="right") - 1)
        fr = scene_frame(s, t - starts[s])
        end = starts[s] + durs[s]
        if s + 1 < len(plan) and t > end - XFADE:  # crossfade into the next scene
            k = (t - (end - XFADE)) / XFADE
            fr = fr * (1 - k) + scene_frame(s + 1, 0) * k
        if fi < FPS * 0.5:  # fade in from black
            fr = fr * (fi / (FPS * 0.5))
        if fi > nframes - FPS * 0.8:  # fade out
            fr = fr * max(0.0, (nframes - fi) / (FPS * 0.8))
        frame = av.VideoFrame.from_ndarray(fr.clip(0, 255).astype(np.uint8), format="rgb24")
        for pkt in vs.encode(frame):
            cont.mux(pkt)
    for pkt in vs.encode():
        cont.mux(pkt)

    step = 1024
    for i in range(0, len(audio), step):
        chunk = audio[i:i + step]
        af = av.AudioFrame.from_ndarray(chunk.reshape(1, -1), format="flt", layout="mono")
        af.sample_rate, af.pts = SR, i
        for pkt in aus.encode(af):
            cont.mux(pkt)
    for pkt in aus.encode():
        cont.mux(pkt)
    cont.close()
    print(f"ok {OUT}  ({total:.0f}s, {OUT.stat().st_size / 1e6:.1f} MB)")


def _with_profile(job, prof):
    # shoot.PROFILE is read inside _shoot; use a per-thread copy of the call instead of mutating the global
    sid, i, budget, out = job
    if out.exists():
        return out
    url = (shoot.DOCS / "src" / "video.html").as_uri() + "#" + sid
    import os
    import subprocess
    import time
    cmd = [str(shoot.EDGE), "--headless=new", "--disable-gpu", "--hide-scrollbars", "--no-first-run",
           "--disable-extensions", "--disable-sync", f"--user-data-dir={prof}",
           f"--window-size={W},{H}", f"--force-device-scale-factor={SCALE}",
           f"--virtual-time-budget={budget}", f"--screenshot={out}", url]
    subprocess.run(cmd, capture_output=True, timeout=60, env=dict(os.environ))
    t0, last = time.time(), -1
    while time.time() - t0 < 60:
        size = out.stat().st_size if out.exists() else -1
        if size > 0 and size == last:
            return out
        last = size
        time.sleep(0.4)
    raise SystemExit(f"frame failed: {out}")


if __name__ == "__main__":
    if "--fresh" in sys.argv and FRAMES.exists():
        shutil.rmtree(FRAMES)
    main()
