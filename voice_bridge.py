"""Voice bridge v2: talk to Claude Code hands-free, with a live orb window.

  "Let's talk"            -> wake (rising chime). Everything you say goes to Claude.
  "Okay, let's end"       -> sleep (falling chime). Running work still finishes.
  "Stop" / "wait"         -> cut the voice off mid-sentence (barge-in).
  "Cancel that"           -> abort the task Claude is working on.
  "New conversation"      -> fresh Claude context.
  "Talk to VS Code"       -> HERE mode: requests go to the VS Code Claude session (via feed.log
                             + Monitor); that session answers with say.py.
  "Separate session"      -> SEPARATE mode: the bridge's own persistent Claude session.

While asleep, speech is transcribed locally ONLY to spot the wake phrase. Nothing is logged or sent.

Every event is mirrored to logs/feed.log (one line each) so whatever Claude session you are in
can follow along with Monitor; logs/voice_YYYYMMDD.md keeps the readable transcript.
Everything lives on G: under this folder (C: is nearly full).
"""
from __future__ import annotations

import argparse
import gc
import glob
import json
import os
import queue
import random
import re
import subprocess
import sys
import threading
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

HERE = Path(__file__).resolve().parent
# Default folder for the separate session: the repo this lives in (…/projects/voice_assistant), else your home folder.
REPO = HERE.parent.parent if HERE.parent.name == "projects" else Path.home()
sys.path.insert(0, str(HERE))
import storage  # noqa: E402  - cache/models locations from storage.json

storage.apply_env()  # all temp/HF/pip caches -> storage.CACHE (never the C: profile)

import numpy as np  # noqa: E402
import sounddevice as sd  # noqa: E402

SR_IN = 16000
BLOCK = 480  # 30 ms
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)

WAKE = ["let's talk", "lets talk", "let us talk", "let's speak", "lets speak", "start listening"]
END = ["let's end", "lets end", "let us end", "stop listening", "end session", "go to sleep"]
RESET = ["new conversation", "start a new conversation", "fresh session"]
STOP_TALK = ["stop", "wait", "hold on", "quiet", "be quiet", "pause", "shut up", "enough", "stop talking"]
CANCEL = ["cancel that", "cancel the task", "cancel it", "abort", "never mind that"]
MODE_HERE = ["talk to vs code", "link to vs code", "vs code mode", "here mode", "use this session",
             "switch to vs code", "talk to v s code"]
MODE_SEP = ["separate session", "separate mode", "switch to separate", "your own session"]
VOICE_WINDOWS = ["microsoft voice", "windows voice", "lighter voice", "light voice", "basic voice", "simple voice"]
VOICE_REAL = ["realistic voice", "kokoro voice", "natural voice", "better voice", "real voice"]
JUNK = {"", "you", "thank you for watching", "thanks for watching", "bye", "uh", "um", "hmm", "mm hmm", "mm"}
# Utterances made only of these words are ignored, unless Claude just asked a question.
FILLER = {"okay", "ok", "um", "umm", "uh", "uhh", "hmm", "mm", "mhm", "so", "well", "yeah", "yes", "yep",
          "right", "alright", "sure", "no", "nope", "hm", "ah", "oh", "like"}
ACKS = ["On it.", "Okay.", "Got it.", "Sure."]

VOICE_PROMPT = (
    "The user is talking to you by VOICE through a local speech-to-text bridge while they do other "
    "work; a male text-to-speech voice reads EVERY piece of text you write aloud, as you write it. "
    "Talk like a colleague on a call. Before multi-step work, say in one short sentence what you are "
    "about to do; between major steps give a one-sentence spoken update; finish with 1-4 short "
    "sentences. Plain speech only: no markdown, lists, tables, code or long paths. Put anything long "
    "in a file and say briefly where. Transcription may be imperfect - interpret charitably; ask one "
    "short question if genuinely ambiguous. Never download or install anything to the C: drive (almost "
    "full) - use G:. Before downloading or installing ANYTHING, or doing anything slow or hard to undo, "
    "ask out loud first (what and how big) and wait for a yes."
)


