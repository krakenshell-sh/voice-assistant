# core/tts.py
# ══════════════════════════════════════════════════════════════════════════
#  Text-to-speech engine.
#  Primary  : pyttsx3 (pip install pyttsx3)
#  Fallback : espeak-ng (sudo pacman -S espeak-ng)
# ══════════════════════════════════════════════════════════════════════════

import subprocess
import threading

from config   import TTS_ENABLED, TTS_RATE, TTS_VOLUME
from utils.log import log_ok, log_warn, log_error


class VoiceEngine:
    """
    Manages TTS with automatic engine detection and fallback.

    Usage:
        voice = VoiceEngine()
        voice.speak("Hello.")                  # non-blocking
        voice.speak("Done.", wait=True)        # block until audio finishes
        voice.shutdown()                       # cleanup on exit
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

        # ── pyttsx3 ───────────────────────────────────────────────────
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

        # ── espeak-ng ─────────────────────────────────────────────────
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

    # ── public ─────────────────────────────────────────────────────────

    def speak(self, text: str, wait: bool = False) -> "threading.Thread | None":
        """Speak text in a daemon thread.  Pass wait=True to block until done."""
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
        """Release engine resources on program exit."""
        if self._engine and self._engine_type == "pyttsx3":
            try:
                self._engine.stop()
            except Exception:
                pass

    # ── internal ───────────────────────────────────────────────────────

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
        """Generate WAV via espeak-ng --stdout, play with aplay.
        Falls back to direct espeak-ng output if aplay is absent."""
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
                    ["aplay", "-q"], input=out,
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30,
                )
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        except FileNotFoundError:
            try:
                subprocess.run(
                    ["espeak-ng", "-v", "en-us", "-s", "160", "-a", "100", text],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=30,
                )
            except Exception:
                pass
        except Exception:
            pass
