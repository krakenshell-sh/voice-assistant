# Voice Assistant — Arch Linux

A terminal-based voice assistant with a CAVA-style real-time FFT spectrum
visualizer, text-to-speech feedback, and automatic offline STT fallback.

```
╔════════════════════════════════════════════════════════════════════════╗
║                    VOICE ASSISTANT  ·  Arch Linux                     ║
║       CAVA FFT Visualizer  ·  TTS Feedback  ·  Offline STT            ║
╚════════════════════════════════════════════════════════════════════════╝

  [ INFO ] Calibrating microphone (2 sec)...
  [  OK  ] Microphone calibrated.
  ──────────────────────────────────────────────────
  Available voice commands
  ──────────────────────────────────────────────────
  shut down                    (exits after)
  restart                      (exits after)
  hibernate                    (exits after)
  open firefox
  open terminal
  update
  ──────────────────────────────────────────────────

  VOICE ASSISTANT  │  Listening for a command...  │  Ctrl+C to quit
  ────────────────────────────────────────────────────────────────────
  ·  ·  ·  ·  ▄  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·  ·
  ·  ·  ·  ▄  █  ·  ·  ·  ·  ·  ·  ·  ▄  ·  ·  ·  ·  ·  ·  ·  ·  ·
  ·  ·  ▄  █  █  ▄  ·  ·  ·  ▄  ·  ▄  █  ▄  ·  ·  ·  ·  ·  ·  ·  ·
  ·  ·  █  █  █  █  ▄  ·  ▄  █  ▄  █  █  █  ·  ▄  ·  ·  ·  ·  ·  ·
  ──────────────────────────────────────────────────────────────────
  20 Hz ──────────────────── 1 kHz ─────────────────── 16 kHz
```

---

## Features

- Real-time CAVA-style FFT visualizer with logarithmic frequency scale,
  fast-attack slow-decay smoothing, and a green/yellow/red color gradient
- Voice commands matched by exact phrase or keyword fallback
  (tolerates filler words like "please", "okay", "hey")
- TTS voice feedback via pyttsx3 (primary) or espeak-ng (automatic fallback)
- Cancellable safety countdown before destructive actions (shutdown / restart /
  hibernate)
- Offline STT fallback to Sphinx when the Google Speech API is unreachable
- Compatible with PipeWire, PulseAudio, and bare ALSA
  (set `SINGLE_STREAM = True` in `config.py` for ALSA)

---

## Project Structure

```
voice-assistant/
│
├── main.py                  Entry point for the modular version
├── voice_assistant.py       Self-contained single-file version
├── config.py                All tunable constants (edit here only)
├── requirements.txt         Python dependencies
│
├── core/
│   ├── __init__.py
│   ├── assistant.py         VoiceAssistant — main loop and orchestration
│   ├── tts.py               VoiceEngine — pyttsx3 / espeak-ng TTS
│   ├── visualizer.py        CavaVisualizer — FFT display
│   └── actions.py           SystemActions + command map
│
└── utils/
    ├── __init__.py
    └── log.py               ANSI color codes and log helpers
```

---

## Dependencies

### System packages

```bash
sudo pacman -S portaudio espeak-ng flac kitty firefox
```

| Package      | Role                                              |
|:-------------|:--------------------------------------------------|
| `portaudio`  | Audio I/O backend (required by sounddevice)       |
| `espeak-ng`  | TTS fallback if pyttsx3 is not installed          |
| `flac`       | Audio codec used by SpeechRecognition internally  |
| `kitty`      | Terminal opened by the "open terminal" command    |
| `firefox`    | Browser opened by the "open firefox" command      |

### Python packages

```bash
pip install -r requirements.txt
```

| Package              | Required | Role                               |
|:---------------------|:--------:|:-----------------------------------|
| `SpeechRecognition`  | yes      | Google STT and Sphinx wrapper      |
| `sounddevice`        | yes      | PortAudio bindings (visualizer)    |
| `numpy`              | yes      | FFT and array operations           |
| `pyttsx3`            | no       | Primary TTS engine                 |
| `pocketsphinx`       | no       | Offline STT fallback               |

> **Note — pocketsphinx on Arch Linux:**
> Install `swig` before running pip:
> ```bash
> sudo pacman -S swig
> pip install pocketsphinx
> ```

---

## Installation

