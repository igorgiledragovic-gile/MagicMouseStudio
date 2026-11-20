"""Capture raw frames from mmsfilter and decode them.  usage: python -I tools/capture.py [seconds] [--enable HEX]"""
import argparse, collections, pathlib, sys, threading, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mmstudio import protocol
from mmstudio.driverlink import DriverLink

ap = argparse.ArgumentParser()
ap.add_argument("seconds", nargs="?", type=float, default=15)
ap.add_argument("--enable")
ap.add_argument("--log", default=str(pathlib.Path(__file__).resolve().parents[1] / "captures" / time.strftime("cap-%Y%m%d-%H%M%S.txt")))
a = ap.parse_args()

link = DriverLink()
if a.enable:
    link.set_feature(bytes.fromhex(a.enable))
print("status:", link.status())
frames = []
done = threading.Event()

def reader():
    while not done.is_set():
        try:
            frames.append(link.read_frame())
        except OSError:
            return

t = threading.Thread(target=reader, daemon=True); t.start()
print(f"capturing {a.seconds}s — touch the mouse with 1, 2, 3 fingers ...")
time.sleep(a.seconds); done.set(); link.cancel(); t.join(1)

by = collections.Counter((f.data[0], len(f.data)) for f in frames)
print("frames:", len(frames), " by (id,len):", {f"0x{k[0]:02X}/{k[1]}": v for k, v in sorted(by.items())})
pathlib.Path(a.log).parent.mkdir(exist_ok=True)
with open(a.log, "w") as fh:
    for f in frames:
        fh.write(f"{f.time_s:.4f} {f.seq} drop={f.dropped} {f.data.hex(' ')}\n")
shown = 0
for f in frames:
    fr = protocol.parse_report(f.data)
    if fr and fr.touches and shown < 12:
        shown += 1
        print(f"  btn={fr.buttons} d=({fr.dx},{fr.dy}) " + " | ".join(
            f"id{t.id} ({t.x},{t.y}) maj{t.major} min{t.minor} sz{t.size} or{t.orientation} st{t.state>>4}" for t in fr.touches))
    b = protocol.parse_battery(f.data)
    if b:
        print("  battery:", b.percent, "% flags", hex(b.flags))
print("log:", a.log)
print("status:", link.status())
