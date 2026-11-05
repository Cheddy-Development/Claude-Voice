<!-- claude-voice:start (managed by setup_voice.ps1; re-run setup to update) -->
# Voice link (applies in every folder)

The user has a voice bridge at `{VA}` (call it VA). When the user says **"open voice"**, **"link voice"**,
**"connect to voice"**, or **"start voice here"**:

1. If it isn't running (`curl -s http://127.0.0.1:8765/state` fails), start it in the background:
   `powershell -ExecutionPolicy Bypass -File "VA/start_voice.ps1" --mode here --start-active`.
   Then (whether it was running or not) claim it for this session and show its window (the window
   action does nothing if one is already open):
   `"VA/.venv/Scripts/python.exe" "VA/say.py" --control "link:<absolute path of this folder>"`
   `"VA/.venv/Scripts/python.exe" "VA/say.py" --control window`
   If the window action fails (an older bridge), open it directly:
   `"VA/.venv/Scripts/pythonw.exe" "VA/window.py"`.
   "Show voice" or "open the voice window" means just the window action.
2. Arm a Monitor (`timeout_ms: 1800000`, re-arm on expiry):
   `tail -n0 -F "VA/logs/feed.log" | grep --line-buffered -E " (ASK|YOU|CLAUDE|ERROR|CANCEL|SYSTEM) "`
3. Every `ASK <text>` line is the user speaking to YOU. **First, right away**, send a silent acknowledgement so the
   bridge knows you picked it up: `"VA/.venv/Scripts/python.exe" "VA/say.py" --control ack`.
   Then do the work in THIS folder and answer out loud:
   `"VA/.venv/Scripts/python.exe" "VA/say.py" "<1-3 short spoken sentences>"`. Use `--progress` for
   interim updates. Plain speech only. Always finish with a non-progress say.
4. Only one session answers ASK lines at a time. When the feed shows `SYSTEM LINKED to the Claude session in <folder>`
   and that folder is not yours, another window has taken over. Stop your Monitor and don't answer anything more.

"Unlink voice" means stop the Monitor (the bridge keeps running). "Stop voice" or "close voice" means run
`VA/stop_voice.ps1`. To switch the voice when typed (spoken requests are handled by the bridge itself), run
`"VA/.venv/Scripts/python.exe" "VA/say.py" --settings tts=windows` (Microsoft, lighter) or `tts=kokoro` (realistic).
{DISKNOTE}
<!-- claude-voice:end -->
