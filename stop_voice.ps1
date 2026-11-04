# Stop the voice bridge completely (the mic is released).
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pidFile = Join-Path $here "voice_bridge.pid"
if (-not (Test-Path $pidFile)) { "Voice bridge is not running."; exit 0 }
$p = Get-Content $pidFile
# /T kills the whole tree, including any Claude task still running in the background.
taskkill /PID $p /T /F | Out-Null
if ($LASTEXITCODE -eq 0) { "Stopped voice bridge (PID $p) and any running Claude task." } else { "Process $p not found." }
Remove-Item $pidFile -ErrorAction SilentlyContinue
