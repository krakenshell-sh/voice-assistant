# core/actions.py
# ══════════════════════════════════════════════════════════════════════════
#  System actions and the voice command map.
#
#  HOW TO ADD A NEW COMMAND:
#    1. Add a method to SystemActions.
#    2. Add an entry to _build_commands().
# ══════════════════════════════════════════════════════════════════════════

import sys
import time
import shutil
import subprocess

from config    import COUNTDOWN_SEC
from utils.log import _GR, _RD, _WH, _DG, _XX, _BD, log_ok, log_warn, log_error, log_action


class SystemActions:
    """
    Each public method corresponds to one voice command.

    Destructive operations (shutdown / restart / hibernate) use a
    cancellable countdown.  The user can press Ctrl+C at any time to abort.
    """

    def __init__(self, voice) -> None:
        self._v = voice   # VoiceEngine instance

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
            f"  {_RD}{_BD}WARNING{_XX}  System will {_WH}{_BD}{label.upper()}{_XX}.  "
            f"{_DG}Press Ctrl+C to cancel.{_XX}"
        )
        print(sep)
        try:
            for i in range(COUNTDOWN_SEC, 0, -1):
                sys.stdout.write(f"\r  {_WH}{_BD}{label.capitalize()} in {i}...{_XX}   ")
                sys.stdout.flush()
                if i <= 3:
                    t = self._v.speak(str(i))
                    if t: t.join(timeout=1.5)
                time.sleep(1)
            print()
        except KeyboardInterrupt:
            # Announce cancellation, then re-raise so run() catches it
            # and calls `continue` — the loop stays alive.
            self._v.speak(f"{label} cancelled.", wait=True)
            print(f"\n\n{_GR}  {label.capitalize()} cancelled by user.{_XX}\n")
            raise

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
                ["firefox"], start_new_session=True,
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
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
        self._v.speak("Running system update. You may need to enter your password.")
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
#  Each entry:
#    "phrase" : {
#        "action"   : callable      — method to call on match
#        "keywords" : list[str]     — ALL must be present for fuzzy fallback
#        "exits"    : bool          — True stops the main loop after execution
#    }
# ══════════════════════════════════════════════════════════════════════════

def build_commands(actions: SystemActions) -> dict:
    return {
        "shut down":     {"action": actions.shutdown,      "keywords": ["shut", "down"], "exits": True },
        "restart":       {"action": actions.restart,       "keywords": ["restart"],       "exits": True },
        "hibernate":     {"action": actions.hibernate,     "keywords": ["hibernate"],     "exits": True },
        "open firefox":  {"action": actions.open_firefox,  "keywords": ["firefox"],       "exits": False},
        "open terminal": {"action": actions.open_terminal, "keywords": ["terminal"],      "exits": False},
        "update":        {"action": actions.update_system, "keywords": ["update"],        "exits": False},
    }
