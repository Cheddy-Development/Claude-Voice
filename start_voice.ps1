# Start the voice bridge (say "let's talk" to wake, "okay, let's end" to stop).
# Extra args pass through, e.g.:  .\start_voice.ps1 --mode here --start-active
# Cache/model locations come from storage.json (see storage.ps1).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $here "voice_bridge.pid"
if (Test-Path $pidFile) {
    $old = Get-Content $pidFile
    if (Get-Process -Id $old -ErrorAction SilentlyContinue) { "Voice bridge already running (PID $old)."; exit 0 }
}
& (Join-Path $here ".venv\Scripts\python.exe") -u (Join-Path $here "voice_bridge.py") @args
