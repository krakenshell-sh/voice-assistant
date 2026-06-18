# core/visualizer.py
# ══════════════════════════════════════════════════════════════════════════
#  CAVA-style real-time FFT spectrum visualizer.
#
#  Audio flow:
#    sounddevice callback  ->  ring buffer (float32)
#    display thread        ->  FFT  ->  log-scale bins  ->  ANSI frame
#
#  Color gradient:
#    green  (0 %–40 %)   normal level
#    yellow (40 %–72 %)  elevated
#    red    (72 %–100 %) hot / clipping region
# ══════════════════════════════════════════════════════════════════════════

import sys
import time
import shutil
import threading

import numpy as np
import sounddevice as sd

from config    import (
    SAMPLE_RATE, VIZ_BARS, VIZ_HEIGHT, VIZ_FPS,
    VIZ_DECAY, VIZ_FFT, VIZ_BLOCK, SINGLE_STREAM,
)
from utils.log import _GR, _YL, _RD, _CY, _WH, _DG, _XX, _BD, log_warn


class CavaVisualizer:
    """
    Real-time CAVA-style ASCII spectrum analyser.

    Lifecycle:
        viz = CavaVisualizer()
        viz.start()    # opens audio stream + starts display thread
        ...            # runs until stop() is called
        viz.stop()     # closes stream, erases owned terminal rows
    """

    def __init__(self) -> None:
        self._ring      = np.zeros(VIZ_FFT, dtype=np.float32)
        self._ring_lock = threading.Lock()
        self._levels    = np.zeros(VIZ_BARS, dtype=np.float32)
        self._running   = False
        self._stream    = None
        self._thread    = None
        self._owned     = 0    # terminal rows currently written by the visualizer

    # ── audio callback ─────────────────────────────────────────────────

    def _audio_cb(self, indata, frames, time_info, status) -> None:
        mono = indata[:, 0].astype(np.float32)
        with self._ring_lock:
            self._ring = np.roll(self._ring, -len(mono))
            self._ring[-len(mono):] = mono

    # ── spectrum ────────────────────────────────────────────────────────

    def _compute_bars(self) -> np.ndarray:
        """FFT -> RMS per log-spaced bin -> normalised [0..1]."""
        with self._ring_lock:
            pcm = self._ring.copy()

        window   = np.hanning(len(pcm))
        spectrum = np.abs(np.fft.rfft(pcm * window))
        usable   = spectrum[: len(spectrum) // 2]

        if len(usable) < 2:
            return np.zeros(VIZ_BARS, dtype=np.float32)

        edges = np.logspace(
            np.log10(1), np.log10(len(usable) - 1),
            VIZ_BARS + 1, dtype=np.float32,
        )
        vals = np.zeros(VIZ_BARS, dtype=np.float32)
        for i in range(VIZ_BARS):
            lo, hi = int(edges[i]), int(edges[i + 1]) + 1
            chunk  = usable[lo:hi]
            if len(chunk):
                vals[i] = float(np.sqrt(np.mean(chunk ** 2)))

        peak = vals.max()
        if peak > 1e-8:
            vals /= peak
        return vals

    # ── color ───────────────────────────────────────────────────────────

    @staticmethod
    def _color(ratio: float) -> str:
        if ratio < 0.40: return _GR
        if ratio < 0.72: return _YL
        return _RD

    # ── frame builder ────────────────────────────────────────────────────

    def _build_frame(self, cols: int) -> list[str]:
        raw = self._compute_bars()
        self._levels = np.where(raw > self._levels, raw, self._levels * VIZ_DECAY)

        n_bars = min(VIZ_BARS, (cols - 4) // 2)
        lvls   = self._levels[:n_bars]
        rows: list[str] = []

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

        w = n_bars * 2
        rows.append(f"{_DG}{'─' * w}{_XX}")

        fixed  = len("20 Hz") + len("  1 kHz  ") + len("16 kHz")
        dashes = max(2, (w - fixed) // 2)
        rows.append(
            f"{_DG}20 Hz{'─' * dashes}  1 kHz  {'─' * dashes}16 kHz{_XX}"
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
        sys.stdout.write("\033[?25l")
        sys.stdout.flush()
        interval = 1.0 / VIZ_FPS

        try:
            while self._running:
                t0   = time.monotonic()
                cols = shutil.get_terminal_size((100, 24)).columns

                header  = (
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
                self._owned = len(lines) + 1

                spare = interval - (time.monotonic() - t0)
                if spare > 0:
                    time.sleep(spare)
        finally:
            self._erase_owned()
            sys.stdout.write("\033[?25h")
            sys.stdout.flush()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self) -> None:
        if self._running or SINGLE_STREAM:
            return
        self._running = True
        try:
            self._stream = sd.InputStream(
                samplerate=SAMPLE_RATE, channels=1,
                blocksize=VIZ_BLOCK, dtype="float32",
                callback=self._audio_cb,
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