# ----------------------------------------------------------------------------- text helpers
def norm(text: str) -> str:
    t = text.lower().replace("\u2019", "'").replace("vscode", "vs code")
    t = re.sub(r"[^a-z' ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def find_phrase(text: str, phrases: list[str]) -> int:
    n = norm(text)
    for p in phrases:
        i = n.find(p)
        if i >= 0:
            return i + len(p)
    return -1


def is_stop(n: str) -> bool:
    return n in STOP_TALK or (len(n.split()) <= 3 and any(re.search(rf"\b{p}\b", n) for p in STOP_TALK))


def clean_for_speech(text: str) -> str:
    t = re.sub(r"```.*?```", " ", text, flags=re.S)
    t = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", t)            # markdown links -> label
    t = re.sub(r"https?://\S+", "a link", t)
    t = re.sub(r"(?:[A-Za-z]:[\\/])?(?:[\w.\-]+[\\/])+([\w.\-]+)", r"\1", t)  # paths -> basename
    t = re.sub(r"[`*#_>|]+", " ", t)
    t = re.sub(r"^\s*[-•]\s+", "", t, flags=re.M)
    return re.sub(r"\s+", " ", t).strip()


def split_sentences(text: str) -> list[str]:
    parts = [p.strip() for p in re.split(r"(?<=[.!?;:])\s+", text) if p.strip()]
    out: list[str] = []
    for p in parts:
        while len(p) > 280:  # very long sentence: break at a comma
            cut = p.rfind(",", 0, 280)
            cut = cut if cut > 60 else 280
            out.append(p[:cut + 1].strip())
            p = p[cut + 1:].strip()
        if out and len(out[-1]) < 25:
            out[-1] += " " + p
        else:
            out.append(p)
    return out


def find_claude() -> str:
    if os.environ.get("CLAUDE_BIN"):
        return os.environ["CLAUDE_BIN"]
    hits = glob.glob(str(Path.home() / ".vscode/extensions/anthropic.claude-code-*/resources/native-binary/claude.exe"))
    if hits:
        def ver(p):
            m = re.search(r"claude-code-(\d+)\.(\d+)\.(\d+)", p)
            return tuple(int(x) for x in m.groups()) if m else (0,)
        return max(hits, key=ver)
    import shutil
    return shutil.which("claude") or "claude"  # npm / standalone installs (claude.cmd / claude.exe)


# ----------------------------------------------------------------------------- settings + model discovery
CONFIG = HERE / "voice_config.json"
DEFAULTS = {"tts": "kokoro", "tts_model": None, "voice": "am_michael",
            "windows_voice": "Microsoft David Desktop", "speed": 1.05, "stt": "small.en"}
MODELS = storage.MODELS


def load_config() -> dict:
    try:
        return {**DEFAULTS, **json.loads(CONFIG.read_text(encoding="utf-8"))}
    except Exception:
        return dict(DEFAULTS)


def save_config(cfg: dict):
    CONFIG.write_text(json.dumps({k: cfg.get(k) for k in DEFAULTS}, indent=2), encoding="utf-8")


def _mb(p: Path) -> int:
    return int(storage.size_mb(p))  # counts linked HF blobs once


def scan_tts() -> list[dict]:
    """Realistic (Kokoro-style) voice models: any folder with *.onnx + voices*.bin in
    models/kokoro/ or models/tts/<name>/. Rescanned every time - drop folders in or delete them."""
    out = []
    dirs = [MODELS / "kokoro"] + (sorted(p for p in (MODELS / "tts").iterdir() if p.is_dir())
                                   if (MODELS / "tts").is_dir() else [])
    for d in dirs:
        if not d.is_dir():
            continue
        vb = next(iter(sorted(d.glob("voices*.bin"))), None)
        if not vb:
            continue
        for onnx in sorted(d.glob("*.onnx")):
            out.append({"id": f"{d.name}/{onnx.name}", "onnx": str(onnx), "voices": str(vb),
                        "label": f"{d.name} / {onnx.stem}", "mb": _mb(onnx)})
    return out


_VOICE_CACHE: dict[str, list[str]] = {}


def scan_voices(voices_bin: str) -> list[str]:
    """Speaker names inside a voices*.bin (npz). Male voices (am_/bm_) listed first."""
    if voices_bin not in _VOICE_CACHE:
        try:
            names = list(np.load(voices_bin).files)
        except Exception:
            names = []
        male = sorted(n for n in names if n[1:3] == "m_")
        _VOICE_CACHE[voices_bin] = male + sorted(n for n in names if n not in male)
    return _VOICE_CACHE[voices_bin]


def scan_stt() -> list[dict]:
    """Speech-to-text models: downloaded faster-whisper caches in models/, plus any CTranslate2
    Whisper folder (contains model.bin) dropped into models/stt/<name>/."""
    out = []
    for d in sorted(MODELS.glob("models--*--faster-*whisper-*")):
        if not any(d.glob("snapshots/*/model.bin")):
            continue
        m = re.search(r"faster-(distil-)?whisper-(.+)$", d.name)
        name = (m.group(1) or "") + m.group(2)
        out.append({"id": name, "label": name, "mb": _mb(d)})
    if (MODELS / "stt").is_dir():
        for d in sorted((MODELS / "stt").iterdir()):
            if (d / "model.bin").exists():
                out.append({"id": str(d), "label": d.name, "mb": _mb(d)})
    return out


_WIN_VOICES: list[str] = []


def windows_voices() -> list[str]:
    global _WIN_VOICES
    if not _WIN_VOICES:
        try:
            r = subprocess.run(["powershell", "-NoProfile", "-Command",
                                "Add-Type -AssemblyName System.Speech; (New-Object System.Speech.Synthesis."
                                "SpeechSynthesizer).GetInstalledVoices() | % { $_.VoiceInfo.Name + '|' + $_.VoiceInfo.Gender }"],
                               capture_output=True, text=True, timeout=20, creationflags=NO_WINDOW)
            rows = [ln.strip().split("|") for ln in r.stdout.splitlines() if "|" in ln]
            _WIN_VOICES = [n for n, g in rows if g == "Male"] + [n for n, g in rows if g != "Male"]
        except Exception:
            _WIN_VOICES = ["Microsoft David Desktop"]
    return _WIN_VOICES


def kill_tree(pid: int):
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], capture_output=True, creationflags=NO_WINDOW)


