MODELS - add or remove as you like; the Settings panel (gear icon) rescans every time you open it,
and your choice is saved to voice_config.json and used on every launch.

Realistic voices (text-to-speech)
  models/kokoro/                 the built-in one (kokoro-v1.0.onnx + voices-v1.0.bin)
  models/tts/<any-name>/         drop in another: exactly one voices*.bin plus one or more *.onnx
                                 e.g. kokoro-v1.0.int8.onnx (88 MB, lighter) from
                                 https://github.com/thewh1teagle/kokoro-onnx/releases
  The Microsoft voices (David, Zira, ...) are built into Windows: no files, almost no RAM/CPU.

Speech recognition (speech-to-text, Whisper)
  models/models--Systran--faster-whisper-<name>/   downloaded with:  get_model.py <name>
                                                   (tiny.en, base.en, small.en, medium.en, distil-large-v3)
  models/stt/<any-name>/                           any CTranslate2 Whisper folder containing model.bin

Delete a folder to remove that model. Keep at least one speech model (small.en is the default).
