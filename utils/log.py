# utils/log.py
# ══════════════════════════════════════════════════════════════════════════
#  ANSI color codes and structured logging helpers.
#  Import from here — never define colors inline elsewhere.
# ══════════════════════════════════════════════════════════════════════════

# ── ANSI escape codes ──────────────────────────────────────────────────────
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

# ── log helpers ────────────────────────────────────────────────────────────

def _log(tag: str, color: str, msg: str) -> None:
    print(f"{color}[ {tag} ]{_XX} {msg}")

def log_ok    (msg: str) -> None: _log(" OK  ", _GR, msg)
def log_warn  (msg: str) -> None: _log("WARN ", _YL, msg)
def log_error (msg: str) -> None: _log("ERROR", _RD, msg)
def log_info  (msg: str) -> None: _log("INFO ", _BL, msg)
def log_action(msg: str) -> None: _log("ACTN ", _CY, msg)
def log_cmd   (msg: str) -> None: _log(" CMD ", _MG, msg)
