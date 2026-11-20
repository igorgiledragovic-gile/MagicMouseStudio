"""Background data service: touch frames + battery from mmsfilter (BT) and USB battery.

Robustness rules (learned the hard way):
  * the reader thread never injects input itself (winput uses its own injector thread), so a
    blocked SendInput on the system can never stop the sensor stream;
  * a watchdog restarts the reader when the driver receives frames that the app does not read;
  * every exception in the reader is logged to %LOCALAPPDATA%\\MagicMouseStudio\\error.log.
"""
from __future__ import annotations

import threading
import time
import traceback
from dataclasses import dataclass

from PySide6.QtCore import QObject, QTimer, Signal

from . import hid, protocol, winput
from .driverlink import SOURCE_BT, DriverLink
from .settings import DATA_DIR

BT_HID_MARK = "0001004c_pid&0269"
USB_BATTERY_MARK = "vid_05ac&pid_0269&mi_00&col02"


def log_error(where: str) -> None:
    try:
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        with open(DATA_DIR / "error.log", "a", encoding="utf-8") as fh:
            fh.write(time.strftime("%Y-%m-%d %H:%M:%S ") + where + ": " + traceback.format_exc() + "\n")
    except OSError:
        pass


@dataclass
class BatteryInfo:
    percent: int
    flags: int
    source: str             # "bt" | "usb"
    age_s: float            # seconds since the mouse reported it

    @property
    def on_cable(self) -> bool:
        return self.source == "usb"


@dataclass
class LinkState:
    driver: bool            # mmsfilter control device reachable
    bt_connected: bool      # BT HID collection present (mouse connected over Bluetooth)
    usb_present: bool       # mouse plugged in with a data cable
    fps: float
    frames: int
    dropped: int
    input_ok: bool = True           # SendInput is not blocked
    input_blocked_s: float = 0.0
    reader_restarts: int = 0


class MouseService(QObject):
    frameReady = Signal(object)      # protocol.TouchFrame
    batteryChanged = Signal(object)  # BatteryInfo
    linkChanged = Signal(object)     # LinkState

    def __init__(self, parent=None, input_engine=None):
        super().__init__(parent)
        self.input_engine = input_engine
        self._run = True
        self._lock = threading.Lock()
        self._link: DriverLink | None = None
        self._gen = 0                       # reader generation; an older reader exits when it changes
        self._reads = 0                     # every frame read (any report)
        self._frames = 0                    # touch frames
        self._fps_frames = 0
        self._fps = 0.0
        self._fps_t = time.monotonic()
        self._dropped = 0
        self._last_usb_poll = 0.0
        self._usb_battery: BatteryInfo | None = None
        self._wd_seen = None                # driver FramesSeen at the last poll
        self._wd_reads = 0
        self._wd_strikes = 0
        self.reader_restarts = 0
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)

    def start(self):
        self._start_reader()
        self._timer.start(1500)
        QTimer.singleShot(200, self._poll)

    def stop(self):
        self._run = False
        self._timer.stop()
        self._gen += 1
        with self._lock:
            if self._link:
                self._link.cancel()

    # ---- reader thread ------------------------------------------------
    def _start_reader(self):
        self._gen += 1
        with self._lock:
            if self._link:
                self._link.cancel()          # wakes a reader blocked in the driver
        threading.Thread(target=self._reader, args=(self._gen,), name=f"mms-reader-{self._gen}", daemon=True).start()

    def _reader(self, gen: int):
        while self._run and gen == self._gen:
            try:
                link = DriverLink()
            except OSError:
                time.sleep(2)
                continue
            with self._lock:
                self._link = link
            try:
                while self._run and gen == self._gen:
                    f = link.read_frame()
                    if gen != self._gen:
                        break
                    self._reads += 1
                    self._dropped += f.dropped
                    if f.source != SOURCE_BT or not f.data:
                        continue
                    rid = f.data[0]
                    if rid == protocol.REPORT_TOUCH:
                        fr = protocol.parse_report(f.data)
                        if fr:
                            if self.input_engine is not None:
                                try:
                                    self.input_engine.feed(fr)
                                except Exception:   # a gesture bug must never stop the data stream
                                    log_error("engine.feed")
                            self._frames += 1
                            self._fps_frames += 1
                            self.frameReady.emit(fr)
                    elif rid == protocol.REPORT_BATTERY:
                        b = protocol.parse_battery(f.data)
                        if b:
                            self.batteryChanged.emit(BatteryInfo(b.percent, b.flags, "bt", 0.0))
            except OSError:
                pass
            except Exception:
                log_error("reader")
            finally:
                with self._lock:
                    if self._link is link:
                        self._link = None
                link.close()
            if self._run and gen == self._gen:
                time.sleep(1)

    # ---- periodic poll (GUI thread) --------------------------------------
    def _poll(self):
        try:
            self._poll_inner()
        except Exception:
            log_error("poll")

    def _poll_inner(self):
        paths = [p.lower() for p in hid.interface_paths()]
        bt = any(BT_HID_MARK in p for p in paths)
        usb_path = next((p for p in paths if USB_BATTERY_MARK in p), None)

        driver_ok = False
        try:
            st = DriverLink()
            s = st.status()
            st.close()
            driver_ok = True
            if s.battery_percent >= 0 and usb_path is None:
                self.batteryChanged.emit(BatteryInfo(s.battery_percent, s.battery_flags, "bt", s.battery_age_s or 0.0))
            # watchdog: the driver got new frames but this app read none of them -> restart the reader
            if self._wd_seen is not None and s.frames_seen > self._wd_seen and self._reads == self._wd_reads:
                self._wd_strikes += 1
                if self._wd_strikes >= 2:
                    self._wd_strikes = 0
                    self.reader_restarts += 1
                    try:
                        raise RuntimeError(f"reader stalled (driver frames {self._wd_seen}->{s.frames_seen}); restarting")
                    except RuntimeError:
                        log_error("watchdog")
                    self._start_reader()
            else:
                self._wd_strikes = 0
            self._wd_seen, self._wd_reads = s.frames_seen, self._reads
        except OSError:
            pass

        now = time.monotonic()
        if usb_path and now - self._last_usb_poll > 20:
            self._last_usb_poll = now
            try:
                with hid.HidDevice(usb_path, write=False) as d:
                    r = d.get_input(protocol.REPORT_BATTERY, 3)
                b = protocol.parse_battery(r or b"")
                if b:
                    self._usb_battery = BatteryInfo(b.percent, b.flags, "usb", 0.0)
            except OSError:
                pass
        if usb_path and self._usb_battery:
            self.batteryChanged.emit(self._usb_battery)
        if not usb_path:
            self._usb_battery = None

        dt = now - self._fps_t
        if dt > 0:
            self._fps = self._fps_frames / dt
        self._fps_frames, self._fps_t = 0, now
        ok, blocked, _ = winput.health()
        self.linkChanged.emit(LinkState(driver_ok, bt, usb_path is not None, self._fps, self._frames, self._dropped,
                                        ok, blocked, self.reader_restarts))
