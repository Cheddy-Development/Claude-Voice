# Voice bridge: talk to Claude Code hands-free

The bridge opens a small window with an animated orb. The orb reacts to your voice (cyan), to Claude's voice
(amber) and to thinking (violet, with rotating arcs). Below it is a live feed of what you said, the tools
Claude ran, and what it answered.

| Say | What happens |
|---|---|
| **"Let's talk"** | Rising chime: it's listening. You can chain a request: "Let's talk, check the inventory report." |
| anything | Short acknowledgement, then Claude works and **speaks as it goes**: a one-line plan, brief updates, the answer. |
| **"Stop"** / "wait" / "hold on" | Cuts the voice off mid-sentence. |
| **"Cancel that"** | Aborts the task Claude is working on. |
| more talk while it works | Queued into the same live session ("Got it, I'll add that"). |
| **"Talk to VS Code"** | HERE mode: requests go to the VS Code Claude session. |
| **"Separate session"** | SEPARATE mode (default): the bridge's own persistent Claude session. |
| "New conversation" | Fresh Claude context. |
| **"Okay, let's end"** | Falling chime: it stops listening. Running work still finishes. |

While it's asleep, speech is transcribed **locally only** to spot "let's talk". Nothing is logged or sent.
The window buttons do the same things.

## Voice and model settings

Click the **gear icon** in the window. Your choice is saved to `voice_config.json` and used on every launch.

- **Voice engine:** *Realistic* (Kokoro, natural sounding) or *Microsoft (light)* (David/Zira, built into Windows).
  Switching to Microsoft frees the realistic model's memory. Sentences take about 0.5 s to generate instead of
  1-2 s. You can also just say **"switch to the Microsoft voice"** or **"switch to the realistic voice"**,
  or type `say.py --settings tts=windows`.
- **Speaker, speed, voice model, speech model:** dropdowns. The model lists are **rescanned each time you open
  the panel**.
- **Adding or removing models:** see [models/README.txt](models/README.txt). Drop a folder into `models/tts/<name>/`
  (one `.onnx` plus a `voices*.bin`) or `models/stt/<name>/` (a Whisper `model.bin`), or run
  `get_model.py base.en`. Delete the folder to remove the model.

## Storage: cache and models folders

`storage.json` sets where the bulky files live (missing file means the defaults below). Paths can be relative to
this folder or absolute, and on any drive.

| Folder | Default | What it holds | Safe to delete? |
|---|---|---|---|
| `cache_dir` | `.cache` | pip downloads, temp audio, window data, Hugging Face metadata (~0-200 MB) | Yes, always |
| `models_dir` | `models` | voice + speech models (~850 MB) | Only models you don't use |
| `.venv` | (fixed) | Python packages (~340 MB) | Re-run setup to rebuild |
| `logs` | (fixed) | transcripts, kept `keep_logs_days` (14); feed.log capped at ~5 MB | Yes |

```powershell
.\storage.ps1                          # sizes + free space
.\storage.ps1 -Clean                   # empty the cache + prune old transcripts (or Settings > "Clear cache")
.\storage.ps1 -Clean -All              # ...also the window's data (close the window first)
.\storage.ps1 -MoveModels "D:\Voice\models"   # move models to another drive (stop the bridge first)
.\storage.ps1 -MoveCache  "D:\Voice\cache"
.\storage.ps1 -KeepLogsDays 7
```

On every launch the bridge also clears stale temp audio, prunes old transcripts and caps feed.log.
Setup asks where to put models and cache, and it empties pip's download cache after installing.

## Install on another PC

1. Here, run `.\make_package.ps1` to build `dist\ClaudeVoice.zip` (~40 KB). Add `-WithModels` for an offline zip
   (~1 GB).
2. On the other PC, unzip it to a drive with about 2 GB free and double-click **`setup_voice.bat`**. It:
   - finds Python 3.10-3.13 (or offers to install it),
   - installs the packages into `.venv` in that folder,
   - asks before each model download,
   - finds Claude Code,
   - teaches every Claude session "open voice" (a marked block in `%USERPROFILE%\.claude\CLAUDE.md`),
   - creates a **Claude Voice** desktop shortcut.
3. Then, in any Claude Code chat, type **"open voice"**. Or double-click the shortcut.

Re-running setup is safe. `setup_voice.ps1 -LinkOnly` only refreshes the instructions and the shortcut.

## Run

```powershell
.\start_voice.ps1                  # or tell Claude: "start voice"  (see CLAUDE.md, Voice Mode)
.\start_voice.ps1 --mode here      # route to the VS Code session
.\stop_voice.ps1                   # stops everything, including a running Claude task
```

Flags: `--voice am_adam` (male voices: am_michael, am_adam, am_eric, am_liam, am_onyx, am_fenrir,
bm_george, bm_lewis, bm_daniel), `--speed 1.15`, `--no-narrate`, `--model sonnet`,
`--permission-mode acceptEdits`, `--new`, `--model-size base.en`, `--mic 1`, `--no-window`.

## The two modes, and how sessions stay linked

- **SEPARATE:** one `claude -p --input-format stream-json` process stays open. That gives fast, multi-turn
  answers, and Claude's text is spoken as it streams. The session id is saved to `logs/separate_session.txt` and
  resumed next time. Open the full session with `claude --resume <id>`.
- **HERE:** your words become `ASK` lines in `logs/feed.log`. The VS Code session follows that file with
  Monitor, does the work, and replies with `say.py "..."`, which comes out as speech.
- **Either mode:** every event goes to `logs/feed.log` (one line each, for Monitor) and to
  `logs/voice_YYYYMMDD.md` (readable). Whatever Claude session you're in can follow along.

HTTP on `127.0.0.1:8765`: `GET /` is the window, `GET /events` is the SSE stream, `GET /state`,
`POST /say {text, final}`, and `POST /control {action}` (wake, sleep, cancel, stop_speaking, new,
mode:here, mode:separate).

## Pipeline

1. **Microphone:** `sounddevice` at 16 kHz, with an energy-based detector that spots when you start and stop
   speaking.
2. **Speech to text:** `faster-whisper` small.en on the CPU (int8).
3. **Commands:** wake, end and stop phrases are handled by the bridge; everything else goes to Claude.
4. **Voice:** Kokoro (`am_michael`). It synthesizes one sentence ahead while the current one plays, so the voice
   can start and stop instantly.
5. **Echo guard:** anything heard *while the bridge is talking* only counts if it's a short stop command, so it
   never answers itself.

## Disk (all on G:, in this folder)

`.venv` ~400 MB · `models/` Whisper small.en ~460 MB + Kokoro ~340 MB · `.cache/` (pip, temp, and the Edge
window profile). C: is nearly full. Do not install there.
Optional GPU: `--device cuda` needs `nvidia-cublas-cu12` + `nvidia-cudnn-cu12` (~1 GB+, not installed).
