from __future__ import annotations
import time
import math

from PyQt6.QtCore import QThread, pyqtSignal

from app.model.types import Move, SpeedSettings
from app.io.hpgl_writer import moves_to_hpgl

# OS; round-trip at 9600 baud ≈ 10–20 ms — negligible vs. any real move duration.
# Timeout must be ≥ the slowest expected single move.
_OS_RESPONSE_TIMEOUT = 120.0


class SerialSender(QThread):
    progress        = pyqtSignal(int, int)  # sent_count, total_count
    confirmed_index = pyqtSignal(int)       # last OS;-confirmed move index (0-based)
    line_sent       = pyqtSignal(str)       # hpgl text for log
    job_finished    = pyqtSignal()
    job_stopped     = pyqtSignal()
    error_occurred  = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._moves: list[Move] = []
        self._speeds: SpeedSettings = SpeedSettings()
        self._port = None
        self._throttle: float = 0.8
        self._sync_mode: str = "throttle"
        self._os_interval: int = 1
        self._offset_x: float = 0.0
        self._offset_y: float = 0.0
        self._paused = False
        self._stopped = False

    def configure(
        self,
        port,
        moves: list[Move],
        speeds: SpeedSettings,
        throttle_factor: float = 0.8,
        sync_mode: str = "throttle",
        os_sync_interval: int = 1,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ):
        self._port = port
        self._moves = moves
        self._speeds = speeds
        self._throttle = throttle_factor
        self._sync_mode = sync_mode
        self._os_interval = max(1, os_sync_interval)
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._paused = False
        self._stopped = False

    def pause(self):
        self._paused = True

    def resume(self):
        self._paused = False

    def stop(self):
        self._stopped = True
        self._paused = False

    # ------------------------------------------------------------------
    # Main thread

    def run(self):
        total = len(self._moves)
        stopped = False
        try:
            for i, move in enumerate(self._moves):
                # ── pause / stop ───────────────────────────────────────
                while self._paused and not self._stopped:
                    time.sleep(0.05)
                if self._stopped:
                    # Lift the tool immediately before issuing reset
                    self._port.write(b"PU;IN;\n")
                    stopped = True
                    break

                # ── send one HPGL command ──────────────────────────────
                first = (i == 0)
                hpgl = moves_to_hpgl(
                    [move],
                    include_init=first,
                    offset_x=self._offset_x,
                    offset_y=self._offset_y,
                    xy_speed_mms=self._speeds.xy_machining_mm_min / 60.0 if first else None,
                    z_speed_mms=self._speeds.z_machining_mm_min / 60.0 if first else None,
                )
                self._port.write(hpgl)
                self.line_sent.emit(hpgl.decode(errors="replace").strip())
                self.progress.emit(i + 1, total)

                # ── synchronisation ────────────────────────────────────
                if self._sync_mode == "os_query":
                    # Send OS; every N moves.
                    # N=1 (default): after every single command — the machine
                    # can have at most 1 command ahead of the PC.  When
                    # OS; response arrives the machine's buffer is empty and
                    # the PC knows the exact last-executed move index.
                    if (i + 1) % self._os_interval == 0:
                        self._os_sync(confirmed_index=i)
                else:
                    wait = self._estimate_seconds(move) * self._throttle
                    if wait > 0:
                        time.sleep(wait)

            # Final OS; — wait for the machine to finish the last moves
            if not stopped and self._sync_mode == "os_query":
                self._os_sync(confirmed_index=total - 1, timeout=_OS_RESPONSE_TIMEOUT)

            if stopped:
                self.job_stopped.emit()
            else:
                self.job_finished.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    # ------------------------------------------------------------------
    # OS; synchronisation

    def _os_sync(self, confirmed_index: int = -1, timeout: float = _OS_RESPONSE_TIMEOUT):
        """Send OS; and block until the machine responds (or timeout).

        The machine queues OS; sequentially in its input buffer.  The
        response arrives only after all preceding commands have been
        executed, giving the PC true back-pressure:

          PC:      [cmd_i]  [OS;]  ← waits ─────────────────────────────
          Machine:  execute cmd_i → execute OS; → responds
          PC:                                      ← continues with cmd_i+1

        With os_sync_interval=1, the machine can never accumulate more
        than 1 command ahead of the PC, so Pause/Stop take effect within
        the execution time of the current single command.
        """
        try:
            self._port.write(b"OS;\n")

            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._stopped:
                    return
                if self._paused:
                    # Still wait while paused — when the user resumes we'll
                    # receive the OS; response and then re-enter the pause
                    # check in the main loop before sending the next command.
                    time.sleep(0.05)
                    continue
                if self._port.in_waiting:
                    self._port.read(self._port.in_waiting)   # drain response
                    if confirmed_index >= 0:
                        self.confirmed_index.emit(confirmed_index)
                    return
                time.sleep(0.015)

            # Timeout — warn but continue (machine may be mid-long-move)
            self.line_sent.emit(
                f"[WARN] OS; sync timeout after {timeout:.0f} s — "
                "machine may still be executing; continuing anyway."
            )
        except Exception as exc:
            self.line_sent.emit(f"[WARN] OS; sync error: {exc}")

    # ------------------------------------------------------------------
    # Duration estimate (throttle mode only)

    def _estimate_seconds(self, move: Move) -> float:
        dx = move.to_pos.x - move.from_pos.x
        dy = move.to_pos.y - move.from_pos.y
        dz = abs(move.to_pos.z - move.from_pos.z)
        xy_dist = math.sqrt(dx * dx + dy * dy)
        t = 0.0
        if xy_dist > 0:
            spd = (
                self._speeds.xy_machining_mm_min
                if move.pen_down
                else self._speeds.xy_travel_mm_min
            )
            if spd > 0:
                t += (xy_dist / spd) * 60.0
        if dz > 0:
            spd = (
                self._speeds.z_machining_mm_min
                if move.pen_down
                else self._speeds.z_travel_mm_min
            )
            if spd > 0:
                t += (dz / spd) * 60.0
        return t
