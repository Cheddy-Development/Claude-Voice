# One-time setup of the Claude voice bridge on a Windows PC.
# Run via setup_voice.bat (double-click). Installs everything INSIDE this folder - put the folder on a
# drive with ~2 GB free. Re-running is safe: it skips what is already done.
#   -Yes        answer yes to every prompt
#   -LinkOnly   only (re)write the Claude instructions + desktop shortcut (no installs/downloads)
param([switch]$Yes, [switch]$LinkOnly)
$ErrorActionPreference = 'Stop'
$VA = Split-Path -Parent $MyInvocation.MyCommand.Path
function Ask([string]$q) { if ($Yes) { return $true }; $a = Read-Host "$q [Y/n]"; return ($a -eq '' -or $a -match '^[yY]') }
$script:stepN = 0; $script:stepTotal = $(if ($LinkOnly) { 2 } else { 8 }); $script:t0 = Get-Date
function Step([string]$t) {
    # "== [3/8] [######..............]  37%  Python packages   (2m 10s so far)"
    $script:stepN++
    $done = ($script:stepN - 1) / $script:stepTotal
    $w = 20; $fill = [int][math]::Round($done * $w)
    $bar = ('#' * $fill) + ('.' * ($w - $fill))
    $el = (Get-Date) - $script:t0
    Write-Host ""
    Write-Host ("== [{0}/{1}] [{2}] {3,3}%  {4}" -f $script:stepN, $script:stepTotal, $bar, [int]($done * 100), $t) -ForegroundColor Cyan -NoNewline
    Write-Host ("   ({0}m {1:00}s so far)" -f [int]$el.TotalMinutes, $el.Seconds) -ForegroundColor DarkGray
}
function Ok([string]$t) { Write-Host "   $t" -ForegroundColor Green }
function Warn([string]$t) { Write-Host "   $t" -ForegroundColor Yellow }

Write-Host "Claude Voice setup  ->  $VA" -ForegroundColor White
$drv = (Get-Item $VA).PSDrive
$free = [math]::Round($drv.Free / 1GB, 1)
$cFree = [math]::Round((Get-PSDrive C).Free / 1GB, 1)

