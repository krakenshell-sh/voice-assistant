# core/assistant.py
# ══════════════════════════════════════════════════════════════════════════
#  Main orchestrator — ties together visualizer, STT, matching, dispatch.
# ══════════════════════════════════════════════════════════════════════════

import sys
import time
import shutil

import speech_recognition as sr

from config        import SAMPLE_RATE, SR_LANGUAGE, SR_TIMEOUT, SR_PHRASE_MAX, SR_CALIBRATE, SR_ENERGY
from utils.log     import _CY, _WH, _DG, _XX, _BD, log_ok, log_warn, log_error, log_info, log_action, log_cmd
from core.tts      import VoiceEngine
from core.visualizer import CavaVisualizer
from core.actions  import SystemActions, build_commands


class VoiceAssistant:
    """
    Main orchestrator.

    One listening cycle:
        visualizer.start()               — display FFT while idle
        sr.Microphone.listen()           — block until speech detected
        visualizer.stop()                — clear display
        STT: Google -> Sphinx fallback   — audio to text
        fuzzy command match              — exact substring, then keywords
        action dispatch                  — execute; optionally exit loop
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
        self._cmds    = build_commands(self._actions)
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

    # ── STT ────────────────────────────────────────────────────────────

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
        t = text.strip().lower()
        for filler in self._STRIP:
            while t.startswith(filler):
                t = t[len(filler):].strip()
        return t

    def _match(self, text: str) -> "tuple[str, dict] | tuple[None, None]":
        """
        Pass 1: canonical phrase is a substring of normalised text.
        Pass 2: all keywords appear anywhere in normalised text.
        """
        n = self._normalize(text)
        for key, cfg in self._cmds.items():
            if key in n:
                return key, cfg
        for key, cfg in self._cmds.items():
            if all(kw in n for kw in cfg["keywords"]):
                return key, cfg
        return None, None

    # ── listen once ─────────────────────────────────────────────────────

    def _listen_once(self) -> "sr.AudioData | None":
        with self._mic as src:
            try:
                return self._rec.listen(
                    src, timeout=SR_TIMEOUT, phrase_time_limit=SR_PHRASE_MAX,
                )
            except sr.WaitTimeoutError:
                return None

    # ── print command table ─────────────────────────────────────────────

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

            self._viz.start()

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

            self._viz.stop()
            print()

            if audio is None:
                log_info("Timeout — no speech detected.  Resuming...")
                continue

            text = self._recognize(audio)
            if text is None:
                log_warn("Could not understand speech.")
                continue

            log_cmd(f"Recognized  :  {_WH}{_BD}{text}{_XX}")

            key, cfg = self._match(text)
            if key is None:
                log_warn(f"No command matched for: '{text}'")
                self._voice.speak("Command not recognised.")
                continue

            log_action(f"Command     :  {key}")
            self._voice.speak(f"Executing {key}.")

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

        self._voice.shutdown()
        print()
        log_info("Voice assistant stopped.")


# ══════════════════════════════════════════════════════════════════════════
#  STARTUP BANNER
# ══════════════════════════════════════════════════════════════════════════

def _print_banner() -> None:
    inner = 72

    def row(text: str = "", color: str = "") -> str:
        return f"\033[90m║\033[0m{color}{text.center(inner)}\033[0m\033[90m║\033[0m"

    print()
    print(f"\033[90m╔{'═' * inner}╗\033[0m")
    print(row())
    print(row("VOICE ASSISTANT  ·  Arch Linux",                         f"{_CY}{_BD}"))
    print(row("CAVA FFT Visualizer  ·  TTS Feedback  ·  Offline STT",   f"{_DG}"))
    print(row())
    print(f"\033[90m╚{'═' * inner}╝\033[0m")
    print()