```bash
# 1. Clone or download the project
git clone https://github.com/krakenshell-sh/voice-assistant.git
cd voice-assistant

# 2. Install system dependencies
sudo pacman -S portaudio espeak-ng flac kitty firefox

# 3. Install Python dependencies
pip install -r requirements.txt

# 4. (Optional) Install TTS and offline STT
pip install pyttsx3
sudo pacman -S swig && pip install pocketsphinx
```

---

## Usage

### Modular version (recommended)

```bash
python main.py
```

### Self-contained single-file version

```bash
python voice_assistant.py
```

Both versions are functionally identical.
`voice_assistant.py` is provided for portability — no imports needed.

---

## Available Commands

Speak any of these phrases after the visualizer appears.
Filler words (`please`, `hey`, `okay`, `system`, etc.) are stripped automatically.

| Phrase            | Action                             | Exits? |
|:------------------|:-----------------------------------|:------:|
| `shut down`       | systemctl poweroff (5-sec warning) | yes    |
| `restart`         | systemctl reboot (5-sec warning)   | yes    |
| `hibernate`       | systemctl hibernate (5-sec warning)| yes    |
| `open firefox`    | Launches Firefox                   | no     |
| `open terminal`   | Launches Kitty terminal            | no     |
| `update`          | Runs sudo pacman -Syu              | no     |

Destructive commands (marked "yes" above) can be cancelled by pressing
**Ctrl+C** during the countdown.

---

## Adding a New Command

**Step 1** — Add a method to `SystemActions` in `core/actions.py`:

```python
def open_editor(self) -> None:
    try:
        subprocess.Popen(["nvim"], start_new_session=True, ...)
        log_action("Neovim launched.")
        self._v.speak("Opening editor.")
    except FileNotFoundError:
        log_error("nvim not found.")
        self._v.speak("Editor not found.")
```

**Step 2** — Add an entry to `build_commands()` in the same file:

```python
"open editor": {
    "action":   actions.open_editor,
    "keywords": ["editor", "nvim"],   # ALL must appear for fuzzy match
    "exits":    False,
},
```

That is all. No other files need to be changed.

---

## Configuration

All tuneable values live in `config.py`.

| Constant        | Default  | Description                                       |
|:----------------|:--------:|:--------------------------------------------------|
| `SAMPLE_RATE`   | 16000    | Audio sample rate (Hz)                            |
| `VIZ_BARS`      | 52       | Number of FFT frequency bars                      |
| `VIZ_HEIGHT`    | 12       | Max bar height in terminal rows                   |
| `VIZ_FPS`       | 30       | Visualizer target frame rate                      |
| `VIZ_DECAY`     | 0.78     | Bar fall speed (0 = instant, 0.99 = very slow)    |
| `SR_LANGUAGE`   | `en-US`  | Speech recognition locale                         |
| `SR_TIMEOUT`    | 15       | Seconds to wait before giving up on silence       |
| `SR_CALIBRATE`  | 2.0      | Ambient noise calibration duration (seconds)      |
| `TTS_ENABLED`   | `True`   | Set `False` to disable all voice output           |
| `TTS_RATE`      | 175      | TTS speed in words per minute                     |
| `COUNTDOWN_SEC` | 5        | Warning countdown for destructive commands        |
| `SINGLE_STREAM` | `False`  | Set `True` on bare ALSA to disable the visualizer |

---

## Audio Architecture

```
PipeWire / PulseAudio (multi-reader)
│
├── Stream 1 — sounddevice (PortAudio)
│     Callback feeds float32 PCM into ring buffer
│     Display thread reads ring buffer -> FFT -> ANSI frame
│
└── Stream 2 — PyAudio (via SpeechRecognition)
      sr.Microphone.listen() blocks until speech is detected
      Returns sr.AudioData -> Google STT -> Sphinx fallback
```

Both streams open simultaneously on the same input device.
This is supported natively by PipeWire and PulseAudio.

**Bare ALSA (no sound server):**
Set `SINGLE_STREAM = True` in `config.py`. This disables the visualizer
and uses only the SpeechRecognition stream.

---

## Compatibility

| Environment   | Visualizer | STT  | Notes                              |
|:--------------|:----------:|:----:|:-----------------------------------|
| PipeWire      | yes        | yes  | Fully supported, recommended       |
| PulseAudio    | yes        | yes  | Fully supported                    |
| Bare ALSA     | no         | yes  | Set `SINGLE_STREAM = True`         |

Tested on Arch Linux. Should work on any systemd-based Linux distribution
with the dependencies installed.

---

## License

MIT — use freely, modify freely.
