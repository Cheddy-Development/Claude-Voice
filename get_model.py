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
from faster_whisper.utils import _MODELS  # noqa: E402
from huggingface_hub import snapshot_download  # noqa: E402

name = sys.argv[1]
repo = name if "/" in name else _MODELS.get(name)
if not repo:
    sys.exit(f"Unknown model {name!r}. Try one of: {', '.join(_MODELS)}")
print(f"Downloading speech model {name} into {storage.MODELS} (progress below) ...")
# Same files and folder layout faster-whisper uses, but with the progress bars it normally hides.
snapshot_download(repo, cache_dir=str(storage.MODELS),
                  allow_patterns=["config.json", "preprocessor_config.json", "model.bin",
                                  "tokenizer.json", "vocabulary.*"])
print("Done. Pick it in the window: Settings > Speech model.")
