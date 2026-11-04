# Storage manager for the voice bridge.
#   .\storage.ps1                         show sizes + free space
#   .\storage.ps1 -Clean                  clear disposable cache (pip, temp, HF) + old logs
#   .\storage.ps1 -Clean -All             ...and the window's browser data (close the window first)
#   .\storage.ps1 -MoveCache  "D:\VoiceCache"     move the cache folder (bridge must be stopped)
#   .\storage.ps1 -MoveModels "D:\VoiceModels"    move the models folder (bridge must be stopped)
#   .\storage.ps1 -KeepLogsDays 7         how many days of transcripts to keep
param([switch]$Clean, [switch]$All, [string]$MoveCache, [string]$MoveModels, [int]$KeepLogsDays = -1)
$ErrorActionPreference = 'Stop'
$VA = Split-Path -Parent $MyInvocation.MyCommand.Path
$py = "$VA\.venv\Scripts\python.exe"
$cfgPath = "$VA\storage.json"
$cfg = if (Test-Path $cfgPath) { Get-Content -Raw $cfgPath | ConvertFrom-Json } else { [pscustomobject]@{ cache_dir = ".cache"; models_dir = "models"; keep_logs_days = 14 } }
foreach ($k in 'cache_dir', 'models_dir', 'keep_logs_days') { if (-not ($cfg.PSObject.Properties.Name -contains $k)) {
    $cfg | Add-Member $k $(switch ($k) { 'cache_dir' { '.cache' } 'models_dir' { 'models' } default { 14 } }) } }
function Resolve-VA([string]$p) { if ([IO.Path]::IsPathRooted($p)) { $p } else { Join-Path $VA $p } }
function Save { $cfg | ConvertTo-Json | Set-Content -Encoding utf8 $cfgPath }
function Running { $f = "$VA\voice_bridge.pid"; (Test-Path $f) -and (Get-Process -Id (Get-Content $f) -ErrorAction SilentlyContinue) }

function Move-Area([string]$key, [string]$dest) {
    if (Running) { throw "Stop the voice bridge first (stop_voice.ps1) - its files are in use." }
    $src = Resolve-VA $cfg.$key
    $dest = [IO.Path]::GetFullPath($dest)
    if ($src -eq $dest) { "Already there."; return }
    New-Item -ItemType Directory -Force $dest | Out-Null
    if (Test-Path $src) {
        "Moving $src -> $dest ..."
        robocopy $src $dest /E /MOVE /NFL /NDL /NJH /NJS /NP | Out-Null
        if ($LASTEXITCODE -ge 8) { throw "robocopy failed ($LASTEXITCODE)" }
    }
    $cfg.$key = $dest; Save; "Saved: $key = $dest"
}

if ($MoveCache) { Move-Area 'cache_dir' $MoveCache }
if ($MoveModels) { Move-Area 'models_dir' $MoveModels }
if ($KeepLogsDays -ge 0) { $cfg.keep_logs_days = $KeepLogsDays; Save; "Keeping $KeepLogsDays days of transcripts." }
if ($Clean -and $All -and (Get-CimInstance Win32_Process | Where-Object { $_.CommandLine -match 'window\.py' })) {
    Write-Host "The voice window is open - skipping its browser data (close the window to clear it too)." -ForegroundColor Yellow
    $All = $false }
$args2 = @("$VA\storage.py") + $(if ($Clean) { '--clean' }) + $(if ($All) { '--all' })
& $py @args2
