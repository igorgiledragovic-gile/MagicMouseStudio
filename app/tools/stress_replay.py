"""Stress test of the whole app WITHOUT the mouse: recorded touch frames are replayed through a fake
driver link into the real UI + input engine + native hook.

usage: python tools/stress_replay.py SECONDS [--real-wheel] [--speed 1.0]
 - keyboard chords / clicks / browser back-forward are counted, not sent (nothing happens on screen)
 - --real-wheel sends the engine's wheel events for real (harmless scrolling of the focused window)
Prints progress every 5 s and a final verdict; exits non-zero on a stall or exception.
"""
import faulthandler, glob, os, pathlib, sys, threading, time

APP = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP))
os.environ["MMS_DEBUG_ALLOW_SECOND"] = "1"

from mmstudio import driverlink, protocol, winput, settings as settings_mod   # noqa: E402

SECONDS = float(sys.argv[1]) if len(sys.argv) > 1 and not sys.argv[1].startswith("-") else 60
REAL_WHEEL = "--real-wheel" in sys.argv
SPEED = float(sys.argv[sys.argv.index("--speed") + 1]) if "--speed" in sys.argv else 1.0
# --stall-at N: the first reader hangs forever (ignoring cancel) after N frames -> watchdog must recover
STALL_AT = int(sys.argv[sys.argv.index("--stall-at") + 1]) if "--stall-at" in sys.argv else -1
_stalled = {"done": False}
LOG = settings_mod.DATA_DIR / "stress_stacks.log"
settings_mod.DATA_DIR.mkdir(parents=True, exist_ok=True)
faulthandler.dump_traceback_later(SECONDS + 60, exit=True, file=open(LOG, "w"))

# ---- recorded frames --------------------------------------------------------------
frames = []
for f in sorted(glob.glob(str(APP / "captures" / "cap-*.txt"))):
    rows = [l.split() for l in open(f) if l.strip()]
    if not rows:
        continue
    t0 = float(rows[0][0])
    for r in rows:
        frames.append((float(r[0]) - t0, bytes.fromhex("".join(r[3:]))))
    frames.append((frames[-1][0] + 0.5, None))      # gap between files
assert frames, "no captures"
counters = {"chord": 0, "click": 0, "button": 0, "back": 0, "forward": 0, "wheel": 0, "read": 0}

# ---- fake output ------------------------------------------------------------------
_real_wheel = winput.wheel
winput.chord = lambda *a: counters.__setitem__("chord", counters["chord"] + 1)
winput.click = lambda b: counters.__setitem__("click", counters["click"] + 1)
winput.button = lambda b, d: counters.__setitem__("button", counters["button"] + 1)
winput.browser_back = lambda: counters.__setitem__("back", counters["back"] + 1)
winput.browser_forward = lambda: counters.__setitem__("forward", counters["forward"] + 1)


def _wheel(d, h=False):
    counters["wheel"] += 1
    if REAL_WHEEL:
        _real_wheel(d, h)


winput.wheel = _wheel


# ---- fake driver link -------------------------------------------------------------
class FakeLink:
    _lock = threading.Lock()
    _idx = 0
    _start = None
    _offset = 0.0

    def __init__(self):
        self._cancel = threading.Event()

    def read_frame(self):
        if STALL_AT >= 0 and not _stalled["done"] and counters["read"] >= STALL_AT:
            _stalled["done"] = True
            print("  >>> simulating a reader stuck forever", flush=True)
            threading.Event().wait()          # never returns, ignores cancel
        while True:
            if self._cancel.is_set():
                raise OSError(995, "cancelled")
            with FakeLink._lock:
                if FakeLink._start is None:
                    FakeLink._start = time.monotonic()
                t, data = frames[FakeLink._idx % len(frames)]
                lap = FakeLink._idx // len(frames)
                due = FakeLink._start + (t + lap * (frames[-1][0] + 1)) / SPEED
                if time.monotonic() >= due:
                    FakeLink._idx += 1
                    if data is None:
                        continue
                    counters["read"] += 1
                    return driverlink.RawFrame(FakeLink._idx, driverlink.SOURCE_BT, 0, time.monotonic(), data)
            time.sleep(0.001)

    def status(self):
        seen = int((time.monotonic() - (FakeLink._start or time.monotonic())) * 90)   # the "driver" keeps receiving
        return driverlink.DriverStatus(0x10100, 1, True, 0, 0, 0, 0, b"", seen, 0, seen, 87, 0, 30.0)

    def set_feature(self, report):
        pass

    def cancel(self):
        self._cancel.set()

    def close(self):
        pass


driverlink.DriverLink = FakeLink
import mmstudio.engine as engine_mod   # noqa: E402
engine_mod.DriverLink = FakeLink
settings_mod.Settings.save = lambda self: None          # don't touch the user's settings

from PySide6.QtCore import QTimer   # noqa: E402
from PySide6.QtWidgets import QApplication   # noqa: E402
from mmstudio.ui.main import STYLE, MainWindow   # noqa: E402

app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
s = settings_mod.Settings.load()
s.tap1 = s.tap2 = s.tap3 = True
s.middle_click = True
s.scroll_smooth = True                  # exercise momentum threads too
w = MainWindow(s)
w.show()

state = {"t0": time.monotonic(), "last_frames": 0, "stall": 0, "page": 0, "fail": None}


def tick():
    el = time.monotonic() - state["t0"]
    fr = w.svc._frames
    hs = w.hook.stats()
    print(f"[{el:5.0f}s] app_frames={fr} read={counters['read']} wheel={counters['wheel']} chords={counters['chord']} "
          f"back/fwd={counters['back']}/{counters['forward']} clicks={counters['click']} hook_alive={hs.alive} "
          f"restarts={w.svc.reader_restarts}", flush=True)
    if fr == state["last_frames"]:
        state["stall"] += 1
        if state["stall"] >= 3:
            state["fail"] = "STALL: frames stopped"
    else:
        state["stall"] = 0
    state["last_frames"] = fr
    # cycle through pages and toggle settings like a user would
    state["page"] = (state["page"] + 1) % w.stack.count()
    w.nav.setCurrentRow(state["page"])
    s.scroll_speed = 1 + (int(el) * 7) % 100
    s.scroll_accelerated = not s.scroll_accelerated
    if el >= SECONDS or state["fail"]:
        print("VERDICT:", state["fail"] or "OK", flush=True)
        err = settings_mod.DATA_DIR / "error.log"
        if err.exists():
            print("error.log tail:\n" + "".join(open(err, encoding="utf-8").readlines()[-15:]))
        w.quit()


t = QTimer()
t.timeout.connect(tick)
t.start(5000)
rc = app.exec()
sys.exit(1 if state["fail"] else 0)
