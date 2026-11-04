"""Offline self-test: male voice speaks -> WAV -> Whisper -> wake/end detection."""
import os, subprocess, sys, wave
from pathlib import Path
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import numpy as np
import voice_bridge as vb

wav = HERE / ".cache" / "tmp" / "selftest.wav"
ps = (f"Add-Type -AssemblyName System.Speech; $s=New-Object System.Speech.Synthesis.SpeechSynthesizer; "
      f"$s.SelectVoice('Microsoft David Desktop'); "
      f"$s.SetOutputToWaveFile('{wav}', (New-Object System.Speech.AudioFormat.SpeechAudioFormatInfo 16000,([System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen),([System.Speech.AudioFormat.AudioChannel]::Mono))); "
      f"$s.Speak(\"Okay, let's talk. Check how many reports are live. Okay, let's end.\"); $s.Dispose()")
subprocess.run(["powershell", "-NoProfile", "-Command", ps], check=True)
with wave.open(str(wav)) as w:
    audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).astype(np.float32) / 32768

from faster_whisper import WhisperModel
m = WhisperModel(sys.argv[1] if len(sys.argv) > 1 else "small.en", device="cpu", compute_type="int8",
                 download_root=str(HERE / "models"))
import time; t = time.time()
segs, _ = m.transcribe(audio, language="en", beam_size=5, vad_filter=True)
text = " ".join(s.text.strip() for s in segs)
print(f"transcript ({time.time()-t:.1f}s for {len(audio)/16000:.1f}s audio): {text}")
print("wake found:", vb.find_phrase(text, vb.WAKE) >= 0, "| end found:", vb.find_phrase(text, vb.END) >= 0)
print("claude bin:", vb.find_claude())