# ----------------------------------------------------------------------------- event bus
class Bus:
    """Fans events out to the window (SSE), feed.log (for Monitor), the md transcript and stdout."""

    def __init__(self):
        (HERE / "logs").mkdir(exist_ok=True)
        self.md = HERE / "logs" / f"voice_{datetime.now():%Y%m%d}.md"
        self.feed_path = HERE / "logs" / "feed.log"
        self.clients: list[queue.Queue] = []
        self.history: list[dict] = []
        self.lock = threading.Lock()
        self.flock = threading.Lock()
        self._lvl_t = {"mic": 0.0, "out": 0.0}

    def subscribe(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=1000)
        with self.lock:
            self.clients.append(q)
        return q

    def unsubscribe(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def push(self, ev: dict):
        data = json.dumps(ev)
        with self.lock:
            for q in self.clients:
                try:
                    q.put_nowait(data)
                except queue.Full:
                    pass

    def level(self, ch: str, rms: float):
        now = time.time()
        if now - self._lvl_t[ch] >= 0.05:
            self._lvl_t[ch] = now
            self.push({"type": "level", "ch": ch, "v": round(rms, 4)})

    def feed(self, kind: str, text: str):
        ts = f"{datetime.now():%H:%M:%S}"
        ev = {"type": "feed", "kind": kind, "text": text, "ts": ts}
        with self.lock:
            self.history = (self.history + [ev])[-150:]
        self.push(ev)
        one = re.sub(r"\s+", " ", text).strip()
        with self.flock:
            with open(self.feed_path, "a", encoding="utf-8") as f:
                f.write(f"{ts} {kind.upper()} {one}\n")
            with open(self.md, "a", encoding="utf-8") as f:
                f.write(f"**{ts} {kind}:** {text}\n\n")
        print(f"[{kind}] {one}", flush=True)


# ----------------------------------------------------------------------------- voice out
class SapiWav:
    """Windows (Microsoft) voices rendered to WAV by one persistent PowerShell process. Very light."""
    PS = r"""
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$fmt = New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo 24000,([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen),([System.Speech.AudioFormat.AudioChannel]::Mono)
$U = [Text.Encoding]::UTF8
while ($true) {
  $line = [Console]::In.ReadLine(); if ($line -eq $null) { break }
  $p, $v, $b = $line.Split('|', 3)
  try { $s.SelectVoice($U.GetString([Convert]::FromBase64String($v))) } catch { try { $s.SelectVoiceByHints('Male') } catch {} }
  $s.Rate = 1
  $s.SetOutputToWaveFile($p, $fmt); $s.Speak($U.GetString([Convert]::FromBase64String($b))); $s.SetOutputToNull()
  [Console]::Out.WriteLine('DONE'); [Console]::Out.Flush()
}"""

    def __init__(self):
        self.proc = subprocess.Popen(["powershell", "-NoProfile", "-NonInteractive", "-Command", self.PS],
                                     stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
                                     creationflags=NO_WINDOW)
        self.path = storage.CACHE / "tmp" / "sapi.wav"

    def create(self, text: str, voice: str):
        import base64
        import wave

        def b(s):
            return base64.b64encode(s.encode("utf-8")).decode()
        self.proc.stdin.write(f"{self.path}|{b(voice)}|{b(text)}\n")
        self.proc.stdin.flush()
        self.proc.stdout.readline()
        with wave.open(str(self.path)) as w:
            return np.frombuffer(w.readframes(w.getnframes()), np.int16).astype(np.float32) / 32768, 24000


class Voice:
    """Sentence-streamed TTS with two swappable engines:
       kokoro  - realistic neural voice (~300-400 MB RAM, CPU burst per sentence)
       windows - built-in Microsoft voices (near-zero RAM/CPU)
    Synthesizes sentence N+1 while N plays; interruptible; emits output levels for the orb."""
    SR = 24000

    def __init__(self, args, bus: Bus, cfg: dict):
        self.args, self.bus = args, bus
        self.text_q: queue.Queue = queue.Queue()
        self.audio_q: queue.Queue = queue.Queue()
        self.gen = 0
        self.synthesizing = self.playing = False
        self.last_audio = 0.0
        self.engine_lock = threading.RLock()
        self.kokoro = None
        self.sapi: SapiWav | None = None
        self.kind = "windows"
        self.tts_model = cfg.get("tts_model")
        self.kokoro_voice = cfg.get("voice", "am_michael")
        self.windows_voice = cfg.get("windows_voice", "Microsoft David Desktop")
        self.speed = float(cfg.get("speed", 1.05))
        self.set_engine(cfg.get("tts", "kokoro"), self.tts_model)
        # Audio-output robustness: Bluetooth/USB/FxSound outputs can sleep or switch while idle, which makes a
        # long-lived stream's write() block forever (orb stuck on "speaking", mic ignored). So: a watchdog
        # aborts a stalled write and reconnects, and after a long idle we reconnect before speaking.
        self.reset_audio = None          # set by App: full re-init of speaker + mic (follows Windows defaults)
        self.stream = None
        self.last_write = 0.0
        self.last_reset = time.time()
        self.player_id = 0
        self.open_stream()
        threading.Thread(target=self._synth_loop, daemon=True).start()
        self._start_player()
        threading.Thread(target=self._watchdog, daemon=True).start()

    IDLE_RESET_S = 180   # reconnect audio before speaking if it has been quiet this long
    STALL_S = 3.0        # a 40 ms write taking longer than this means the output device is gone/asleep

    def open_stream(self):
        self.stream = sd.OutputStream(samplerate=self.SR, channels=1, dtype="float32", device=self.args.speaker)
        self.stream.start()

    def close_stream(self):
        s, self.stream = self.stream, None
        if s is not None:
            for fn in (s.abort, s.close):
                try:
                    fn()
                except Exception:
                    pass

    def _start_player(self):
        self.player_id += 1
        threading.Thread(target=self._play_loop, args=(self.player_id,), daemon=True).start()

    def _watchdog(self):
        while True:
            time.sleep(0.5)
            if self.playing and time.time() - self.last_write > self.STALL_S:
                self.bus.feed("error", "speaker stopped responding - reconnecting audio")
                self.playing = False
                stuck = self.stream
                self._start_player()      # fresh player thread; the blocked one exits when it wakes
                self.stop()               # drop what was queued (it would play late)
                try:
                    stuck.abort()         # unblocks the stalled write()
                except Exception:
                    pass
                if self.reset_audio:
                    self.reset_audio("speaker stopped responding", quiet=False)
                else:
                    self.close_stream()
                    self.open_stream()

    # -- engine management
    def set_engine(self, kind: str, model_id: str | None = None) -> str:
        """Switch engine (and realistic model). Returns the engine actually in use."""
        with self.engine_lock:
            if kind == "kokoro":
                models = scan_tts()
                m = next((x for x in models if x["id"] == model_id), None) or (models[0] if models else None)
                if not m:
                    self.bus.feed("error", "no realistic voice model found in models/; using the Microsoft voice")
                    kind = "windows"
                else:
                    try:
                        if self.kokoro is None or self.tts_model != m["id"]:
                            from kokoro_onnx import Kokoro
                            self.kokoro = None
                            gc.collect()
                            self.kokoro = Kokoro(m["onnx"], m["voices"])
                            self.tts_model = m["id"]
                        voices = scan_voices(m["voices"])
                        if voices and self.kokoro_voice not in voices:
                            self.kokoro_voice = voices[0]
                    except Exception as e:
                        self.bus.feed("error", f"realistic voice failed to load ({e!r}); using the Microsoft voice")
                        self.kokoro, kind = None, "windows"
            if kind == "windows":
                self.kokoro = None  # free the neural model's memory
                gc.collect()
                if self.sapi is None:
                    self.sapi = SapiWav()
            self.kind = kind
            return kind

    @property
    def engine(self) -> str:
        if self.kind == "kokoro":
            return f"Realistic ({self.kokoro_voice})"
        return f"Microsoft ({self.windows_voice.replace('Microsoft ', '').replace(' Desktop', '')})"

    # -- speaking
    @property
    def busy(self) -> bool:
        return (self.playing or self.synthesizing or not self.text_q.empty() or not self.audio_q.empty()
                or time.time() - self.last_audio < 0.45)  # echo tail

    def say(self, text: str):
        text = clean_for_speech(text)
        for s in split_sentences(text):
            self.text_q.put((self.gen, s))

    def stop(self):
        self.gen += 1
        for q in (self.text_q, self.audio_q):
            while not q.empty():
                try:
                    q.get_nowait()
                except queue.Empty:
                    break

    def _synth(self, s: str):
        with self.engine_lock:
            if self.kind == "kokoro" and self.kokoro:
                audio, sr = self.kokoro.create(s, voice=self.kokoro_voice, speed=self.speed, lang="en-us")
            else:
                if self.sapi is None:
                    self.sapi = SapiWav()
                audio, sr = self.sapi.create(s, self.windows_voice)
        audio = np.asarray(audio, dtype=np.float32)
        if sr != self.SR:  # cheap linear resample
            x = np.linspace(0, len(audio) - 1, int(len(audio) * self.SR / sr))
            audio = np.interp(x, np.arange(len(audio)), audio).astype(np.float32)
        return audio

    def _synth_loop(self):
        while True:
            g, s = self.text_q.get()
            if g != self.gen:
                continue
            self.synthesizing = True
            try:
                audio = self._synth(s)
                if g == self.gen:
                    self.audio_q.put((g, audio))
            except Exception as e:
                self.bus.feed("error", f"voice synthesis failed: {e!r}")
            finally:
                self.synthesizing = False

    def _play_loop(self, pid: int):
        n = 960  # 40 ms
        while pid == self.player_id:
            try:
                g, audio = self.audio_q.get(timeout=1)
            except queue.Empty:
                continue
            if pid != self.player_id:
                self.audio_q.put((g, audio))  # hand it to the current player
                return
            if g != self.gen:
                continue
            now = time.time()
            if (self.reset_audio and now - self.last_audio > self.IDLE_RESET_S
                    and now - self.last_reset > self.IDLE_RESET_S):
                self.reset_audio("idle", quiet=True)  # pick up whatever speaker Windows uses now
            self.playing = True
            self.last_write = time.time()
            try:
                for i in range(0, len(audio), n):
                    deadline = time.time() + 5  # a reconnect may be in progress: wait for the new stream
                    while self.stream is None and time.time() < deadline:
                        self.last_write = time.time()
                        time.sleep(0.05)
                    if g != self.gen or pid != self.player_id or self.stream is None:
                        break
                    chunk = audio[i:i + n]
                    self.stream.write(chunk.reshape(-1, 1))
                    self.last_write = self.last_audio = time.time()
                    self.bus.level("out", float(np.sqrt(np.mean(chunk ** 2))))
            except Exception as e:
                if pid == self.player_id:
                    self.bus.feed("error", f"speaker error ({e!r}) - reconnecting audio")
                    if self.reset_audio:
                        threading.Thread(target=self.reset_audio, args=("speaker error",),
                                         kwargs={"quiet": False}, daemon=True).start()
            finally:
                if pid == self.player_id:
                    self.playing = False
                    self.bus.level("out", 0.0)


def chime(up: bool):
    try:
        import winsound
        for f in ((660, 880) if up else (880, 520)):
            winsound.Beep(f, 110)
    except Exception:
        pass


# ----------------------------------------------------------------------------- Claude backends
TOOL_WORDS = {"Bash": "Running a command.", "PowerShell": "Running a command.", "Read": "Reading a file.",
              "Grep": "Searching.", "Glob": "Searching.", "Edit": "Editing a file.", "Write": "Writing a file.",
              "WebSearch": "Checking the web.", "WebFetch": "Checking the web.", "Agent": "Starting a helper.",
              "Task": "Starting a helper."}


def describe_tool(block: dict) -> str:
    inp = block.get("input") or {}
    name = block.get("name", "tool")
    detail = inp.get("description") or inp.get("command") or inp.get("file_path") or inp.get("pattern") or inp.get("query") or ""
    return f"{name}: {str(detail)[:160]}"


def load_workspaces() -> dict[str, str]:
    """Named folders the separate session can work in (workspaces.json: {"name": "G:/path"})."""
    f = HERE / "workspaces.json"
    try:
        return {norm(k): v for k, v in json.loads(f.read_text(encoding="utf-8")).items()}
    except Exception:
        return {"analytics": str(REPO)}


def resolve_folder(name_or_path: str | None) -> Path:
    if not name_or_path:
        return REPO
    ws = load_workspaces()
    p = Path(ws.get(norm(name_or_path), name_or_path))
    if not p.is_dir():
        raise SystemExit(f"--cwd: no such folder or workspace name: {name_or_path}")
    return p.resolve()


class SeparateBackend:
    """One persistent `claude -p` stream-json process: realtime, multi-turn, resumable."""
    name = "separate"

    def __init__(self, app):
        self.app, self.args, self.bus = app, app.args, app.bus
        self.bin = find_claude()
        self.cwd = resolve_folder(self.args.cwd)
        self.sid_file = HERE / "logs" / "separate_sessions.json"  # one session per folder
        self.session_id = None if self.args.new else self._sids().get(str(self.cwd))
        self.proc: subprocess.Popen | None = None
        self.busy = False
        self.lock = threading.Lock()
        self.last_narr = 0.0

    def _spawn(self):
        cmd = [self.bin, "-p", "--input-format", "stream-json", "--output-format", "stream-json", "--verbose",
               "--permission-mode", self.args.permission_mode, "--append-system-prompt", VOICE_PROMPT]
        if self.args.model:
            cmd += ["--model", self.args.model]
        if self.session_id:
            cmd += ["--resume", self.session_id]
        self.proc = subprocess.Popen(cmd, cwd=str(self.cwd), stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                     stderr=subprocess.PIPE, text=True, encoding="utf-8", errors="replace",
                                     bufsize=1, creationflags=NO_WINDOW)
        threading.Thread(target=self._read, args=(self.proc,), daemon=True).start()
        threading.Thread(target=self._read_err, args=(self.proc,), daemon=True).start()

    def send(self, text: str):
        with self.lock:
            if not self.proc or self.proc.poll() is not None:
                self._spawn()
            msg = {"type": "user", "message": {"role": "user", "content": text}}
            self.proc.stdin.write(json.dumps(msg) + "\n")
            self.proc.stdin.flush()
            self.busy = True

    def _read_err(self, proc):
        for line in proc.stderr:
            line = line.strip()
            if line and "warn" not in line.lower():
                self.bus.feed("error", f"claude: {line[:300]}")

    def _read(self, proc):
        for line in proc.stdout:
            if not line.startswith("{"):
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            sid = ev.get("session_id")
            if sid and sid != self.session_id:
                self.session_id = sid
                self._save_sid(sid)
                self.bus.feed("system", f"separate Claude session {sid} in {self.cwd}")
            t = ev.get("type")
            if t == "assistant":
                self.busy = True
                for b in (ev.get("message") or {}).get("content") or []:
                    if b.get("type") == "text" and b.get("text", "").strip():
                        self.bus.feed("claude", b["text"].strip())
                        self.app.voice.say(b["text"])
                    elif b.get("type") == "tool_use":
                        self.bus.feed("tool", describe_tool(b))
                        if (self.args.narrate and not self.app.voice.busy
                                and time.time() - self.last_narr > 10):
                            self.last_narr = time.time()
                            self.app.voice.say(TOOL_WORDS.get(b.get("name"), "Working."))
            elif t == "result":
                self.busy = False
                if ev.get("is_error"):
                    msg = ev.get("result") or ev.get("subtype") or "error"
                    self.bus.feed("error", f"Claude turn failed: {msg}")
                    self.app.voice.say("That request hit an error. It's in the log.")
        if proc is self.proc:  # unexpected exit
            self.busy = False
            self.proc = None
            self.bus.feed("system", f"Claude process exited ({proc.poll()}); will resume on next request")

    def cancel(self):
        with self.lock:
            p, self.proc, self.busy = self.proc, None, False
        if p:
            kill_tree(p.pid)

    def reset(self):
        self.cancel()
        self.session_id = None
        self._save_sid(None)

    def set_cwd(self, folder: Path):
        """Point the separate session at another folder (resumes that folder's last session)."""
        self.cancel()
        self.cwd = folder
        self.session_id = self._sids().get(str(folder))
        self.bus.feed("system", f"separate session now works in {folder}")

    def _sids(self) -> dict:
        try:
            return json.loads(self.sid_file.read_text(encoding="utf-8"))
        except Exception:
            return {}

    def _save_sid(self, sid):
        d = self._sids()
        if sid:
            d[str(self.cwd)] = sid
        else:
            d.pop(str(self.cwd), None)
        self.sid_file.write_text(json.dumps(d, indent=2), encoding="utf-8")

    def shutdown(self):
        self.cancel()


class HereBackend:
    """Routes requests to whatever Claude session is following feed.log (as ASK lines)."""
    name = "here"

    def __init__(self, app):
        self.app = app
        self.busy = False
        self.since = 0.0
        self.nudged = False
        self.acked = False  # the linked session showed a sign of life for the current request
        threading.Thread(target=self._watchdog, daemon=True).start()

    def send(self, text: str):
        if self.busy and self.acked:
            return  # follow-up while the session is already on it - no new pickup timer
        self.busy, self.since, self.nudged, self.acked = True, time.time(), False, False

    def ack(self):
        """Any sign of life from the linked session: silent ack, progress update, or final answer."""
        self.acked = True

    def done(self):
        self.busy = False
        self.acked = True

    def cancel(self):
        self.busy = False
        self.app.bus.feed("cancel", "user cancelled the current request")

    def reset(self):
        self.app.bus.feed("system", "user asked for a new conversation")

    def shutdown(self):
        pass

    def _watchdog(self):
        while True:
            time.sleep(2)
            # Warn once, only if the linked session has given NO sign of life (no ack, no progress, no answer).
            if (self.busy and not self.acked and not self.nudged
                    and time.time() - self.since > self.app.args.here_timeout):
                self.nudged = True
                self.app.voice.say("The linked Claude window hasn't responded yet. It may still be busy. "
                                   "Say separate session if you want me to handle it instead.")


# ----------------------------------------------------------------------------- mic in
class Listener:
    def __init__(self, app):
        self.app = app
        self.frames: queue.Queue = queue.Queue()
        self.in_speech = False

        self.stream = None

    def start(self):
        a = self.app.args
        mic = int(a.mic) if a.mic and str(a.mic).isdigit() else a.mic
        self.stream = sd.InputStream(samplerate=SR_IN, channels=1, dtype="float32", blocksize=BLOCK,
                                     device=mic, callback=self.callback)
        self.stream.start()

    def stop(self):
        s, self.stream = self.stream, None
        if s is not None:
            for fn in (s.abort, s.close):
                try:
                    fn()
                except Exception:
                    pass

    def callback(self, indata, frames, t, status):
        blk = indata[:, 0].copy()
        self.frames.put(blk)
        self.app.bus.level("mic", float(np.sqrt(np.mean(blk ** 2))))

    def utterances(self):
        """Yield (audio, during_speech). during_speech=True if the bot was talking at any point."""
        a = self.app.args
        floor, buf, pre = 0.003, [], []
        voiced = silent = 0
        during = False
        end_blocks = int(a.silence / 0.03)
        while True:
            blk = self.frames.get()
            rms = float(np.sqrt(np.mean(blk ** 2)) + 1e-9)
            loud = rms > max(floor * a.sensitivity, 0.006)
            talking = self.app.voice.busy
            if not self.in_speech:
                floor = 0.98 * floor + 0.02 * min(rms, floor * 2.5)
                pre = (pre + [blk])[-10:]
                voiced = voiced + 1 if loud else 0
                if voiced >= 3:
                    self.in_speech, buf, silent, during = True, list(pre), 0, talking
            else:
                buf.append(blk)
                during = during or talking
                silent = 0 if loud else silent + 1
                max_blocks = int((3 if during else a.max_utterance) / 0.03)  # while it talks only short commands count
                if silent >= end_blocks or len(buf) >= max_blocks:
                    audio = np.concatenate(buf)
                    self.in_speech, buf, pre, voiced = False, [], [], 0
                    if len(audio) > SR_IN * 0.35:
                        yield audio, during


# ----------------------------------------------------------------------------- app
class App:
    def __init__(self, args):
        self.args = args
        self.bus = Bus()
        self.cfg = load_config()
        for k, a in (("tts", "tts"), ("voice", "voice"), ("windows_voice", "windows_voice"),
                     ("speed", "speed"), ("stt", "model_size")):
            if getattr(args, a, None) is not None:  # explicit CLI flags win over the saved config
                self.cfg[k] = getattr(args, a)
        self.voice = Voice(args, self.bus, self.cfg)
        self.stt_model = None
        self.stt_name = self.cfg["stt"]
        self.active = args.start_active
        self.backends = {"separate": SeparateBackend(self), "here": HereBackend(self)}
        self.mode = args.mode
        self.listener = Listener(self)
        self.audio_lock = threading.Lock()
        self.voice.reset_audio = self.reset_audio
        self.state = ""

    @property
    def backend(self):
        return self.backends[self.mode]

    # -- control
    def wake(self, say=True):
        if not self.active:
            self.active = True
            chime(True)
            heard, self.last_heard = getattr(self, "last_heard", ""), ""
            self.bus.feed("system", "listening" + (f' (heard: "{heard}")' if heard else ""))
            if say:
                self.voice.say("I'm listening.")

    def sleep(self):
        if self.active:
            self.active = False
            chime(False)
            heard, self.last_heard = getattr(self, "last_heard", ""), ""
            self.bus.feed("system", "stopped listening" + (f' (heard: "{heard}")' if heard else ""))
            self.voice.say("Okay, I'll stop listening." +
                           (" I'll still finish what I'm on." if self.backend.busy else ""))

    def set_mode(self, mode: str):
        if mode in self.backends and mode != self.mode:
            self.mode = mode
            self.bus.feed("system", f"mode: {mode}")
            self.voice.say("Okay, I'm routing to the VS Code session." if mode == "here"
                           else "Okay, using my own separate session.")
            self.push_state(force=True)

    def cancel(self):
        self.voice.stop()
        if self.backend.busy:
            self.backend.cancel()
            self.bus.feed("system", "cancelled")
            self.voice.say("Cancelled.")

    def submit(self, text: str):
        if self.mode == "here":
            self.bus.feed("ask", text)
        else:
            self.bus.feed("you", text)
        self.voice.say("Got it, I'll add that." if self.backend.busy else random.choice(ACKS))
        self.backend.send(text)

    def control(self, action: str):
        if action.startswith("link:"):  # a Claude session (any folder) takes over HERE mode
            where = action[5:].strip() or "another folder"
            self.mode = "here"
            self.backends["here"].busy = False
            self.bus.feed("system", f"LINKED to the Claude session in {where}")
            self.voice.say(f"Linked. I'm now talking to the session in {Path(where).name or where}.")
            self.push_state(force=True)
            return True
        if action == "ack":  # silent "got it" from the linked session (no speech, no feed line)
            self.backends["here"].ack()
            return True
        if action == "clear_cache":
            mb = storage.clear_cache()
            removed = storage.prune_logs()
            self.bus.feed("system", f"cache cleared: {mb} MB freed, {removed} old transcripts removed")
            return True
        acts = {"wake": self.wake, "sleep": self.sleep, "stop_speaking": self.voice.stop, "cancel": self.cancel,
                "mode:here": lambda: self.set_mode("here"), "mode:separate": lambda: self.set_mode("separate"),
                "new": lambda: (self.backend.reset(), self.voice.say("Starting a fresh conversation."))}
        if action in acts:
            acts[action]()
            self.push_state(force=True)
            return True
        return False

    # -- speech handling
    def handle(self, text: str, during_speech: bool):
        n = norm(text)
        self.last_heard = text  # shown in the feed if this utterance turns out to be a wake/stop command
        if n in JUNK:
            return
        if during_speech:  # mic hears the speaker: only obey short stop commands
            if is_stop(n):
                self.voice.stop()
                self.bus.feed("system", "stopped talking")
            return
        if not self.active:
            end = find_phrase(text, WAKE)
            if end < 0:
                return  # asleep: discard silently
            rest = n[end:].strip(" ,.")
            self.wake(say=len(rest.split()) < 3)
            if len(rest.split()) >= 3:
                self.submit(rest)
            return
        if find_phrase(text, END) >= 0:
            return self.sleep()
        if find_phrase(text, MODE_HERE) >= 0 and len(n.split()) <= 8:
            return self.set_mode("here")
        if find_phrase(text, MODE_SEP) >= 0 and len(n.split()) <= 8:
            return self.set_mode("separate")
        if find_phrase(text, RESET) >= 0 and len(n.split()) <= 6:
            return self.control("new")
        if len(n.split()) <= 8 and re.search(r"\b(switch|use|change|go)\b", n):
            if any(p in n for p in VOICE_WINDOWS):
                return self.apply_settings({"tts": "windows"})
            if any(p in n for p in VOICE_REAL):
                return self.apply_settings({"tts": "kokoro"})
        m = re.match(r"^(?:okay |ok |so )?(?:work in|switch to|go to|move to) (?:the )?(.+?)"
                     r"(?: project| folder| workspace| directory)?$", n)
        if m and m.group(1) in load_workspaces():
            folder = Path(load_workspaces()[m.group(1)])
            self.backends["separate"].set_cwd(folder)
            if self.mode != "separate":
                self.mode = "separate"
            self.voice.say(f"Okay, my separate session now works in {m.group(1)}.")
            return self.push_state(force=True)
        if (find_phrase(text, CANCEL) >= 0 or n == "cancel") and len(n.split()) <= 5:
            return self.cancel()
        if is_stop(n):
            return self.voice.stop()
        if all(w in FILLER for w in n.split()) and not self.claude_just_asked():
            return  # "okay, um..." / "yeah." - not a request
        self.submit(text)

    def claude_just_asked(self, within: float = 30) -> bool:
        with self.bus.lock:
            last = next((e for e in reversed(self.bus.history) if e["kind"] == "claude"), None)
        if not last or not last["text"].rstrip().endswith("?"):
            return False
        h, m, s = map(int, last["ts"].split(":"))
        now = datetime.now()
        return (now.hour * 3600 + now.minute * 60 + now.second) - (h * 3600 + m * 60 + s) <= within

    def compute_state(self) -> str:
        if self.voice.busy and (self.voice.playing or self.voice.audio_q.qsize()):
            return "speaking"
        if self.listener.in_speech and self.active:
            return "hearing"
        if self.backend.busy or self.voice.synthesizing:
            return "thinking"
        return "listening" if self.active else "sleeping"

    def push_state(self, force=False):
        s = self.compute_state()
        if force or s != self.state:
            self.state = s
            self.bus.push({"type": "state", "state": s, "mode": self.mode, "active": self.active,
                           "voice": self.voice.engine})

    def ticker(self):
        while True:
            self.push_state()
            time.sleep(0.08)

    # -- settings (window panel, voice commands, /settings API)
    def load_stt(self, name: str):
        from faster_whisper import WhisperModel
        self.bus.feed("system", f"loading speech model {Path(name).name} ...")
        m = WhisperModel(name, device=self.args.device,
                         compute_type="int8" if self.args.device == "cpu" else "float16",
                         download_root=str(MODELS))
        self.stt_model, self.stt_name = m, name  # swap; the old model is freed
        gc.collect()

    def settings(self) -> dict:
        tts_models = scan_tts()
        cur = next((m for m in tts_models if m["id"] == self.voice.tts_model), tts_models[0] if tts_models else None)
        return {
            "tts": self.voice.kind, "tts_model": self.voice.tts_model, "voice": self.voice.kokoro_voice,
            "windows_voice": self.voice.windows_voice, "speed": self.voice.speed, "stt": self.stt_name,
            "engine": self.voice.engine,
            "options": {
                "tts_models": [{k: m[k] for k in ("id", "label", "mb")} for m in tts_models],
                "voices": scan_voices(cur["voices"]) if cur else [],
                "windows_voices": windows_voices(),
                "stt": scan_stt(),
            },
            "storage": storage.report(),
        }

    def apply_settings(self, d: dict, speak: bool = True):
        """Apply any subset of {tts, tts_model, voice, windows_voice, speed, stt}; persists for next launch."""
        msg = None
        if "voice" in d:
            self.voice.kokoro_voice = d["voice"]
        if "windows_voice" in d:
            self.voice.windows_voice = d["windows_voice"]
        if "speed" in d:
            self.voice.speed = max(0.6, min(1.6, float(d["speed"])))
        if "tts" in d or "tts_model" in d:
            want = d.get("tts", self.voice.kind)
            got = self.voice.set_engine(want, d.get("tts_model", self.voice.tts_model))
            msg = ("Switched to the realistic voice." if got == "kokoro"
                   else "Switched to the Microsoft voice. It's lighter on your computer.")
        elif "voice" in d or "windows_voice" in d:
            msg = "This is my new voice."
        if d.get("stt") and d["stt"] != self.stt_name:
            def swap():
                try:
                    self.load_stt(d["stt"])
                    self.voice.say("Speech model switched.")
                except Exception as e:
                    self.bus.feed("error", f"could not load speech model {d['stt']}: {e!r}")
                self.save()
            threading.Thread(target=swap, daemon=True).start()
        self.save()
        self.bus.feed("system", f"settings: voice {self.voice.engine}, speech model {self.stt_name}")
        self.push_state(force=True)
        if speak and msg:
            self.voice.say(msg)

    def save(self):
        save_config({"tts": self.voice.kind, "tts_model": self.voice.tts_model, "voice": self.voice.kokoro_voice,
                     "windows_voice": self.voice.windows_voice, "speed": self.voice.speed, "stt": self.stt_name})

    def run(self):
        try:
            self.load_stt(self.stt_name)
        except Exception as e:
            self.bus.feed("error", f"speech model {self.stt_name} failed ({e!r}); falling back to small.en")
            self.load_stt("small.en")
        threading.Thread(target=self.ticker, daemon=True).start()
        self.listener.start()
        self.bus.feed("system", f"ready - mode {self.mode}, voice {self.voice.engine}, "
                                f"window http://127.0.0.1:{self.args.port}")
        self.voice.say("Voice bridge ready. Say let's talk when you need me." if not self.active
                       else "Voice bridge ready, and I'm listening.")
        chime(True)
        for audio, during in self.listener.utterances():
            try:
                segs, _ = self.stt_model.transcribe(audio, language="en", beam_size=5 if self.active else 1,
                                                    vad_filter=True, condition_on_previous_text=False)
                text = " ".join(s.text.strip() for s in segs).strip()
                if text:
                    self.handle(text, during)
            except Exception as e:
                self.bus.feed("error", f"speech handling failed: {e!r}")

    def reset_audio(self, why: str, quiet: bool = False):
        """Re-open speaker + mic so they follow Windows' current default devices (PortAudio caches the device
        list at start-up, so a full re-init is the only way to see a headset that slept or reconnected)."""
        with self.audio_lock:
            self.listener.stop()
            self.voice.close_stream()
            try:
                sd._terminate()
                sd._initialize()
            except Exception as e:
                self.bus.feed("error", f"audio re-init failed: {e!r}")
            try:
                self.voice.open_stream()
                self.listener.start()
            except Exception as e:
                self.bus.feed("error", f"could not reopen audio ({e!r}); will retry before the next reply")
                self.voice.last_reset = 0.0
                return
            self.voice.last_reset = time.time()
            msg = (f"audio reconnected ({why}): speaker {sd.query_devices(kind='output')['name']}, "
                   f"mic {sd.query_devices(kind='input')['name']}")
            if quiet:
                print("[system]", msg, flush=True)  # not in feed.log: would ping linked sessions every idle
            else:
                self.bus.feed("system", msg)


# ----------------------------------------------------------------------------- http (window + say.py)
APP: App | None = None


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _json(self, code: int, obj):
        body = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self):
        if self.path in ("/", "/index.html"):
            body = (HERE / "ui.html").read_bytes()
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
        elif self.path == "/events":
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            q = APP.bus.subscribe()
            try:
                APP.push_state(force=True)
                with APP.bus.lock:
                    hist = list(APP.bus.history)
                self.wfile.write(f"data: {json.dumps({'type': 'history', 'items': hist})}\n\n".encode())
                self.wfile.flush()
                while True:
                    try:
                        data = q.get(timeout=15)
                        self.wfile.write(f"data: {data}\n\n".encode())
                    except queue.Empty:
                        self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError, OSError):
                pass
            finally:
                APP.bus.unsubscribe(q)
        elif self.path == "/settings":
            self._json(200, APP.settings())
        elif self.path == "/state":
            self._json(200, {"state": APP.state, "mode": APP.mode, "active": APP.active,
                             "busy": APP.backend.busy, "voice": APP.voice.engine})
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(n) or b"{}")
        except Exception:
            return self._json(400, {"error": "bad json"})
        if self.path == "/say":  # used by say.py from the VS Code session (HERE mode)
            text = str(body.get("text", "")).strip()
            if text:
                APP.bus.feed("claude", text)
                APP.voice.say(text)
            APP.backends["here"].ack()  # progress updates count as "picked up" too
            if body.get("final", True):
                APP.backends["here"].done()
            return self._json(200, {"ok": True})
        if self.path == "/settings":
            APP.apply_settings({k: v for k, v in body.items() if k in DEFAULTS})
            return self._json(200, APP.settings())
        if self.path == "/control":
            return self._json(200, {"ok": APP.control(str(body.get("action", "")))})
        self._json(404, {"error": "not found"})


