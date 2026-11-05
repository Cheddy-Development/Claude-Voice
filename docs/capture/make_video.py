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
XFADE = 0.35          # seconds of crossfade between scenes
OUT = shoot.DOCS / "claude_voice_setup.mp4"
FRAMES = shoot.storage.CACHE / "video_frames"

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


def narrate():
    from kokoro_onnx import Kokoro
    k = shoot.VA / "models" / "kokoro"
    tts = Kokoro(str(k / "kokoro-v1.0.onnx"), str(k / "voices-v1.0.bin"))
    out = []
    for sid, _, text in SCENES:
        audio, sr = tts.create(text, voice="am_michael", speed=1.0, lang="en-us")
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
    lead, tail = 0.5, 0.7
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
    vs.options = {"crf": "20", "preset": "medium", "tune": "stillimage"}
    aus = cont.add_stream("aac", rate=SR)
    aus.layout = "mono"

    cache = {}
    def img(p):
        if p not in cache:
            cache.clear() if len(cache) > 40 else None
            cache[p] = shoot.read_png(p).astype(np.float32)
        return cache[p]

    def scene_frame(paths, t):  # t seconds into the scene
        if len(paths) == 1:
            return img(paths[0])
        x = min(t * ANIM_FPS, len(paths) - 1.001)
        a, f = int(x), x - int(x)
        return img(paths[a]) * (1 - f) + img(paths[a + 1]) * f

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
        fr = scene_frame(plan[s], t - starts[s])
        end = starts[s] + durs[s]
        if s + 1 < len(plan) and t > end - XFADE:  # crossfade into the next scene
            k = (t - (end - XFADE)) / XFADE
            fr = fr * (1 - k) + scene_frame(plan[s + 1], 0) * k
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
           f"--window-size={W},{H}", "--force-device-scale-factor=1",
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
