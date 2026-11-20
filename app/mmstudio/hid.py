"""Minimal Windows HID access via ctypes (hid.dll + setupapi.dll + kernel32).

No third-party packages: enumerate HID interfaces, read capabilities,
read input reports (overlapped), get/set feature and input reports.
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes as wt
from dataclasses import dataclass

hid = ctypes.WinDLL("hid.dll")
setupapi = ctypes.WinDLL("setupapi.dll")
kernel32 = ctypes.WinDLL("kernel32.dll", use_last_error=True)

GENERIC_READ = 0x80000000
GENERIC_WRITE = 0x40000000
FILE_SHARE_RW = 0x3
OPEN_EXISTING = 3
FILE_FLAG_OVERLAPPED = 0x40000000
INVALID_HANDLE = wt.HANDLE(-1).value
DIGCF_PRESENT_INTERFACE = 0x12
ERROR_IO_PENDING = 997
WAIT_TIMEOUT = 0x102


class GUID(ctypes.Structure):
    _fields_ = [("d1", wt.DWORD), ("d2", wt.WORD), ("d3", wt.WORD), ("d4", ctypes.c_ubyte * 8)]


class SP_DEVICE_INTERFACE_DATA(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("guid", GUID), ("flags", wt.DWORD), ("reserved", ctypes.c_void_p)]


class HIDD_ATTRIBUTES(ctypes.Structure):
    _fields_ = [("Size", wt.ULONG), ("VendorID", wt.USHORT), ("ProductID", wt.USHORT), ("Version", wt.USHORT)]


class HIDP_CAPS(ctypes.Structure):
    _fields_ = [
        ("Usage", wt.USHORT), ("UsagePage", wt.USHORT),
        ("InputReportByteLength", wt.USHORT), ("OutputReportByteLength", wt.USHORT),
        ("FeatureReportByteLength", wt.USHORT), ("Reserved", wt.USHORT * 17),
        ("NumberLinkCollectionNodes", wt.USHORT),
        ("NumberInputButtonCaps", wt.USHORT), ("NumberInputValueCaps", wt.USHORT), ("NumberInputDataIndices", wt.USHORT),
        ("NumberOutputButtonCaps", wt.USHORT), ("NumberOutputValueCaps", wt.USHORT), ("NumberOutputDataIndices", wt.USHORT),
        ("NumberFeatureButtonCaps", wt.USHORT), ("NumberFeatureValueCaps", wt.USHORT), ("NumberFeatureDataIndices", wt.USHORT),
    ]


class OVERLAPPED(ctypes.Structure):
    _fields_ = [("Internal", ctypes.c_void_p), ("InternalHigh", ctypes.c_void_p),
                ("Offset", wt.DWORD), ("OffsetHigh", wt.DWORD), ("hEvent", wt.HANDLE)]


setupapi.SetupDiGetClassDevsW.restype = wt.HANDLE
setupapi.SetupDiGetClassDevsW.argtypes = [ctypes.POINTER(GUID), wt.LPCWSTR, wt.HWND, wt.DWORD]
setupapi.SetupDiEnumDeviceInterfaces.argtypes = [wt.HANDLE, ctypes.c_void_p, ctypes.POINTER(GUID), wt.DWORD,
                                                 ctypes.POINTER(SP_DEVICE_INTERFACE_DATA)]
setupapi.SetupDiGetDeviceInterfaceDetailW.argtypes = [wt.HANDLE, ctypes.POINTER(SP_DEVICE_INTERFACE_DATA),
                                                      ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.c_void_p]
setupapi.SetupDiDestroyDeviceInfoList.argtypes = [wt.HANDLE]
kernel32.CreateFileW.restype = wt.HANDLE
kernel32.CreateFileW.argtypes = [wt.LPCWSTR, wt.DWORD, wt.DWORD, ctypes.c_void_p, wt.DWORD, wt.DWORD, wt.HANDLE]
kernel32.ReadFile.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.DWORD, ctypes.POINTER(wt.DWORD), ctypes.POINTER(OVERLAPPED)]
kernel32.GetOverlappedResult.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED), ctypes.POINTER(wt.DWORD), wt.BOOL]
kernel32.CancelIoEx.argtypes = [wt.HANDLE, ctypes.POINTER(OVERLAPPED)]
kernel32.CreateEventW.restype = wt.HANDLE
kernel32.CreateEventW.argtypes = [ctypes.c_void_p, wt.BOOL, wt.BOOL, wt.LPCWSTR]
kernel32.WaitForSingleObject.argtypes = [wt.HANDLE, wt.DWORD]
kernel32.CloseHandle.argtypes = [wt.HANDLE]
for _fn in ("HidD_GetFeature", "HidD_SetFeature", "HidD_GetInputReport", "HidD_SetOutputReport"):
    getattr(hid, _fn).argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]
hid.HidD_GetAttributes.argtypes = [wt.HANDLE, ctypes.POINTER(HIDD_ATTRIBUTES)]
hid.HidD_GetPreparsedData.argtypes = [wt.HANDLE, ctypes.POINTER(ctypes.c_void_p)]
hid.HidD_FreePreparsedData.argtypes = [ctypes.c_void_p]
hid.HidP_GetCaps.argtypes = [ctypes.c_void_p, ctypes.POINTER(HIDP_CAPS)]
hid.HidD_GetProductString.argtypes = [wt.HANDLE, ctypes.c_void_p, wt.ULONG]


def _hid_guid() -> GUID:
    g = GUID()
    hid.HidD_GetHidGuid(ctypes.byref(g))
    return g


def interface_paths(guid: GUID | None = None) -> list[str]:
    """Device interface paths for a class GUID (default: all present HID interfaces)."""
    g = guid or _hid_guid()
    devs = setupapi.SetupDiGetClassDevsW(ctypes.byref(g), None, None, DIGCF_PRESENT_INTERFACE)
    if devs == INVALID_HANDLE:
        return []
    out: list[str] = []
    try:
        i = 0
        while True:
            ifd = SP_DEVICE_INTERFACE_DATA(cbSize=ctypes.sizeof(SP_DEVICE_INTERFACE_DATA))
            if not setupapi.SetupDiEnumDeviceInterfaces(devs, None, ctypes.byref(g), i, ctypes.byref(ifd)):
                break
            i += 1
            need = wt.DWORD()
            setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(ifd), None, 0, ctypes.byref(need), None)
            buf = ctypes.create_string_buffer(need.value)
            ctypes.cast(buf, ctypes.POINTER(wt.DWORD))[0] = 8  # cbSize of SP_DEVICE_INTERFACE_DETAIL_DATA_W on x64
            if setupapi.SetupDiGetDeviceInterfaceDetailW(devs, ctypes.byref(ifd), buf, need, None, None):
                out.append(ctypes.wstring_at(ctypes.addressof(buf) + 4))
    finally:
        setupapi.SetupDiDestroyDeviceInfoList(devs)
    return out


@dataclass
class HidInfo:
    path: str
    vid: int
    pid: int
    usage_page: int
    usage: int
    in_len: int
    out_len: int
    feat_len: int
    product: str

    @property
    def kind(self) -> str:
        return f"UP=0x{self.usage_page:04X} U=0x{self.usage:04X} in={self.in_len} out={self.out_len} feat={self.feat_len}"


class HidDevice:
    """One HID top-level collection opened for overlapped I/O."""

    def __init__(self, path: str, write: bool = True):
        self.path = path
        access = GENERIC_READ | (GENERIC_WRITE if write else 0)
        h = kernel32.CreateFileW(path, access, FILE_SHARE_RW, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if h == INVALID_HANDLE and write:  # some collections only allow read
            h = kernel32.CreateFileW(path, GENERIC_READ, FILE_SHARE_RW, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if h == INVALID_HANDLE:
            h = kernel32.CreateFileW(path, 0, FILE_SHARE_RW, None, OPEN_EXISTING, FILE_FLAG_OVERLAPPED, None)
        if h == INVALID_HANDLE:
            raise OSError(ctypes.get_last_error(), f"CreateFile failed: {path}")
        self.handle = h
        self._event = kernel32.CreateEventW(None, True, False, None)
        self.info = self._query()

    def _query(self) -> HidInfo:
        attrs = HIDD_ATTRIBUTES(Size=ctypes.sizeof(HIDD_ATTRIBUTES))
        hid.HidD_GetAttributes(self.handle, ctypes.byref(attrs))
        caps = HIDP_CAPS()
        pp = ctypes.c_void_p()
        if hid.HidD_GetPreparsedData(self.handle, ctypes.byref(pp)):
            hid.HidP_GetCaps(pp, ctypes.byref(caps))
            hid.HidD_FreePreparsedData(pp)
        name = ctypes.create_unicode_buffer(128)
        hid.HidD_GetProductString(self.handle, name, ctypes.sizeof(name))
        return HidInfo(self.path, attrs.VendorID, attrs.ProductID, caps.UsagePage, caps.Usage,
                       caps.InputReportByteLength, caps.OutputReportByteLength, caps.FeatureReportByteLength,
                       name.value)

    # -- reports ---------------------------------------------------------
    def read(self, timeout_ms: int = 100) -> bytes | None:
        """One input report, or None on timeout."""
        n = max(self.info.in_len, 1)
        buf = ctypes.create_string_buffer(n)
        ov = OVERLAPPED(hEvent=self._event)
        kernel32.ResetEvent(self._event)
        got = wt.DWORD()
        if not kernel32.ReadFile(self.handle, buf, n, ctypes.byref(got), ctypes.byref(ov)):
            err = ctypes.get_last_error()
            if err != ERROR_IO_PENDING:
                raise OSError(err, "ReadFile failed")
            if kernel32.WaitForSingleObject(self._event, timeout_ms) == WAIT_TIMEOUT:
                kernel32.CancelIoEx(self.handle, ctypes.byref(ov))
                kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(got), True)
                return None
            if not kernel32.GetOverlappedResult(self.handle, ctypes.byref(ov), ctypes.byref(got), False):
                raise OSError(ctypes.get_last_error(), "GetOverlappedResult failed")
        return buf.raw[: got.value]

    def get_feature(self, report_id: int, length: int | None = None) -> bytes | None:
        n = length or max(self.info.feat_len, 2)
        buf = ctypes.create_string_buffer(n)
        buf[0] = report_id
        return buf.raw if hid.HidD_GetFeature(self.handle, buf, n) else None

    def set_feature(self, data: bytes, pad_to_caps: bool = True) -> bool:
        n = max(len(data), self.info.feat_len) if pad_to_caps else len(data)
        buf = ctypes.create_string_buffer(bytes(data), n)
        return bool(hid.HidD_SetFeature(self.handle, buf, n))

    def get_input(self, report_id: int, length: int | None = None) -> bytes | None:
        n = length or max(self.info.in_len, 2)
        buf = ctypes.create_string_buffer(n)
        buf[0] = report_id
        return buf.raw if hid.HidD_GetInputReport(self.handle, buf, n) else None

    def close(self) -> None:
        if self.handle:
            kernel32.CloseHandle(self.handle)
            kernel32.CloseHandle(self._event)
            self.handle = 0

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()


def enumerate_hid(path_filter=None) -> list[HidInfo]:
    """Info for every present HID collection whose path matches `path_filter(path)`."""
    out = []
    for p in interface_paths():
        if path_filter and not path_filter(p.lower()):
            continue
        try:
            with HidDevice(p, write=False) as d:
                out.append(d.info)
        except OSError:
            continue
    return out