if (-not $LinkOnly) {
    Step "Storage (models ~850 MB, packages ~350 MB, cache ~200 MB)"
    Get-PSDrive -PSProvider FileSystem | Where-Object { $_.Free -gt 0 } |
        ForEach-Object { "   {0}:  {1,7:N1} GB free" -f $_.Name, ($_.Free / 1GB) }
    "   This folder is on $($drv.Name): ($free GB free). Python packages always live here (.venv)."
    $st = if (Test-Path "$VA\storage.json") { Get-Content -Raw "$VA\storage.json" | ConvertFrom-Json } else { $null }
    $models = if ($st -and $st.models_dir) { $st.models_dir } else { "models" }
    $cache = if ($st -and $st.cache_dir) { $st.cache_dir } else { ".cache" }
    if (-not $Yes) {
        $a = Read-Host "   Folder for MODELS (Enter = $models)"; if ($a) { $models = $a }
        $a = Read-Host "   Folder for CACHE  (Enter = $cache)"; if ($a) { $cache = $a }
    }
    $abs = { param($p) if ([IO.Path]::IsPathRooted($p)) { $p } else { Join-Path $VA $p } }
    $M = & $abs $models; $C = & $abs $cache
    [pscustomobject]@{ cache_dir = $cache; models_dir = $models; keep_logs_days = $(if ($st -and $st.keep_logs_days) { $st.keep_logs_days } else { 14 }) } |
        ConvertTo-Json | Set-Content -Encoding utf8 "$VA\storage.json"
    Ok "models -> $M"; Ok "cache  -> $C   (disposable; storage.ps1 -Clean empties it)"
    $mFree = [math]::Round((Get-PSDrive ([IO.Path]::GetPathRoot([IO.Path]::GetFullPath($M)).Substring(0, 1))).Free / 1GB, 1)
    if ($mFree -lt 1.5) { Warn "Only $mFree GB free for models."; if (-not (Ask "Continue anyway?")) { exit 1 } }

    # every cache goes to the cache folder (never the C: profile)
    $env:PIP_CACHE_DIR = "$C\pip"; $env:TEMP = "$C\tmp"; $env:TMP = $env:TEMP; $env:HF_HOME = "$C\hf"
    foreach ($d in "$C\pip", "$C\tmp", "$C\hf", "$M\kokoro", "$M\tts", "$M\stt", "$VA\logs") {
        New-Item -ItemType Directory -Force $d | Out-Null }
    if (-not (Test-Path "$M\README.txt") -and (Test-Path "$VA\models\README.txt")) { Copy-Item "$VA\models\README.txt" $M }

    Step "Python 3.10 - 3.13"
    $py = $null
    foreach ($c in 'py -3.12', 'py -3.11', 'py -3.13', 'py -3.10', 'python') {
        $parts = $c.Split(' '); $rest = @($parts | Select-Object -Skip 1)
        try { $okv = & $parts[0] @rest -c "import sys;print(int((3,10)<=sys.version_info[:2]<(3,14)))" 2>$null } catch { $okv = $null }
        if ("$okv".Trim() -eq '1') { $py = $parts; break }
    }
    if (-not $py) {
        Warn "No suitable Python found."
        if ((Get-Command winget -ErrorAction SilentlyContinue) -and (Ask "Install Python 3.11 with winget (~100 MB, per-user)?")) {
            winget install -e --id Python.Python.3.11 --scope user --accept-package-agreements --accept-source-agreements
            $py = @("$env:LOCALAPPDATA\Programs\Python\Python311\python.exe")
        } else { Write-Host "Install Python 3.11 from https://www.python.org/downloads/ (tick 'Add to PATH'), then re-run."; exit 1 }
    }
    Ok "using: $($py -join ' ')"

    Step "Python packages (into .venv here)"
    if (-not (Test-Path "$VA\.venv\Scripts\python.exe")) {
        $rest = @($py | Select-Object -Skip 1); & $py[0] @rest -m venv "$VA\.venv" }
    Write-Host "   updating pip ..." -ForegroundColor DarkGray
    & "$VA\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check -q --upgrade pip
    # one package at a time so you can see how far along it is; pip draws a download bar for each file
    $pkgs = @(Get-Content "$VA\requirements.txt" | ForEach-Object { $_.Trim() } | Where-Object { $_ -and -not $_.StartsWith('#') })
    Write-Host "   ~350 MB in total; usually 3-10 minutes. Download bars appear below." -ForegroundColor DarkGray
    $i = 0
    foreach ($p in $pkgs) {
        $i++; $ts = Get-Date
        Write-Host ""
        Write-Host ("   ({0}/{1}) installing {2} ..." -f $i, $pkgs.Count, $p) -ForegroundColor White
        & "$VA\.venv\Scripts\python.exe" -m pip install --disable-pip-version-check --progress-bar on $p
        if ($LASTEXITCODE -ne 0) { throw "pip install of $p failed - check the internet connection and re-run setup_voice.bat" }
        Ok ("({0}/{1}) {2} done in {3:N0}s" -f $i, $pkgs.Count, $p, ((Get-Date) - $ts).TotalSeconds)
    }
    & "$VA\.venv\Scripts\python.exe" -m pip cache purge 2>$null | Out-Null  # downloads no longer needed
    Ok "packages installed (pip download cache emptied)"

    Step "Realistic voice model (Kokoro, ~340 MB)"
    $k = "$M\kokoro"
    $base = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0"
    if ((Test-Path "$k\kokoro-v1.0.onnx") -and (Get-Item "$k\kokoro-v1.0.onnx").Length -gt 300MB) { Ok "already present" }
    elseif (Ask "Download the realistic voice? (No = use the built-in Microsoft voice)") {
        $files = [ordered]@{ 'voices-v1.0.bin' = '27 MB'; 'kokoro-v1.0.onnx' = '310 MB' }; $i = 0
        foreach ($f in $files.Keys) {
            $i++
            Write-Host ("   ({0}/2) downloading {1} ({2}); curl shows % done, speed and time left:" -f $i, $f, $files[$f]) -ForegroundColor White
            curl.exe -L --fail --retry 5 --retry-delay 3 --speed-limit 20000 --speed-time 30 -o "$k\$f" "$base/$f"
            if ($LASTEXITCODE -ne 0) { Warn "download of $f failed - get it in a browser from $base/$f and save it to $k" }
        }
    } else { '{"tts": "windows"}' | Set-Content -Encoding ascii "$VA\voice_config.json"; Ok "will use the Microsoft voice" }

    Step "Speech recognition model (Whisper small.en, ~480 MB)"
    if (Get-ChildItem $M -Directory -Filter "models--Systran--faster-whisper-*" -ErrorAction SilentlyContinue) { Ok "already present" }
    elseif (Ask "Download it now? (No = it downloads on first launch)") {
        & "$VA\.venv\Scripts\python.exe" "$VA\get_model.py" small.en
    }

    Step "Claude Code"
    $claude = Get-ChildItem "$env:USERPROFILE\.vscode\extensions" -Directory -Filter "anthropic.claude-code*" -ErrorAction SilentlyContinue |
        ForEach-Object { Join-Path $_.FullName "resources\native-binary\claude.exe" } | Where-Object { Test-Path $_ } | Select-Object -Last 1
    if (-not $claude) { $claude = (Get-Command claude -ErrorAction SilentlyContinue).Source }
    if ($claude) { Ok "found: $claude" } else { Warn "Claude Code not found. Install the Claude Code VS Code extension (or CLI) and sign in, then you're set." }
}

