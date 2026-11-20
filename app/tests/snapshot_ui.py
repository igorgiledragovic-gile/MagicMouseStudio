"""Render every page of the main window (with captured or synthetic data) to PNGs for visual checks.
usage: .venv\\Scripts\\python.exe tests\\snapshot_ui.py [capture.txt] [out_dir]"""
import faulthandler, os, pathlib, sys
faulthandler.dump_traceback_later(40, exit=True)    # never hang a test run
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QApplication
from mmstudio import protocol
from mmstudio.engine import BatteryInfo, LinkState
from mmstudio.settings import Settings
from mmstudio.ui.main import STYLE, MainWindow
Settings.save = lambda self: None          # never touch the user's real settings file from a test

out_dir = pathlib.Path(sys.argv[2] if len(sys.argv) > 2 else pathlib.Path(__file__).with_name("snapshots"))
out_dir.mkdir(parents=True, exist_ok=True)
LANG = os.environ.get("MMS_LANG", "en")
from mmstudio import i18n
i18n.set_language(LANG)
app = QApplication(sys.argv)
app.setStyleSheet(STYLE)
if i18n.is_rtl():
    from PySide6.QtCore import Qt
    app.setLayoutDirection(Qt.RightToLeft)
_s = Settings()
_s.language = LANG
w = MainWindow(_s, start_services=False)   # no device, no hook: only the data fed below
w.show()

frame = None
if len(sys.argv) > 1 and os.path.exists(sys.argv[1]):
    for line in open(sys.argv[1]):
        _, _, _, *hx = line.split()
        fr = protocol.parse_report(bytes.fromhex("".join(hx)))
        if fr and fr.touches:
            w.on_frame(fr)
            if frame is None or len(fr.touches) > len(frame.touches):
                frame = fr
if frame is None:
    frame = protocol.TouchFrame(0, 0, 0, [
        protocol.Touch(1, -600, -900, 150, 120, 10, -6, 0x40),
        protocol.Touch(2, 100, -700, 140, 125, 10, 0, 0x40),
        protocol.Touch(3, 700, 300, 160, 130, 10, 8, 0x30)])
w.on_frame(frame)
w.on_battery(BatteryInfo(100, 0, "bt", 75))
w.on_link(LinkState(True, True, False, 88, 1879, 0))
for a in ("nav-back", "tap 1 → left", "desktop-next"):
    w._on_action(a)

pages = [int(x) for x in os.environ.get("MMS_PAGES", ",".join(str(i) for i in range(w.stack.count()))).split(",")]


def snap():
    i = pages.pop(0)
    w.nav.setCurrentRow(i)
    w._refresh_live()

    def grab():
        name = w.pages[i][0].replace(" ", "_")
        p = out_dir / f"{i}_{name}.png"
        w.grab().save(str(p))
        print("saved", p)
        if pages:
            snap()
        else:
            w.quit()
    QTimer.singleShot(150, grab)


QTimer.singleShot(300, snap)
app.exec()