def open_window(port: int):
    """Native WebView2 window in its own process (no browser profile, no sign-in/sync prompts)."""
    pyw = Path(sys.executable).with_name("pythonw.exe")
    subprocess.Popen([str(pyw if pyw.exists() else sys.executable), str(HERE / "window.py"), str(port)],
                     cwd=str(HERE))


def main():
    global APP
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=["separate", "here"], default="separate")
    # Voice / model flags default to the saved voice_config.json (set from the window's settings panel).
    ap.add_argument("--tts", choices=["kokoro", "windows"], default=None,
                    help="kokoro = realistic voice, windows = Microsoft voice (lighter)")
    ap.add_argument("--voice", default=None,
                    help="realistic male voices: am_michael am_adam am_eric am_liam am_onyx am_fenrir am_puck "
                         "am_echo bm_george bm_lewis bm_daniel bm_fable")
    ap.add_argument("--windows-voice", default=None, help='e.g. "Microsoft David Desktop"')
    ap.add_argument("--speed", type=float, default=None)
    ap.add_argument("--model-size", default=None, help="speech model, e.g. small.en, base.en, or a models/stt folder")
    ap.add_argument("--device", default="cpu")
    ap.add_argument("--permission-mode", default="auto")
    ap.add_argument("--model", default=None, help="Claude model alias for the separate session")
    ap.add_argument("--new", action="store_true", help="don't resume the last separate session")
    ap.add_argument("--narrate", action=argparse.BooleanOptionalAction, default=True,
                    help="speak short tool updates ('Reading a file.')")
    ap.add_argument("--silence", type=float, default=1.6,
                    help="seconds of quiet that end what you're saying (raise if it cuts you off)")
    ap.add_argument("--max-utterance", type=float, default=120, help="longest single stretch of speech (s)")
    ap.add_argument("--cwd", default=None,
                    help="folder (or name from workspaces.json) the SEPARATE session works in; default: repo root")
    ap.add_argument("--sensitivity", type=float, default=3.0)
    ap.add_argument("--mic", default=None)
    ap.add_argument("--speaker", default=None)
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--here-timeout", type=float, default=45,
                    help="seconds before warning that the linked window hasn't acknowledged a request")
    ap.add_argument("--no-window", action="store_true")
    ap.add_argument("--start-active", action="store_true")
    args = ap.parse_args()
    if args.speaker and str(args.speaker).isdigit():
        args.speaker = int(args.speaker)

    (HERE / "voice_bridge.pid").write_text(str(os.getpid()))
    storage.prune_logs()  # keep transcripts for storage.json keep_logs_days; cap feed.log
    for f in (storage.CACHE / "tmp").glob("*"):  # stale temp audio from earlier runs
        try:
            f.unlink() if f.is_file() else None
        except OSError:
            pass
    APP = App(args)
    srv = ThreadingHTTPServer(("127.0.0.1", args.port), Handler)
    srv.daemon_threads = True
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    if not args.no_window:
        open_window(args.port)
    try:
        APP.run()
    finally:
        for b in APP.backends.values():
            b.shutdown()


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        pass
    finally:
        try:
            (HERE / "voice_bridge.pid").unlink()
        except Exception:
            pass
