"""Download an extra speech-recognition (Whisper) model into the models folder so it shows up in Settings.

    .venv\\Scripts\\python.exe get_model.py base.en        # ~150 MB, faster, a bit less accurate
    .venv\\Scripts\\python.exe get_model.py medium.en      # ~1.5 GB, slower, more accurate
    .venv\\Scripts\\python.exe get_model.py distil-large-v3

To remove a model, delete its folder in the models folder (models--Systran--faster-whisper-<name>).
Realistic voice models: put a folder in <models>/tts/<name>/ containing one .onnx and one voices*.bin.
The models folder is set in storage.json (default: models/ here).
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import storage  # noqa: E402

storage.apply_env()
if len(sys.argv) != 2:
    sys.exit(__doc__)
from faster_whisper import WhisperModel  # noqa: E402

name = sys.argv[1]
print(f"Downloading speech model {name} into {storage.MODELS} ...")
WhisperModel(name, device="cpu", compute_type="int8", download_root=str(storage.MODELS))
print("Done. Pick it in the window: Settings > Speech model.")
