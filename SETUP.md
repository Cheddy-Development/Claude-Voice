# Claude Voice: setup in 5 minutes

Talk to Claude Code out loud, and it answers out loud.

**Prefer pictures?** Open **Setup Guide.html**: the same steps with screenshots and a short narrated video.

## Before you start

- Windows 10 or 11, with a microphone and speakers or headphones.
- Claude Code installed and signed in (the VS Code extension or the CLI).
- About 2 GB free on a drive **other than C:** (for example D:).

## 1. Put the folder on another drive

Unzip `ClaudeVoice.zip`, or download the repo, to a folder on D: or any other drive. **Don't use C:.**
Everything installs inside this folder.

Example: `D:\Tools\ClaudeVoice`

## 2. Run the setup

Double-click **`setup_voice.bat`**. A black window opens and shows its progress as `[1/8] ... [8/8]`.

When it asks a question, **press Enter** to accept the default. That's the right choice for most people.

| It asks | What to do |
|---|---|
| Folder for MODELS | **Enter**. Or type a folder on another drive, like `E:\VoiceModels`. Never use C:. |
| Folder for CACHE | **Enter**. Or type a folder on another drive. Never use C:. |
| Install Python 3.11? (only if missing) | **Y** |
| Download the realistic voice? | **Enter** (yes, ~340 MB). Say **n** to use the lighter built-in Microsoft voice. |
| Download the speech model now? | **Enter** (yes, ~480 MB) |
| Create a desktop shortcut? | **Enter** (yes) |

The package step downloads about 350 MB and takes 3-10 minutes, so wait for it.
It's finished when it shows **`[8/8] 100% Done`**. You can then close the window.

## 3. Start talking

1. In any Claude Code chat, type **`open voice`**. A small window with an animated orb opens.
2. Say **"let's talk"**, then ask for anything.
3. Say **"okay, let's end"** when you want it to stop listening.

| Say | What happens |
|---|---|
| "stop" / "wait" | It stops talking. |
| "cancel task" | Claude drops what it's doing. |
| "switch to the Microsoft voice" | Lighter voice that uses less memory. |

To turn it off completely, type **`close voice`** in Claude Code.

## If something goes wrong

- **The setup closed with an error:** check your internet connection, then double-click `setup_voice.bat` again.
  It continues from where it stopped.
- **No sound:** check that your speakers or headphones are the Windows default, then type `close voice` and
  `open voice`.
- **It doesn't hear you:** check that your microphone is the Windows default input.
- **No window:** type `open voice` again.
