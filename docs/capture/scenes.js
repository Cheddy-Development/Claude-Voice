// Injected before ui.html's own script: replaces the live bridge with a scripted one, so the real UI
// can be rendered in any state (no microphone, no sound, no bridge needed). Scene = location.hash.
(() => {
  const VOICE = 'Realistic (am_michael)';
  const T = (ts, kind, text) => ({ type: 'feed', ts, kind, text });
  const base = [
    T('09:41:02', 'system', 'ready - voice Realistic (am_michael), window http://127.0.0.1:8765'),
    T('09:41:03', 'system', 'LINKED to the Claude session in D:/Projects/my-app'),
  ];
  const talk = [
    ...base,
    T('09:41:20', 'system', 'listening (heard: "Let\'s talk.")'),
    T('09:41:31', 'ask', 'What does the sales report folder have in it?'),
  ];
  const working = [...talk,
    T('09:41:33', 'claude', 'Let me check the reports folder.'),
  ];
  const answered = [...working,
    T('09:41:39', 'claude', 'It has 12 reports. The newest is the weekly sales summary from Monday. Want me to open it?'),
  ];
  const S = {
    asleep:    { st: 'sleeping', active: false, feed: base, mic: 0.0005 },
    listening: { st: 'listening', active: true, feed: [...base, T('09:41:20', 'system', 'listening (heard: "Let\'s talk.")')], mic: 0.002 },
    hearing:   { st: 'hearing', active: true, feed: [...base, T('09:41:20', 'system', 'listening (heard: "Let\'s talk.")')], mic: 0.05 },
    working:   { st: 'thinking', active: true, feed: working, mic: 0.001 },
    speaking:  { st: 'speaking', active: true, feed: answered, out: 0.07 },
    settings:  { st: 'listening', active: true, feed: base, mic: 0.002, settings: true },
    lite:      { st: 'speaking', active: true, feed: answered, out: 0.07, orb: 'off' },
  };
  const name = (location.hash || '#asleep').slice(1);
  const sc = S[name] || S.asleep;
  try { localStorage.setItem('orbMode', sc.orb || 'anim'); } catch {}

  const SETTINGS = {
    tts: 'kokoro', tts_model: 'kokoro/kokoro-v1.0.onnx', voice: 'am_michael', windows_voice: 'Microsoft David Desktop',
    speed: 1.05, stt: 'small.en', engine: VOICE,
    options: {
      tts_models: [{ id: 'kokoro/kokoro-v1.0.onnx', label: 'kokoro / kokoro-v1.0', mb: 325 }],
      voices: ['am_michael', 'am_adam', 'am_eric', 'am_liam', 'am_onyx', 'bm_george', 'bm_lewis', 'bm_daniel'],
      windows_voices: ['Microsoft David Desktop', 'Microsoft Zira Desktop'],
      stt: [{ id: 'small.en', label: 'small.en', mb: 486 }],
    },
    storage: {
      'cache (disposable)': { path: 'D:\\Tools\\ClaudeVoice\\.cache', mb: 12.4 },
      models: { path: 'D:\\Tools\\ClaudeVoice\\models', mb: 839.8 },
      free_gb: { 'models drive': 27.4 },
    },
  };
  window.fetch = async () => ({ ok: true, json: async () => SETTINGS });

  window.EventSource = class {
    constructor() {
      setTimeout(() => {
        this.onopen && this.onopen();
        const send = d => this.onmessage && this.onmessage({ data: JSON.stringify(d) });
        send({ type: 'history', items: sc.feed });
        send({ type: 'state', state: sc.st, mode: 'here', active: sc.active, busy: sc.st === 'thinking', voice: VOICE });
        let k = 0;
        setInterval(() => {  // speech-like level wobble
          k += 1;
          const w = 0.55 + 0.45 * Math.abs(Math.sin(k * 0.37) * Math.sin(k * 0.11 + 1));
          if (sc.out) send({ type: 'level', ch: 'out', v: sc.out * w });
          send({ type: 'level', ch: 'mic', v: (sc.mic || 0) * w });
        }, 50);
        if (sc.settings) setTimeout(() => document.querySelector('#gear').click(), 50);
      }, 0);
    }
    close() {}
  };
})();
