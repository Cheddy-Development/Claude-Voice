"""Native window for the voice bridge (WebView2, no browser profile, no sign-in, no sync).

    .venv\\Scripts\\pythonw.exe window.py [port]
Re-run it any time to reopen the window; closing it does not stop the bridge.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import storage  # noqa: E402

storage.apply_env()
import webview  # noqa: E402

port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
webview.create_window("Claude Voice", f"http://127.0.0.1:{port}", width=460, height=780,
                      min_size=(360, 520), background_color="#0b0d12")
webview.start(private_mode=True, storage_path=str(storage.CACHE / "webview"))  # window data -> cache folder
