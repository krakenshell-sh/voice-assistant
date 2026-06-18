#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
╔══════════════════════════════════════════════════════════════════════════╗
║  VOICE ASSISTANT  ·  Arch Linux                                         ║
║  CAVA FFT Visualizer  ·  TTS Feedback  ·  Offline STT Fallback          ║
╚══════════════════════════════════════════════════════════════════════════╝

  DEPENDENCIES
  ─────────────────────────────────────────────────────────────────────────
  system    sudo pacman -S portaudio espeak-ng flac kitty firefox
  pip       pip install SpeechRecognition sounddevice numpy
  optional  pip install pyttsx3 pocketsphinx    (TTS / offline STT)

  AUDIO NOTES
  ─────────────────────────────────────────────────────────────────────────
  The visualizer (sounddevice / PortAudio) and the STT engine
  (SpeechRecognition / PyAudio) open separate input streams concurrently.
  This is fully supported on PipeWire and PulseAudio (both multi-reader).
  On bare ALSA without dmix, set  SINGLE_STREAM = True  to disable the
  visualizer and use only one stream.

  USAGE
  ─────────────────────────────────────────────────────────────────────────
  python voice_assistant.py

  ADDING A COMMAND
  ─────────────────────────────────────────────────────────────────────────
  1. Add a method to SystemActions.
  2. Add an entry to _build_commands().
