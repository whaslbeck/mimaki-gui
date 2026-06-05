from __future__ import annotations
import time
import math
from typing import Optional

from PyQt6.QtCore import QThread, pyqtSignal

from app.model.types import Move, SpeedSettings
from app.io.hpgl_writer import moves_to_hpgl

_OS_RESPONSE_TIMEOUT = 120.0


class SerialSender(QThread):
    progress             = pyqtSignal(int, int)  # sent_count, total_count
    confirmed_index      = pyqtSignal(int)       # last OS;-confirmed move index (0-based)
    line_sent            = pyqtSignal(str)       # hpgl line or status message for log
    retracted            = pyqtSignal(bool)      # True = cutter raised (PU;), False = re-engaged
    tool_change_required = pyqtSignal(float)     # z-depth that triggered a tool-change pause
    job_finished         = pyqtSignal()
    job_stopped          = pyqtSignal()
    error_occurred       = pyqtSignal(str)

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
        self._resume_from: int = -1     # set by resume_from(); -1 = continue normally
        self._init_sent: bool = False   # guard: send IN/VS/VZ only once per job
        self._last_confirmed_move: Optional[Move] = None
        self._last_sent_move: Optional[Move] = None
        self._tool_change_depths: frozenset = frozenset()
        self._tool_change_triggered: set[float] = set()
        self._feed_override: float = 1.0
        self._feed_override_changed: bool = False

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
        tool_change_depths: frozenset = frozenset(),
    ):
        self._port = port
        self._moves = moves
        self._speeds = speeds
        self._throttle = throttle_factor
        self._sync_mode = sync_mode
        self._os_interval = max(1, os_sync_interval)
        self._offset_x = offset_x
        self._offset_y = offset_y
        self._tool_change_depths = tool_change_depths
        self._paused = False
        self._stopped = False
        self._resume_from = -1
        self._init_sent = False
        self._last_confirmed_move = None
        self._last_sent_move = None
        self._tool_change_triggered = set()
        self._feed_override = 1.0
        self._feed_override_changed = False

    def pause(self):
        self._paused = True

    def resume(self):
        """Resume from the next unsent move (normal resume)."""
        self._resume_from = -1
        self._paused = False

    def resume_from(self, index: int):
        """Resume from a specific move index (e.g. after rewind)."""
        self._resume_from = max(0, index)
        self._paused = False

    def set_feed_override(self, factor: float):
        """Multiply machining feed by factor (0.25–4.0). Injects VS; before next move."""
        self._feed_override = max(0.25, min(4.0, factor))
        self._feed_override_changed = True

    def stop(self):
        self._stopped = True
        self._paused = False

    # ------------------------------------------------------------------
    # Main thread

    def run(self):
        total = len(self._moves)
        stopped = False
        i = 0
        try:
            while i < total:
                move = self._moves[i]

                # ── Stop ──────────────────────────────────────────────
                if self._stopped:
                    self._port.write(b"PU;IN;\n")
                    stopped = True
                    break

                # ── Pause ─────────────────────────────────────────────
                if self._paused:
                    retracted = self._retract_if_cutting()
                    while self._paused and not self._stopped:
                        time.sleep(0.05)
                    if self._stopped:
                        self._port.write(b"PU;IN;\n")
                        stopped = True
                        break
                    if retracted:
                        self._reengage()
                    # Apply rewind if requested
                    if self._resume_from >= 0:
                        i = self._resume_from
                        self._resume_from = -1
                        continue   # restart loop from new index (no i += 1)

                # ── Tool-change pause ─────────────────────────────────
                z_key = round(move.to_pos.z, 2)
                if (move.z_move and move.pen_down and
                        z_key in self._tool_change_depths and
                        z_key not in self._tool_change_triggered):
                    self._tool_change_triggered.add(z_key)
                    self._retract_if_cutting()
                    self.line_sent.emit(
                        f"[TOOL CHANGE] pausing before pass at Z {z_key:.2f} mm"
                    )
                    self.tool_change_required.emit(z_key)
                    self._paused = True
                    while self._paused and not self._stopped:
                        time.sleep(0.05)
                    if self._stopped:
                        self._port.write(b"PU;IN;\n")
                        stopped = True
                        break
                    if self._resume_from >= 0:
                        i = self._resume_from
                        self._resume_from = -1
                        continue

                # ── Feed override injection ────────────────────────────
                if self._feed_override_changed:
                    new_mms = max(1, round(
                        self._speeds.xy_machining_mm_min / 60.0 * self._feed_override
                    ))
                    self._port.write(f"VS{new_mms};\n".encode())
                    self.line_sent.emit(
                        f"[FEED] VS{new_mms}; ({self._feed_override:.0%})"
                    )
                    self._feed_override_changed = False

                # ── Send one HPGL command ─────────────────────────────
                first = not self._init_sent
                hpgl = moves_to_hpgl(
                    [move],
                    include_init=first,
                    offset_x=self._offset_x,
                    offset_y=self._offset_y,
                    xy_speed_mms=self._speeds.xy_machining_mm_min / 60.0 if first else None,
                    z_speed_mms=self._speeds.z_machining_mm_min / 60.0 if first else None,
                )
                if first:
                    self._init_sent = True
                self._port.write(hpgl)
                self.line_sent.emit(hpgl.decode(errors="replace").strip())
                self.progress.emit(i + 1, total)
                self._last_sent_move = move

                # ── Synchronisation ───────────────────────────────────
                if self._sync_mode == "os_query":
                    if (i + 1) % self._os_interval == 0:
                        self._os_sync(confirmed_index=i)
                else:
                    wait = self._estimate_seconds(move) * self._throttle
                    if wait > 0:
                        time.sleep(wait)

                i += 1

            # Final OS; — wait for machine to finish remaining moves
            if not stopped and self._sync_mode == "os_query":
                self._os_sync(confirmed_index=total - 1,
                               timeout=_OS_RESPONSE_TIMEOUT)

            if stopped:
                self.job_stopped.emit()
            else:
                self.job_finished.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

    # ------------------------------------------------------------------
    # Pause / retract helpers

    def _current_ref_move(self) -> Optional[Move]:
        return self._last_confirmed_move or self._last_sent_move

    def _retract_if_cutting(self) -> bool:
        """Send PU; if cutter is in PD state. Returns True if sent."""
        ref = self._current_ref_move()
        if ref is None or not ref.pen_down:
            return False
        self._port.write(b"PU;\n")
        self.line_sent.emit("[PAUSE] PU; sent — cutter raised to travel height")
        self.retracted.emit(True)
        return True

    def _reengage(self):
        """Send PD; to lower cutter back to the stored !PZ depth."""
        self._port.write(b"PD;\n")
        self.line_sent.emit("[RESUME] PD; sent — cutter lowered to cutting depth")
        self.retracted.emit(False)

    # ------------------------------------------------------------------
    # OS; synchronisation

    def _os_sync(self, confirmed_index: int = -1,
                 timeout: float = _OS_RESPONSE_TIMEOUT):
        try:
            self._port.write(b"OS;\n")
            deadline = time.time() + timeout
            while time.time() < deadline:
                if self._stopped:
                    return
                if self._paused:
                    time.sleep(0.05)
                    continue
                if self._port.in_waiting:
                    self._port.read(self._port.in_waiting)
                    if 0 <= confirmed_index < len(self._moves):
                        self._last_confirmed_move = self._moves[confirmed_index]
                        self.confirmed_index.emit(confirmed_index)
                    return
                time.sleep(0.015)
            self.line_sent.emit(
                f"[WARN] OS; timeout after {timeout:.0f} s — continuing anyway."
            )
        except Exception as exc:
            self.line_sent.emit(f"[WARN] OS; error: {exc}")

    # ------------------------------------------------------------------
    # Duration estimate (throttle mode)

    def _estimate_seconds(self, move: Move) -> float:
        dx = move.to_pos.x - move.from_pos.x
        dy = move.to_pos.y - move.from_pos.y
        dz = abs(move.to_pos.z - move.from_pos.z)
        xy_dist = math.sqrt(dx * dx + dy * dy)
        t = 0.0
        if xy_dist > 0:
            spd = (self._speeds.xy_machining_mm_min if move.pen_down
                   else self._speeds.xy_travel_mm_min)
            if spd > 0:
                t += (xy_dist / spd) * 60.0
        if dz > 0:
            spd = (self._speeds.z_machining_mm_min if move.pen_down
                   else self._speeds.z_travel_mm_min)
            if spd > 0:
                t += (dz / spd) * 60.0
        return t
