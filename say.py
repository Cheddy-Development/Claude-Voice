"""Talk to the running voice bridge from any terminal / Claude session.

    python say.py "Done. The report is in the reports folder."      # speak (final answer)
    python say.py --progress "Pulling the numbers now."               # interim update
    python say.py --control window                                   # wake|sleep|cancel|link:<folder>|ack|...
    python say.py --settings tts=windows                              # Microsoft voice (lighter)
    python say.py --settings tts=kokoro voice=am_adam stt=base.en     # realistic voice, other speaker/model
    python say.py --settings                                          # show current settings + options
"""
import argparse
import json
import sys
import urllib.request

ap = argparse.ArgumentParser()
ap.add_argument("text", nargs="*")
ap.add_argument("--progress", action="store_true", help="interim update; keep the request open")
ap.add_argument("--control", help="send a control action instead of speech")
ap.add_argument("--settings", nargs="*", metavar="KEY=VALUE", help="view or change voice/model settings")
ap.add_argument("--port", type=int, default=8765)
a = ap.parse_args()

base = f"http://127.0.0.1:{a.port}"
if a.settings is not None:
    body = {}
    for kv in a.settings:
        k, _, v = kv.partition("=")
        body[k] = float(v) if k == "speed" else v
    path, data = "/settings", (json.dumps(body).encode() if body else None)
elif a.control:
    path, data = "/control", json.dumps({"action": a.control}).encode()
else:
    path, data = "/say", json.dumps({"text": " ".join(a.text), "final": not a.progress}).encode()

req = urllib.request.Request(base + path, data=data, method="POST" if data else "GET",
                             headers={"Content-Type": "application/json"})
try:
    print(urllib.request.urlopen(req, timeout=30).read().decode())
except Exception as e:
    print(f"voice bridge not reachable at {base}: {e}", file=sys.stderr)
    sys.exit(1)
