# config.py
# ══════════════════════════════════════════════════════════════════════════
#  Central configuration — edit values here, nowhere else.
# ══════════════════════════════════════════════════════════════════════════

# ── audio (shared by visualizer and STT) ──────────────────────────────────
SAMPLE_RATE   : int   = 16_000   # Hz

# ── CAVA-style FFT visualizer ──────────────────────────────────────────────
VIZ_BARS      : int   = 52       # number of frequency bars
VIZ_HEIGHT    : int   = 12       # max bar height in terminal rows
VIZ_FPS       : int   = 30       # target render rate (frames/sec)
VIZ_DECAY     : float = 0.78     # bar fall speed  (0 = instant, 0.99 = sluggish)
VIZ_FFT       : int   = 4096     # FFT window size (samples)
VIZ_BLOCK     : int   = 1024     # sounddevice callback block size

# ── speech recognition ─────────────────────────────────────────────────────
SR_LANGUAGE   : str   = "en-US"
SR_TIMEOUT    : int   = 15       # seconds before giving up on silence
SR_PHRASE_MAX : int   = 10       # max utterance length (seconds)
SR_CALIBRATE  : float = 2.0      # ambient noise calibration (seconds)
SR_ENERGY     : int   = 300      # initial energy threshold

# ── text-to-speech ─────────────────────────────────────────────────────────
TTS_ENABLED   : bool  = True
TTS_RATE      : int   = 175      # words per minute
TTS_VOLUME    : float = 0.9

# ── safety countdown (shutdown / restart / hibernate) ──────────────────────
COUNTDOWN_SEC : int   = 5

# ── compatibility ──────────────────────────────────────────────────────────
# Set True on bare ALSA (no sound server) to use a single audio stream
# and disable the visualizer.  Not needed on PipeWire or PulseAudio.
SINGLE_STREAM : bool  = False
