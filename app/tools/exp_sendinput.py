"""Isolate the SendInput hang. usage: python tools/exp_sendinput.py MODE
MODE: nohook-thread | hook-thread | hook-main | hook-thread-qt"""
import os, pathlib, sys, threading, time
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from mmstudio import winput
from mmstudio.hook import MouseHook

mode = sys.argv[1]
h = None
if mode.startswith("hook"):
    h = MouseHook()
    print("hook start:", h.start(), flush=True)
done = threading.Event()


def worker():
    for i in range(5):
        t = time.perf_counter()
        winput.wheel(int(os.environ.get("D","1")))                     # delta 0: no visible scrolling
        print(f"  sendinput {i} took {1000 * (time.perf_counter() - t):.1f} ms", flush=True)
    done.set()


if mode == "hook-main":
    worker()
elif mode == "hook-thread-qt":
    from PySide6.QtWidgets import QApplication, QLabel
    from PySide6.QtCore import QTimer
    app = QApplication([])
    lab = QLabel("exp"); lab.show()
    threading.Thread(target=worker, daemon=True).start()
    QTimer.singleShot(3000, app.quit)
    app.exec()
else:
    threading.Thread(target=worker, daemon=True).start()
print("finished:", done.wait(5), flush=True)
if h:
    h.stop()
os._exit(0)
