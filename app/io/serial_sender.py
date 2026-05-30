from __future__ import annotations
import time
import math

from PyQt6.QtCore import QThread, pyqtSignal

from app.model.types import Move, SpeedSettings
from app.io.hpgl_writer import moves_to_hpgl


class SerialSender(QThread):
    progress = pyqtSignal(int, int)       # sent_count, total_count
    line_sent = pyqtSignal(str)           # hpgl text for log
    job_finished = pyqtSignal()
    job_stopped = pyqtSignal()
    error_occurred = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._moves: list[Move] = []
        self._speeds: SpeedSettings = SpeedSettings()
        self._port = None                 # open serial.Serial instance
        self._throttle: float = 0.8
        self._use_zi_sync: bool = False
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
        use_zi_sync: bool = False,
        offset_x: float = 0.0,
        offset_y: float = 0.0,
    ):
        self._port = port
        self._moves = moves
        self._speeds = speeds
        self._throttle = throttle_factor
        self._use_zi_sync = use_zi_sync
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

    def run(self):
        total = len(self._moves)
        stopped = False
        try:
            for i, move in enumerate(self._moves):
                while self._paused and not self._stopped:
                    time.sleep(0.05)
                if self._stopped:
                    self._port.write(b"PU;IN;\n")
                    stopped = True
                    break

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

                if self._use_zi_sync:
                    self._port.write(b"ZI\n")
                    deadline = time.time() + 10.0
                    buf = b""
                    while time.time() < deadline and not self._stopped:
                        if self._port.in_waiting:
                            buf += self._port.read(self._port.in_waiting)
                            if b"ME-500" in buf:
                                break
                        time.sleep(0.01)
                    else:
                        if not self._stopped:
                            raise TimeoutError(
                                "ZI sync: no response from machine (timeout 10 s)"
                            )
                else:
                    wait = self._estimate_seconds(move) * self._throttle
                    if wait > 0:
                        time.sleep(wait)

            if stopped:
                self.job_stopped.emit()
            else:
                self.job_finished.emit()
        except Exception as exc:
            self.error_occurred.emit(str(exc))

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