"""

# ── standard library ───────────────────────────────────────────────────────
import sys
import time
import shutil
import threading
import subprocess
from shutil import which as _which

# ── third-party ────────────────────────────────────────────────────────────
try:
    import numpy as np
    import sounddevice as sd
    import speech_recognition as sr
except ImportError as _e:
    print(f"\n[ERROR] Missing module: {_e}")
    print("  Run: pip install SpeechRecognition sounddevice numpy\n")
    sys.exit(1)


# ══════════════════════════════════════════════════════════════════════════
#  CONFIGURATION
# ══════════════════════════════════════════════════════════════════════════

SAMPLE_RATE   : int   = 16_000   # Hz  — shared by visualizer and STT

# Visualizer ──────────────────────────────────────────────────────────────
VIZ_BARS      : int   = 52       # number of frequency bars
VIZ_HEIGHT    : int   = 12       # max bar height (terminal rows)
VIZ_FPS       : int   = 30       # target render rate
VIZ_DECAY     : float = 0.78     # bar fall speed  (0 = instant, 0.99 = very slow)
VIZ_FFT       : int   = 4096     # FFT window (samples)
VIZ_BLOCK     : int   = 1024     # sounddevice block size

# Speech recognition ──────────────────────────────────────────────────────
SR_LANGUAGE   : str   = "en-US"
SR_TIMEOUT    : int   = 15       # seconds before giving up waiting for speech
SR_PHRASE_MAX : int   = 10       # max utterance length (seconds)
SR_CALIBRATE  : float = 2.0      # ambient noise calibration duration (seconds)
SR_ENERGY     : int   = 300      # initial energy threshold

# Text-to-speech ──────────────────────────────────────────────────────────
TTS_ENABLED   : bool  = True
TTS_RATE      : int   = 175      # words per minute
TTS_VOLUME    : float = 0.9

# Safety countdown (shutdown / restart / hibernate) ───────────────────────
COUNTDOWN_SEC : int   = 5

# Set True on bare ALSA to disable the visualizer and use one stream only ─
SINGLE_STREAM : bool  = False


# ══════════════════════════════════════════════════════════════════════════
#  ANSI CODES
# ══════════════════════════════════════════════════════════════════════════

_GR = "\033[92m"   # bright green
_YL = "\033[93m"   # yellow
_RD = "\033[91m"   # bright red
_CY = "\033[96m"   # cyan
_WH = "\033[97m"   # bright white
_DG = "\033[90m"   # dark gray
_BL = "\033[94m"   # blue
_MG = "\033[95m"   # magenta
_XX = "\033[0m"    # reset all
_BD = "\033[1m"    # bold


# ══════════════════════════════════════════════════════════════════════════
#  LOGGING
# ══════════════════════════════════════════════════════════════════════════

def _log(tag: str, color: str, msg: str) -> None:
    print(f"{color}[ {tag} ]{_XX} {msg}")

def log_ok    (msg: str) -> None: _log(" OK  ", _GR, msg)
def log_warn  (msg: str) -> None: _log("WARN ", _YL, msg)
def log_error (msg: str) -> None: _log("ERROR", _RD, msg)
def log_info  (msg: str) -> None: _log("INFO ", _BL, msg)
def log_action(msg: str) -> None: _log("ACTN ", _CY, msg)
def log_cmd   (msg: str) -> None: _log(" CMD ", _MG, msg)


# ══════════════════════════════════════════════════════════════════════════
#  TEXT-TO-SPEECH ENGINE
# ══════════════════════════════════════════════════════════════════════════

class VoiceEngine:
    """
    TTS with pyttsx3 as primary and espeak-ng as automatic fallback.

    All synthesis runs in a daemon thread so it never blocks the main loop.
    Call speak(text, wait=True) when the audio must finish before proceeding
    (e.g. the final word before a shutdown command executes).
    """

    def __init__(self) -> None:
        self._engine      = None
        self._engine_type = None      # 'pyttsx3' | 'espeak' | None
        self._lock        = threading.Lock()
        self._init()

    # ── initialisation ─────────────────────────────────────────────────

    def _init(self) -> None:
        if not TTS_ENABLED:
            return

        # ── attempt pyttsx3 ──────────────────────────────────────────
        try:
            import pyttsx3
            e = pyttsx3.init()
            e.setProperty("rate",   TTS_RATE)
            e.setProperty("volume", TTS_VOLUME)
            for v in (e.getProperty("voices") or []):
                if "english" in v.name.lower():
                    e.setProperty("voice", v.id)
                    break
            self._engine      = e
            self._engine_type = "pyttsx3"
            log_ok("TTS engine: pyttsx3")
            return
        except ImportError:
            log_warn("pyttsx3 not installed — trying espeak-ng")
        except Exception as exc:
            log_warn(f"pyttsx3 unavailable ({exc}) — trying espeak-ng")

        # ── attempt espeak-ng ─────────────────────────────────────────
        try:
            subprocess.run(
                ["espeak-ng", "--version"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=True,
            )
            self._engine_type = "espeak"
            log_ok("TTS engine: espeak-ng")
            return
        except (FileNotFoundError, subprocess.CalledProcessError):
            pass

        log_error("No TTS engine found.  Install: sudo pacman -S espeak-ng")

    # ── public interface ───────────────────────────────────────────────

    def speak(self, text: str, wait: bool = False) -> "threading.Thread | None":
        """Start speaking in a daemon thread.  If wait=True, block until done."""
        if not TTS_ENABLED or self._engine_type is None:
            return None
        t = threading.Thread(
            target=self._speak_sync, args=(text,),
            daemon=True, name="TTS",
        )
        t.start()
        if wait:
            t.join()
        return t

    def shutdown(self) -> None:
        if self._engine and self._engine_type == "pyttsx3":
            try:
                self._engine.stop()
            except Exception:
                pass

    # ── internal ──────────────────────────────────────────────────────

    def _speak_sync(self, text: str) -> None:
        with self._lock:
            try:
                if self._engine_type == "pyttsx3":
                    self._engine.say(text)
                    self._engine.runAndWait()
                elif self._engine_type == "espeak":
                    self._speak_espeak(text)
            except Exception as exc:
                log_warn(f"TTS error: {exc}")

    def _speak_espeak(self, text: str) -> None:
        """
        Generate WAV via espeak-ng --stdout, then play with aplay.
        Falls back to direct espeak-ng playback if aplay is absent.
        """
        try:
            proc = subprocess.Popen(
                ["espeak-ng", "-v", "en-us", "-s", "160", "-a", "100",
                 "--stdout", text],
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
            )
            out, _ = proc.communicate(timeout=30)
            if out:
                subprocess.run(
                    ["aplay", "-q"],
                    input=out,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except FileNotFoundError:
            # aplay not available — use direct output
            try:
                subprocess.run(
                    ["espeak-ng", "-v", "en-us", "-s", "160", "-a", "100", text],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            except Exception:
                pass
        except Exception:
            pass


# ══════════════════════════════════════════════════════════════════════════
#  SYSTEM ACTIONS
# ══════════════════════════════════════════════════════════════════════════

class SystemActions:
    """
    Each public method corresponds to one voice command.

    Destructive operations (shutdown / restart / hibernate) show a
    cancellable countdown.  The user can press Ctrl+C at any point
    during the countdown to abort.
    """

    def __init__(self, voice: VoiceEngine) -> None:
        self._v = voice

    # ── countdown helper ───────────────────────────────────────────────

    def _countdown(self, label: str) -> None:
        """
        Announce and count down to a destructive action.

        Raises KeyboardInterrupt if the user presses Ctrl+C — this propagates
        back to VoiceAssistant.run() which catches it and calls continue,
        keeping the main loop alive instead of exiting.
        """
        self._v.speak(
            f"System will {label} in {COUNTDOWN_SEC} seconds. "
            "Press Control C to cancel."
        )
        sep = f"{_DG}{'─' * 44}{_XX}"
        print(f"\n{sep}")
        print(
            f"  {_RD}{_BD}WARNING{_XX}  "
            f"System will {_WH}{_BD}{label.upper()}{_XX}.  "
            f"{_DG}Press Ctrl+C to cancel.{_XX}"
        )
        print(sep)
        try:
            for i in range(COUNTDOWN_SEC, 0, -1):
                sys.stdout.write(
                    f"\r  {_WH}{_BD}{label.capitalize()} in {i}...{_XX}   "
                )
                sys.stdout.flush()
                if i <= 3:
                    t = self._v.speak(str(i))
                    if t:
                        t.join(timeout=1.5)
                time.sleep(1)
            print()
        except KeyboardInterrupt:
            self._v.speak(f"{label} cancelled.", wait=True)
            print(f"\n\n{_GR}  {label.capitalize()} cancelled by user.{_XX}\n")
            raise   # re-raise → run() catches it → loop continues

    # ── actions ────────────────────────────────────────────────────────

    def shutdown(self) -> None:
        self._countdown("shut down")   # raises KeyboardInterrupt if cancelled
        self._v.speak("Shutting down now.", wait=True)
        log_action("Executing: systemctl poweroff")
        subprocess.run(["systemctl", "poweroff"])

    def restart(self) -> None:
        self._countdown("restart")
        self._v.speak("Restarting now.", wait=True)
        log_action("Executing: systemctl reboot")
        subprocess.run(["systemctl", "reboot"])

    def hibernate(self) -> None:
        self._countdown("hibernate")
        self._v.speak("Hibernating now.", wait=True)
        log_action("Executing: systemctl hibernate")
        result = subprocess.run(
            ["systemctl", "hibernate"],
            capture_output=True,
        )
        if result.returncode != 0:
            err = result.stderr.decode(errors="replace").strip()
            log_error(f"Hibernate failed: {err}")
            log_warn("Hibernate requires a swap partition or swap file.")
            log_warn("Check: swapon --show  and  cat /sys/power/state")
            self._v.speak("Hibernate failed. Swap may not be configured.")

    def open_firefox(self) -> None:
        try:
            subprocess.Popen(
                ["firefox"],
                start_new_session=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            log_action("Firefox launched.")
            self._v.speak("Opening Firefox.")
        except FileNotFoundError:
            log_error("firefox not found.  Install: sudo pacman -S firefox")
            self._v.speak("Firefox not found.")

    def open_terminal(self) -> None:
        _TERMS = [
            "kitty", "alacritty", "xterm", "urxvt",
            "konsole", "gnome-terminal", "xfce4-terminal",
        ]
        for term in _TERMS:
            if shutil.which(term):
                try:
                    subprocess.Popen(
                        [term], start_new_session=True,
                        stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    )
                    log_action(f"{term} launched.")
                    self._v.speak("Opening terminal.")
                    return
                except Exception as exc:
                    log_warn(f"{term} found but failed to launch: {exc}")
                    continue
        log_error(f"No terminal emulator found. Tried: {', '.join(_TERMS)}")
        log_warn("Install one: sudo pacman -S kitty")
        self._v.speak("No terminal emulator found.")

    def update_system(self) -> None:
        self._v.speak(
            "Running system update. You may need to enter your password."
        )
        log_action("Running: sudo pacman -Syu")
        try:
            result = subprocess.run(["sudo", "pacman", "-Syu"], check=False)
            if result.returncode == 0:
                log_ok("System update completed.")
                self._v.speak("System update completed.")
            else:
                log_warn(f"Update exited with code {result.returncode}.")
                self._v.speak("Update finished with warnings.")
        except KeyboardInterrupt:
            log_ok("Update cancelled.")
            self._v.speak("Update cancelled.")
        except FileNotFoundError:
            log_error("pacman not found.")


# ══════════════════════════════════════════════════════════════════════════
#  COMMAND MAP
#
#  Each entry maps a canonical phrase to its handler and metadata:
#
#    "phrase key" : {
#        "action"   : callable        — function to call on match
#        "keywords" : list[str]       — ALL must appear for fuzzy fallback
#        "exits"    : bool            — True stops the main loop afterward
#    }
#
#  Matching strategy (in order):
#    1. Exact substring of normalised speech text
#    2. All listed keywords present anywhere in normalised text
#
#  HOW TO ADD A COMMAND:
#    1. Add a method to SystemActions above.
#    2. Add an entry here.
# ══════════════════════════════════════════════════════════════════════════

def _build_commands(a: SystemActions) -> dict:
    return {
        "shut down":     {"action": a.shutdown,       "keywords": ["shut", "down"],  "exits": True },
        "restart":       {"action": a.restart,        "keywords": ["restart"],        "exits": True },
        "hibernate":     {"action": a.hibernate,      "keywords": ["hibernate"],      "exits": True },
        "open firefox":  {"action": a.open_firefox,   "keywords": ["firefox"],        "exits": False},
        "open terminal": {"action": a.open_terminal,  "keywords": ["terminal"],       "exits": False},
        "update":        {"action": a.update_system,  "keywords": ["update"],         "exits": False},
    }


# ══════════════════════════════════════════════════════════════════════════
#  CAVA-STYLE FFT VISUALIZER
# ══════════════════════════════════════════════════════════════════════════

class CavaVisualizer:
    """
    Real-time CAVA-style ASCII spectrum analyser.

    Audio thread (sounddevice callback)
        writes float32 PCM into a ring buffer

    Display thread (daemon)
        reads ring buffer  ->  FFT with Hanning window
        ->  RMS per log-spaced frequency bin
        ->  fast-attack / slow-decay bar smoothing
        ->  ANSI frame rendered to stdout

    Color gradient:
        green  (0% – 40%)  normal level
        yellow (40% – 72%) elevated
        red    (72% – 100%) hot / clipping region

    Block characters:
        full block  (▀)  bar reaches this row
        half block  (▄)  bar is mid-row
        dim dot     (·)  bar does not reach
    """

    def __init__(self) -> None:
        self._ring      = np.zeros(VIZ_FFT, dtype=np.float32)
        self._ring_lock = threading.Lock()
        self._levels    = np.zeros(VIZ_BARS, dtype=np.float32)
        self._running   = False
        self._stream    = None
        self._thread    = None
        self._owned     = 0    # terminal rows currently written by visualizer

    # ── audio callback ─────────────────────────────────────────────────

    def _audio_cb(
        self,
        indata: np.ndarray,
        frames: int,
        time_info: object,
        status: "sd.CallbackFlags",
    ) -> None:
        mono = indata[:, 0].astype(np.float32)
        with self._ring_lock:
            self._ring = np.roll(self._ring, -len(mono))
            self._ring[-len(mono):] = mono

    # ── spectrum ────────────────────────────────────────────────────────

    def _compute_bars(self) -> np.ndarray:
        """
        FFT of ring buffer  ->  RMS per log-spaced bin  ->  normalised [0..1].

        Uses a Hanning window to suppress spectral leakage, and a
        logarithmic frequency axis for perceptually even bar distribution.
        """
        with self._ring_lock:
            pcm = self._ring.copy()

        window   = np.hanning(len(pcm))
        spectrum = np.abs(np.fft.rfft(pcm * window))
        usable   = spectrum[: len(spectrum) // 2]   # below Nyquist/2

        if len(usable) < 2:
            return np.zeros(VIZ_BARS, dtype=np.float32)

        edges = np.logspace(
            np.log10(1),
            np.log10(len(usable) - 1),
            VIZ_BARS + 1,
            dtype=np.float32,
        )
        vals = np.zeros(VIZ_BARS, dtype=np.float32)
        for i in range(VIZ_BARS):
            lo    = int(edges[i])
            hi    = int(edges[i + 1]) + 1
            chunk = usable[lo:hi]
            if len(chunk):
                vals[i] = float(np.sqrt(np.mean(chunk ** 2)))

        peak = vals.max()
        if peak > 1e-8:
            vals /= peak
        return vals

    # ── color ───────────────────────────────────────────────────────────

    @staticmethod
    def _color(ratio: float) -> str:
        if ratio < 0.40:
            return _GR
        if ratio < 0.72:
            return _YL
        return _RD

    # ── frame builder ────────────────────────────────────────────────────

    def _build_frame(self, cols: int) -> list[str]:
        raw = self._compute_bars()

        # Vectorised smooth: instant attack, exponential decay
        self._levels = np.where(raw > self._levels, raw, self._levels * VIZ_DECAY)

        n_bars = min(VIZ_BARS, (cols - 2) // 2)
        lvls   = self._levels[:n_bars]
        rows: list[str] = []

        # ── grid (top to bottom) ────────────────────────────────────────
        for r in range(VIZ_HEIGHT, 0, -1):
            thr  = r / VIZ_HEIGHT
            half = (r - 0.5) / VIZ_HEIGHT
            line = []
            for lvl in lvls:
                c = self._color(float(lvl))
                if   lvl >= thr:  line.append(f"{c}█{_XX}")
                elif lvl >= half: line.append(f"{c}▄{_XX}")
                else:             line.append(f"{_DG}·{_XX}")
            rows.append(" ".join(line))

        # ── axis ─────────────────────────────────────────────────────────
        w = n_bars * 2
        rows.append(f"{_DG}{'─' * w}{_XX}")

        # ── frequency labels ─────────────────────────────────────────────
        fixed    = len("20 Hz") + len("  1 kHz  ") + len("16 kHz")
        dashes   = max(2, (w - fixed) // 2)
        rows.append(
            f"{_DG}20 Hz"
            f"{'─' * dashes}"
            f"  1 kHz  "
            f"{'─' * dashes}"
            f"16 kHz{_XX}"
        )
        return rows

    # ── terminal management ──────────────────────────────────────────────

    def _erase_owned(self) -> None:
        if self._owned > 0:
            sys.stdout.write(f"\033[{self._owned}A\033[J")
            sys.stdout.flush()
        self._owned = 0

    # ── display loop ─────────────────────────────────────────────────────

    def _display_loop(self) -> None:
        sys.stdout.write("\033[?25l")   # hide cursor
        sys.stdout.flush()
        interval = 1.0 / VIZ_FPS

        try:
            while self._running:
                t0   = time.monotonic()
                cols = shutil.get_terminal_size((100, 24)).columns

                header = (
                    f"  {_CY}{_BD}VOICE ASSISTANT{_XX}  "
                    f"{_DG}│{_XX}  "
                    f"{_WH}Listening for a command...{_XX}  "
                    f"{_DG}│  Ctrl+C to quit{_XX}"
                )
                divider = f"  {_DG}{'─' * min(cols - 4, VIZ_BARS * 2)}{_XX}"
                frame   = self._build_frame(cols)
                lines   = ["", header, divider] + [f"  {ln}" for ln in frame]

                self._erase_owned()
                sys.stdout.write("\n".join(lines) + "\n")
                sys.stdout.flush()
                self._owned = len(lines) + 1   # +1 for trailing newline

                spare = interval - (time.monotonic() - t0)
                if spare > 0:
                    time.sleep(spare)
        finally:
            self._erase_owned()
            sys.stdout.write("\033[?25h")   # restore cursor
            sys.stdout.flush()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running or SINGLE_STREAM:
            return
        self._running = True
        try:
            self._stream = sd.InputStream(
                samplerate = SAMPLE_RATE,
                channels   = 1,
                blocksize  = VIZ_BLOCK,
                dtype      = "float32",
                callback   = self._audio_cb,
            )
            self._stream.start()
        except Exception as exc:
            self._running = False
            log_warn(f"Visualizer unavailable: {exc}")
            return
        self._thread = threading.Thread(
            target=self._display_loop, daemon=True, name="CavaDisplay",
        )
        self._thread.start()

    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.2)
        self._thread = None
        if self._stream:
            try:
                self._stream.stop()
                self._stream.close()
            except Exception:
                pass
            self._stream = None


# ══════════════════════════════════════════════════════════════════════════
#  VOICE ASSISTANT — main orchestrator
# ══════════════════════════════════════════════════════════════════════════

class VoiceAssistant:
    """
    Ties together the visualizer, STT, command matcher, and action dispatcher.

    One listening cycle:
        visualizer.start()              — display FFT while idle
        sr.Microphone.listen()          — block until speech detected
        visualizer.stop()               — clear display
        STT: Google -> Sphinx fallback  — convert audio to text
        fuzzy command match             — exact substring then keywords
        action dispatch                 — execute; optionally exit loop
    """

    _STRIP = (
        "please", "system", "okay", "ok", "hey",
        "can you", "would you", "i want to", "could you",
    )

    def __init__(self) -> None:
        self._rec = sr.Recognizer()
        self._rec.energy_threshold         = SR_ENERGY
        self._rec.dynamic_energy_threshold = True
        self._rec.pause_threshold          = 0.8

        self._voice   = VoiceEngine()
        self._actions = SystemActions(self._voice)
        self._cmds    = _build_commands(self._actions)
        self._viz     = CavaVisualizer()
        self._mic     = sr.Microphone(sample_rate=SAMPLE_RATE)

        self._calibrate()

    # ── calibration ────────────────────────────────────────────────────

    def _calibrate(self) -> None:
        log_info(f"Calibrating microphone ({SR_CALIBRATE:.0f} sec)...")
        try:
            with self._mic as src:
                self._rec.adjust_for_ambient_noise(src, duration=SR_CALIBRATE)
            log_ok("Microphone calibrated.")
        except Exception as exc:
            log_warn(f"Calibration failed ({exc}) — using defaults.")
        print()

    # ── speech recognition ──────────────────────────────────────────────

    def _recognize(self, audio: sr.AudioData) -> "str | None":
        """Google STT with automatic Sphinx fallback on network failure."""
        try:
            return self._rec.recognize_google(audio, language=SR_LANGUAGE)
        except sr.UnknownValueError:
            return None
        except sr.RequestError as exc:
            log_warn(f"Google STT unavailable ({exc}) — trying Sphinx...")

        try:
            return self._rec.recognize_sphinx(audio)
        except sr.UnknownValueError:
            return None
        except Exception as exc:
            log_error(f"Sphinx failed: {exc}")
            return None

    # ── command matching ────────────────────────────────────────────────

    def _normalize(self, text: str) -> str:
        """Lowercase and strip known filler words from the front."""
        t = text.strip().lower()
        for filler in self._STRIP:
            while t.startswith(filler):
                t = t[len(filler):].strip()
        return t

    def _match(self, text: str) -> "tuple[str, dict] | tuple[None, None]":
        """
        Two-pass match:
          Pass 1 — canonical phrase is a substring of normalised text
          Pass 2 — all keywords appear anywhere in normalised text
        """
        n = self._normalize(text)
        for key, cfg in self._cmds.items():
            if key in n:
                return key, cfg
        for key, cfg in self._cmds.items():
            if all(kw in n for kw in cfg["keywords"]):
                return key, cfg
        return None, None

    # ── one listen cycle ────────────────────────────────────────────────

    def _listen_once(self) -> "sr.AudioData | None":
        with self._mic as src:
            try:
                return self._rec.listen(
                    src,
                    timeout=SR_TIMEOUT,
                    phrase_time_limit=SR_PHRASE_MAX,
                )
            except sr.WaitTimeoutError:
                return None

    # ── command table print ─────────────────────────────────────────────

    def _print_commands(self) -> None:
        sep = f"{_DG}{'─' * 50}{_XX}"
        print(sep)
        print(f"  {_WH}{_BD}Available voice commands{_XX}")
        print(sep)
        for key, cfg in self._cmds.items():
            tag = f"  {_DG}(exits after){_XX}" if cfg["exits"] else ""
            print(f"  {_CY}{key:<22}{_XX}{tag}")
        print(sep)
        print()

    # ── main loop ───────────────────────────────────────────────────────

    def run(self) -> None:
        _print_banner()
        self._print_commands()
        self._voice.speak("Voice assistant ready. Say a command.")

        while True:

            # ── Phase 1: idle with FFT visualizer ──────────────────────
            self._viz.start()

            # ── Phase 2: block until speech or timeout ──────────────────
            audio = None
            try:
                audio = self._listen_once()
            except KeyboardInterrupt:
                self._viz.stop()
                break
            except Exception as exc:
                self._viz.stop()
                log_error(f"Listen error: {exc}")
                time.sleep(0.5)
                continue

            # ── Phase 3: tear down visualizer cleanly ───────────────────
            self._viz.stop()
            print()

            if audio is None:
                log_info("Timeout — no speech detected.  Resuming...")
                continue

            # ── Phase 4: speech-to-text ─────────────────────────────────
            text = self._recognize(audio)
            if text is None:
                log_warn("Could not understand speech.")
                continue

            log_cmd(f"Recognized  :  {_WH}{_BD}{text}{_XX}")

            # ── Phase 5: match ───────────────────────────────────────────
            key, cfg = self._match(text)
            if key is None:
                log_warn(f"No command matched for: '{text}'")
                self._voice.speak("Command not recognised.")
                continue

            log_action(f"Command     :  {key}")
            self._voice.speak(f"Executing {key}.")

            # ── Phase 6: execute ─────────────────────────────────────────
            try:
                cfg["action"]()
            except KeyboardInterrupt:
                log_ok("Action interrupted by user.")
                continue
            except Exception as exc:
                log_error(f"Action failed: {exc}")
                self._voice.speak("An error occurred.")
                continue

            if cfg["exits"]:
                break

            print()

        # ── Shutdown ─────────────────────────────────────────────────────
        self._voice.shutdown()
        print()
        log_info("Voice assistant stopped.")


# ══════════════════════════════════════════════════════════════════════════
#  STARTUP BANNER
# ══════════════════════════════════════════════════════════════════════════

def _print_banner() -> None:
    inner = 72   # fixed inner width for consistency across terminals

    def row(text: str = "", color: str = "") -> str:
        return f"{_DG}║{_XX}{color}{text.center(inner)}{_XX}{_DG}║{_XX}"

    print()
    print(f"{_DG}╔{'═' * inner}╗{_XX}")
    print(row())
    print(row("VOICE ASSISTANT  ·  Arch Linux",                    f"{_CY}{_BD}"))
    print(row("CAVA FFT Visualizer  ·  TTS Feedback  ·  Offline STT", f"{_DG}"))
    print(row())
    print(f"{_DG}╚{'═' * inner}╝{_XX}")
    print()


# ══════════════════════════════════════════════════════════════════════════
#  ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════

def main() -> None:
    try:
        VoiceAssistant().run()
    except KeyboardInterrupt:
        print(f"\n{_DG}  Interrupted.{_XX}\n")
    except Exception as exc:
        log_error(f"Fatal: {exc}")
        raise


if __name__ == "__main__":
    main()
