# Build a zip to copy to another PC: unzip anywhere, double-click setup_voice.bat (it asks where models/cache go).
#   .\make_package.ps1               small zip (~50 KB) - models download during setup
#   .\make_package.ps1 -WithModels   also bundles the voice + speech models (~850 MB) for offline installs
param([switch]$WithModels)
$ErrorActionPreference = 'Stop'
$VA = Split-Path -Parent $MyInvocation.MyCommand.Path
$dist = Join-Path $VA "dist"
$stage = Join-Path $dist "_stage\ClaudeVoice"
if (Test-Path "$dist\_stage") { Remove-Item "$dist\_stage" -Recurse -Force }
New-Item -ItemType Directory -Force $stage, "$stage\models" | Out-Null

$files = 'voice_bridge.py', 'storage.py', 'ui.html', 'window.py', 'say.py', 'get_model.py', 'selftest.py',
         'start_voice.ps1', 'stop_voice.ps1', 'storage.ps1', 'setup_voice.bat', 'setup_voice.ps1',
         'requirements.txt', 'README.md', 'claude_voice_instructions.md'
foreach ($f in $files) { Copy-Item (Join-Path $VA $f) $stage }
Copy-Item "$VA\models\README.txt" "$stage\models\"
# Not shipped (per-machine): .venv, cache, logs, storage.json, voice_config.json.

if ($WithModels) {
    $st = if (Test-Path "$VA\storage.json") { Get-Content -Raw "$VA\storage.json" | ConvertFrom-Json } else { $null }
    $M = if ($st -and $st.models_dir) { $st.models_dir } else { "models" }
    if (-not [IO.Path]::IsPathRooted($M)) { $M = Join-Path $VA $M }
    Copy-Item "$M\kokoro" "$stage\models\kokoro" -Recurse
    # copy whisper caches with links resolved (blobs are shared files on this PC)
    Get-ChildItem $M -Directory -Filter "models--Systran--faster-whisper-*" | ForEach-Object {
        Get-ChildItem "$($_.FullName)\snapshots" -Directory | ForEach-Object {
            $dst = "$stage\models\stt\" + ($_.Parent.Parent.Name -replace '^models--Systran--faster-(distil-)?whisper-', '$1')
            New-Item -ItemType Directory -Force $dst | Out-Null
            Get-ChildItem $_.FullName -File | ForEach-Object { [IO.File]::Copy($_.FullName, (Join-Path $dst $_.Name), $true) }
        }
    }
}
$zip = Join-Path $dist ($(if ($WithModels) { "ClaudeVoice-with-models.zip" } else { "ClaudeVoice.zip" }))
if (Test-Path $zip) { Remove-Item $zip -Force }
Compress-Archive -Path $stage -DestinationPath $zip -CompressionLevel Optimal
Remove-Item "$dist\_stage" -Recurse -Force
"{0}  ({1:N1} MB)" -f $zip, ((Get-Item $zip).Length / 1MB)
