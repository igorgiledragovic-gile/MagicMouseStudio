"""Probe Magic Mouse 2 HID collections: caps, feature/input gets, and live reads.

usage: python -I tools/probe.py [--seconds 5] [--enable HEX] [--path-substr mi_01]
"""
import argparse, pathlib, sys, threading, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))

from mmstudio import hid, protocol


def is_mm2(p: str) -> bool:
    return ("vid_05ac&pid_0269" in p) or ("0001004c_pid&0269" in p) or ("vid_05ac&pid_0323" in p)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seconds", type=float, default=5)
    ap.add_argument("--enable", help="feature report to send first, hex (e.g. f10201)")
    ap.add_argument("--path-substr", default="")
    ap.add_argument("--gets", action="store_true", help="try GetFeature/GetInputReport on common IDs")
    a = ap.parse_args()

    devs = []
    for p in hid.interface_paths():
        pl = p.lower()
        if not is_mm2(pl) or a.path_substr not in pl:
            continue
        try:
            d = hid.HidDevice(p)
        except OSError as e:
            print("OPEN-FAIL", p, e)
            continue
        print(f"[{len(devs)}] {d.info.kind}  {p}")
        devs.append(d)

    if a.gets:
        for i, d in enumerate(devs):
            for rid in (0x02, 0x47, 0x90, 0xF1, 0xF0, 0x55, 0xC8, 0xD7, 0x01):
                f = d.get_feature(rid)
                if f:
                    print(f"  [{i}] GetFeature 0x{rid:02X} -> {f.hex(' ')}")
                r = d.get_input(rid)
                if r:
                    print(f"  [{i}] GetInput   0x{rid:02X} -> {r.hex(' ')}")

    if a.enable:
        data = bytes.fromhex(a.enable)
        for i, d in enumerate(devs):
            if d.info.feat_len:
                print(f"  [{i}] SetFeature {data.hex(' ')} (featlen {d.info.feat_len}) ->", d.set_feature(data))

    stats = {}
    stop = time.time() + a.seconds

    def reader(i, d):
        while time.time() < stop:
            try:
                r = d.read(200)
            except OSError as e:
                stats.setdefault(i, {})["err"] = str(e)
                return
            if not r:
                continue
            s = stats.setdefault(i, {"n": 0, "ids": {}, "samples": []})
            s["n"] += 1
            key = (r[0], len(r.rstrip(b"\0")))
            s["ids"][key] = s["ids"].get(key, 0) + 1
            if len(s["samples"]) < 6 or (r[0] == 0x12 and len(r.rstrip(b'\0')) > 14 and len(s["samples"]) < 12):
                s["samples"].append(r.hex(" "))

    ts = [threading.Thread(target=reader, args=(i, d), daemon=True) for i, d in enumerate(devs) if d.info.in_len]
    print(f"reading {a.seconds}s from {len(ts)} collections — touch the mouse surface now ...")
    for t in ts: t.start()
    for t in ts: t.join()
    for i, s in sorted(stats.items()):
        print(f"[{i}] {devs[i].info.kind}")
        if "err" in s:
            print("   error:", s["err"]); continue
        print("   reports:", s["n"], " by (id,len):", {f"0x{k[0]:02X}/{k[1]}": v for k, v in s["ids"].items()})
        for x in s["samples"]:
            print("   ", x)
    for d in devs:
        d.close()


if __name__ == "__main__":
    main()
