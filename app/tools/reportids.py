"""List report IDs / usages per HID collection (from preparsed data) for Magic Mouse 2."""
import ctypes, ctypes.wintypes as wt, pathlib, sys
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mmstudio import hid

class VALUE_CAPS(ctypes.Structure):
    _fields_ = [("UsagePage", wt.USHORT), ("ReportID", ctypes.c_ubyte), ("IsAlias", ctypes.c_ubyte),
                ("BitField", wt.USHORT), ("LinkCollection", wt.USHORT), ("LinkUsage", wt.USHORT), ("LinkUsagePage", wt.USHORT),
                ("IsRange", ctypes.c_ubyte), ("IsStringRange", ctypes.c_ubyte), ("IsDesignatorRange", ctypes.c_ubyte), ("IsAbsolute", ctypes.c_ubyte),
                ("HasNull", ctypes.c_ubyte), ("Reserved", ctypes.c_ubyte), ("BitSize", wt.USHORT), ("ReportCount", wt.USHORT),
                ("Reserved2", wt.USHORT * 5), ("UnitsExp", wt.ULONG), ("Units", wt.ULONG), ("LogicalMin", wt.LONG), ("LogicalMax", wt.LONG),
                ("PhysicalMin", wt.LONG), ("PhysicalMax", wt.LONG), ("UsageMin", wt.USHORT), ("UsageMax", wt.USHORT),
                ("StringMin", wt.USHORT), ("StringMax", wt.USHORT), ("DesignatorMin", wt.USHORT), ("DesignatorMax", wt.USHORT),
                ("DataIndexMin", wt.USHORT), ("DataIndexMax", wt.USHORT)]

H = ctypes.WinDLL("hid.dll")
for kind_name, kind in (("In", 0), ("Feat", 2)):
    pass
for p in hid.interface_paths():
    if "pid_0269" not in p.lower():
        continue
    d = hid.HidDevice(p, write=False)
    pp = ctypes.c_void_p(); H.HidD_GetPreparsedData(ctypes.c_void_p(d.handle), ctypes.byref(pp))
    print(d.info.kind, p.split("#")[1])
    for kn, k in (("Input", 0), ("Output", 1), ("Feature", 2)):
        for fn, cnt in (("HidP_GetValueCaps", 64), ("HidP_GetButtonCaps", 64)):
            arr = (VALUE_CAPS * cnt)(); n = wt.USHORT(cnt)
            if getattr(H, fn)(k, arr, ctypes.byref(n), pp) == 0x110000:
                for c in arr[: n.value]:
                    u = f"{c.UsageMin:#x}-{c.UsageMax:#x}" if c.IsRange else f"{c.UsageMin:#x}"
                    extra = f" bits={c.BitSize}x{c.ReportCount}" if fn.endswith("ValueCaps") else ""
                    print(f"   {kn:7} {fn[9:14]} id=0x{c.ReportID:02X} UP=0x{c.UsagePage:04X} U={u}{extra}")
    H.HidD_FreePreparsedData(pp); d.close()
