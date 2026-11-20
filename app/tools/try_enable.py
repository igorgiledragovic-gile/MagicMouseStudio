"""Try every user-mode way to send the multi-touch enable report and show Win32 errors."""
import ctypes, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mmstudio import hid

hid.hid.HidD_SetFeature.restype = ctypes.c_bool
hid.hid.HidD_SetOutputReport.restype = ctypes.c_bool
k32 = ctypes.WinDLL("kernel32", use_last_error=True)
IOCTL_HID_SET_FEATURE = 0x000B0191

for p in hid.interface_paths():
    if "vid_05ac&pid_0269" not in p.lower():
        continue
    try:
        d = hid.HidDevice(p)
    except OSError as e:
        print("open fail", p[-60:], e); continue
    print(d.info.kind, p.split('#')[1])
    for payload in ("f10201", "f1c809", "0201"):
        data = bytes.fromhex(payload)
        buf = ctypes.create_string_buffer(data, len(data))
        ok = ctypes.WinDLL("hid.dll", use_last_error=True).HidD_SetFeature(d.handle, buf, len(data))
        e1 = ctypes.get_last_error()
        ok2 = ctypes.WinDLL("hid.dll", use_last_error=True).HidD_SetOutputReport(d.handle, buf, len(data))
        e2 = ctypes.get_last_error()
        print(f"   {payload}: SetFeature={bool(ok)} err={e1}   SetOutput={bool(ok2)} err={e2}")
    d.close()