Step "Teach Claude 'open voice' (all folders)"
$md = "$env:USERPROFILE\.claude\CLAUDE.md"
New-Item -ItemType Directory -Force (Split-Path $md) | Out-Null
$vaFwd = $VA -replace '\\', '/'
$note = if ($cFree -lt 10) { "C: is nearly full ($cFree GB free). Never download or install anything to C:." } else { "" }
$block = (Get-Content -Raw -Encoding utf8 "$VA\claude_voice_instructions.md").Replace('{VA}', $vaFwd).Replace('{DISKNOTE}', $note)
$old = if (Test-Path $md) { Get-Content -Raw -Encoding utf8 $md } else { "" }
if ($old -match '(?s)<!-- claude-voice:start.*?<!-- claude-voice:end -->') {
    $new = [regex]::Replace($old, '(?s)<!-- claude-voice:start.*?<!-- claude-voice:end -->', [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block.Trim() })
} elseif ($old -match '(?s)# Voice link \(applies in every folder\).*?Never download or install anything to C:\.') {
    # upgrade the older unmarked block written by hand
    $new = [regex]::Replace($old, '(?s)# Voice link \(applies in every folder\).*?Never download or install anything to C:\.', [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block.Trim() })
} else { $new = ($old.TrimEnd() + "`r`n`r`n" + $block.Trim()).Trim() }
[IO.File]::WriteAllText($md, $new + "`r`n", (New-Object Text.UTF8Encoding $false))
Ok "updated $md"

Step "Desktop shortcut"
$lnk = Join-Path ([Environment]::GetFolderPath('Desktop')) "Claude Voice.lnk"
if ((Test-Path $lnk) -or (Ask "Create a 'Claude Voice' shortcut on the desktop?")) {
    $s = (New-Object -ComObject WScript.Shell).CreateShortcut($lnk)
    $s.TargetPath = "$env:WINDIR\System32\WindowsPowerShell\v1.0\powershell.exe"
    $s.Arguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Minimized -File `"$VA\start_voice.ps1`""
    $s.WorkingDirectory = $VA
    $s.IconLocation = "$env:WINDIR\System32\SndVol.exe,0"
    $s.Description = "Talk to Claude Code by voice"
    $s.Save()
    Ok "created $lnk"
}

$el = (Get-Date) - $script:t0
Write-Host ""
Write-Host ("== [{0}/{0}] [{1}] 100%  Done in {2}m {3:00}s" -f $script:stepTotal, ('#' * 20), [int]$el.TotalMinutes, $el.Seconds) -ForegroundColor Green
Write-Host "  Start:  double-click 'Claude Voice' on the desktop, or in any Claude Code chat type:  open voice"
Write-Host "  Talk:   say 'let's talk' ... 'okay, let's end'.   Settings: gear icon in the window."
