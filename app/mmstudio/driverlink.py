"""User-mode side of mmsfilter.sys (\\\\.\\MagicMouseStudio). Mirrors driver/src/mmsfilter_public.h."""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateFileW.restype = wt.HANDLE
k32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
k32.DeviceIoControl.argtypes = [wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD, ctypes.c_void_p, wt.DWORD,
                                ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
k32.CloseHandle.argtypes = [wt.HANDLE]

FILE_DEVICE_MMS = 0x8A4D
MMS_MAX_REPORT = 64


def _ctl(func: int, access: int) -> int:
    return (FILE_DEVICE_MMS << 16) | (access << 14) | (func << 2) | 0  # METHOD_BUFFERED


IOCTL_MMS_SET_FEATURE = _ctl(0x801, 2)
IOCTL_MMS_GET_STATUS = _ctl(0x802, 1)
IOCTL_MMS_READ_FRAME = _ctl(0x803, 1)
MMS_FRAME_MAX = 512
SOURCE_USB, SOURCE_BT = 1, 2


class _MMS_FRAME(ctypes.Structure):
    _fields_ = [("Seq", wt.ULONG), ("Source", wt.ULONG), ("Length", wt.ULONG), ("Dropped", wt.ULONG),
                ("Time100ns", ctypes.c_ulonglong), ("Data", ctypes.c_ubyte * MMS_FRAME_MAX)]


@dataclass
class RawFrame:
    seq: int
    source: int
    dropped: int
    time_s: float
    data: bytes


class _MMS_STATUS(ctypes.Structure):
    _fields_ = [("Version", wt.ULONG), ("DeviceCount", wt.ULONG), ("Connected", wt.ULONG),
                ("ControlDeviceStatus", wt.LONG), ("UsbCreateStatus", wt.LONG), ("InterfaceNumber", wt.ULONG),
                ("SendCount", wt.ULONG), ("LastStatus", wt.LONG), ("LastBytes", wt.ULONG), ("LastLen", wt.ULONG),
                ("LastReport", ctypes.c_ubyte * MMS_MAX_REPORT),
                ("FramesSeen", wt.ULONG), ("FramesDropped", wt.ULONG), ("UrbsHooked", wt.ULONG),
                ("BatteryPercent", wt.LONG), ("BatteryFlags", wt.ULONG),
                ("BatteryTime100ns", ctypes.c_ulonglong), ("Now100ns", ctypes.c_ulonglong)]


@dataclass
class DriverStatus:
    version: int
    devices: int
    connected: bool
    usb_create_status: int
    interface: int
    send_count: int
    last_status: int
    last_report: bytes
    frames_seen: int = 0
    frames_dropped: int = 0
    urbs_hooked: int = 0
    battery_percent: int = -1
    battery_flags: int = 0
    battery_age_s: float | None = None

    @property
    def last_ok(self) -> bool:
        return self.last_status >= 0 and self.send_count > 0


class DriverLink:
    PATH = r"\\.\MagicMouseStudio"

    def __init__(self):
        self.h = k32.CreateFileW(self.PATH, 0xC0000000, 3, None, 3, 0, None)
        if self.h == wt.HANDLE(-1).value:
            raise OSError(ctypes.get_last_error(), "mmsfilter control device not available")

    def _ioctl(self, code: int, inbuf: bytes | None, outsize: int) -> bytes:
        ib = ctypes.create_string_buffer(inbuf, len(inbuf)) if inbuf else None
        ob = ctypes.create_string_buffer(outsize) if outsize else None
        got = wt.DWORD()
        ok = k32.DeviceIoControl(self.h, code, ib, len(inbuf) if inbuf else 0, ob, outsize, ctypes.byref(got), None)
        if not ok:
            raise OSError(ctypes.get_last_error(), f"IOCTL 0x{code:08X} failed")
        return ob.raw[: got.value] if ob else b""

    def status(self) -> DriverStatus:
        s = _MMS_STATUS.from_buffer_copy(self._ioctl(IOCTL_MMS_GET_STATUS, None, ctypes.sizeof(_MMS_STATUS)))
        u32 = lambda v: v & 0xFFFFFFFF
        return DriverStatus(s.Version, s.DeviceCount, bool(s.Connected), u32(s.UsbCreateStatus), s.InterfaceNumber,
                            s.SendCount, s.LastStatus, bytes(s.LastReport[: s.LastLen]),
                            s.FramesSeen, s.FramesDropped, s.UrbsHooked, s.BatteryPercent, s.BatteryFlags,
                            (s.Now100ns - s.BatteryTime100ns) / 1e7 if s.BatteryPercent >= 0 else None)

    def set_feature(self, report: bytes) -> None:
        self._ioctl(IOCTL_MMS_SET_FEATURE, report, 0)

    def read_frame(self) -> RawFrame:
        """Blocks until the mouse sends the next raw packet (cancel with cancel())."""
        f = _MMS_FRAME.from_buffer_copy(self._ioctl(IOCTL_MMS_READ_FRAME, None, ctypes.sizeof(_MMS_FRAME)))
        return RawFrame(f.Seq, f.Source, f.Dropped, f.Time100ns / 1e7, bytes(f.Data[: f.Length]))

    def cancel(self) -> None:
        k32.CancelIoEx(wt.HANDLE(self.h), None)

    def close(self):
        if self.h:
            k32.CloseHandle(self.h)
            self.h = None


def available() -> bool:
    try:
        DriverLink().close()
        return True
    except OSError:
        return False
