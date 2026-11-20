"""MagicMouse Studio — utility-style main window (sidebar + settings pages) and tray."""
from __future__ import annotations

import os
import subprocess
import sys
import time
import winreg
from dataclasses import fields

from PySide6.QtCore import QObject, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QColor, QFont, QIcon, QPainter, QPainterPath, QPixmap
from PySide6.QtWidgets import (QApplication, QFrame, QGridLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow, QMenu, QMessageBox, QProgressBar,
                               QPushButton, QScrollArea, QStackedWidget, QSystemTrayIcon, QTableWidget,
                               QTableWidgetItem, QVBoxLayout, QWidget)

from .. import __version__, i18n
from ..i18n import _
from ..engine import BatteryInfo, LinkState, MouseService
from ..hook import MouseHook
from ..inputengine import InputEngine
from ..settings import (DATA_DIR, KIND_MIDDLE, KIND_PRIMARY, KIND_SECONDARY, MIDDLE_ANY_TWO,
                        MIDDLE_ONE_FINGER_CENTER, MIDDLE_THREE, MIDDLE_WIDE_TWO, OWNER_APPLE, OWNER_STUDIO,
                        SCROLL_ONE, SCROLL_ONE_OR_TWO, SCROLL_TWO, Settings)
from .mouseview import MouseView
from .widgets import ACCENT, Binder, Card, depends

APP_NAME = "MagicMouse Studio"
RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
FROZEN = bool(getattr(sys, "frozen", False))          # packaged build (PyInstaller, installed by Setup.exe)
DRIVER_DIR = (os.path.join(os.path.dirname(sys.executable), "driver") if FROZEN else
              os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "driver")))

STYLE = f"""
* {{ font-family: 'Segoe UI'; font-size: 10pt; color: #e5e7eb; }}
QMainWindow, #content, QScrollArea, #page {{ background: #0f1115; }}
QLabel, QAbstractButton {{ background: transparent; }}
#sidebar {{ background: #14171e; border-right: 1px solid #1f232b; }}
#appTitle {{ font-size: 13pt; font-weight: 600; }}
#devName {{ font-size: 11pt; font-weight: 600; }}
#pageTitle {{ font-size: 17pt; font-weight: 600; }}
#hint {{ color: #8b93a1; font-size: 9pt; }}
#rowLabel {{ font-size: 10pt; }}
#value {{ color: #cbd5e1; }}
#big {{ font-size: 30pt; font-weight: 600; }}
#warn {{ color: #fbbf24; }}
#card {{ background: #161a22; border: 1px solid #222733; border-radius: 12px; }}
#cardTitle {{ font-size: 11pt; font-weight: 600; }}
#nav {{ background: transparent; border: none; outline: none; }}
#nav::item {{ padding: 9px 12px; border-radius: 8px; margin: 1px 8px; color: #c7cdd8; }}
#nav::item:hover {{ background: #1c212b; }}
#nav::item:selected {{ background: {ACCENT}; color: white; }}
QProgressBar {{ border: none; border-radius: 5px; background: #0b0d11; height: 10px; }}
QProgressBar::chunk {{ border-radius: 5px; background: #22c55e; }}
QComboBox, QSpinBox, QLineEdit {{ background: #0f1219; border: 1px solid #2a2f3a; border-radius: 7px; padding: 4px 8px; }}
QComboBox QAbstractItemView {{ background: #161a22; selection-background-color: {ACCENT}; }}
QSlider::groove:horizontal {{ height: 4px; background: #2a2f3a; border-radius: 2px; }}
QSlider::sub-page:horizontal {{ background: {ACCENT}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: white; width: 16px; margin: -6px 0; border-radius: 8px; }}
QPushButton {{ background: #1f2430; border: 1px solid #2a2f3a; border-radius: 8px; padding: 6px 14px; }}
QPushButton:hover {{ background: #262c3a; }}
QTableWidget {{ background: #11141a; gridline-color: #222733; border: none; border-radius: 8px; }}
QHeaderView::section {{ background: #161a22; color: #8b93a1; border: none; padding: 4px; }}
QScrollBar:vertical {{ background: transparent; width: 10px; }}
QScrollBar::handle:vertical {{ background: #2a2f3a; border-radius: 5px; min-height: 30px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; }}
*:disabled, #hint:disabled, #rowLabel:disabled {{ color: #4f5664; }}
"""

# translated lazily (the language is chosen after import)
def KINDS():  # noqa: N802
    return [(_("Primary click"), KIND_PRIMARY), (_("Secondary click"), KIND_SECONDARY), (_("Middle click"), KIND_MIDDLE)]


def OWNERS():  # noqa: N802
    return [("MagicMouse Studio", OWNER_STUDIO), (_("Apple driver (original)"), OWNER_APPLE)]


def action_name(code: str) -> str:
    names = {"nav-back": _("Back"), "nav-forward": _("Forward"), "desktop-next": _("Next desktop"),
             "desktop-prev": _("Previous desktop"), "task-view": _("Task View"), "desktop-view": _("Desktop"),
             "double-tap drag": _("Double-tap drag")}
    if code in names:
        return names[code]
    if code.startswith("tap ") and " → " in code:          # "tap 2 → right"
        n, btn = code[4:].split(" → ", 1)
        return _("Tap {n} → {button}", n=n, button=_(btn))
    return code


# ---------------------------------------------------------------- helpers
def launch_spec() -> tuple[str, list[str], str]:
    """(executable, leading args, working dir) that start this app: the installed .exe, or pythonw + run.py."""
    if FROZEN:
        return sys.executable, [], os.path.dirname(sys.executable)
    pyw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
    exe = pyw if os.path.exists(pyw) else sys.executable
    run = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "run.py"))
    return exe, [run], os.path.dirname(run)


def app_command() -> str:
    exe, args, _cwd = launch_spec()
    return " ".join(f'"{a}"' for a in [exe, *args, "--minimized"])


STARTUP_LNK = os.path.join(os.environ.get("APPDATA", ""), r"Microsoft\Windows\Start Menu\Programs\Startup",
                           "MagicMouse Studio.lnk")


def set_autostart(on: bool) -> None:
    """Autostart via a shortcut in the user's Startup folder.
    (A HKCU\\...\\Run value was silently skipped by Explorer at logon on this machine — 2026-11-20 —
    while every other Run entry started, so the Run value is no longer used and is removed.)"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
            winreg.DeleteValue(k, "MagicMouseStudio")
    except OSError:
        pass
    if not on:
        if os.path.exists(STARTUP_LNK):
            os.remove(STARTUP_LNK)
        return
    exe, args, app_dir = launch_spec()
    arg_line = " ".join([f'"{a}"' for a in args] + ["--minimized"])

    def q(s):
        return s.replace("'", "''")

    ps = (f"$s=(New-Object -ComObject WScript.Shell).CreateShortcut('{q(STARTUP_LNK)}');"
          f"$s.TargetPath='{q(exe)}';$s.Arguments='{q(arg_line)}';"
          f"$s.WorkingDirectory='{q(app_dir)}';$s.Description='MagicMouse Studio';$s.Save()")
    r = subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-Command", ps],
                       capture_output=True, text=True, timeout=30, creationflags=0x08000000)
    if r.returncode != 0 or not os.path.exists(STARTUP_LNK):
        raise OSError(r.stderr.strip() or "shortcut not created")


def battery_color(pct: int, s: Settings) -> str:
    return "#22c55e" if pct > max(20, s.battery_warning) else ("#f59e0b" if pct > s.battery_critical else "#ef4444")


def tray_icon(percent: int | None, charging: bool, s: Settings | None = None) -> QIcon:
    pm = QPixmap(64, 64)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    body = QPainterPath()
    body.addRoundedRect(QRectF(14, 2, 36, 60), 17, 17)
    p.fillPath(body, QColor("#e5e7eb"))
    if percent is not None:
        h = 56 * max(0, min(100, percent)) / 100
        fill = QPainterPath()
        fill.addRect(QRectF(14, 62 - h, 36, h))
        p.fillPath(body.intersected(fill), QColor(battery_color(percent, s or Settings())))
        p.setPen(QColor("#111827"))
        p.setFont(QFont("Segoe UI", 15, QFont.Bold))
        p.drawText(QRectF(0, 16, 64, 32), Qt.AlignCenter, "⚡" if charging else str(percent))
    p.end()
    return QIcon(pm)


class _Bridge(QObject):
    action = Signal(str)


# ---------------------------------------------------------------- window
class MainWindow(QMainWindow):
    def __init__(self, settings: Settings, start_services: bool = True):
        super().__init__()
        self.s = settings
        self.setWindowTitle(APP_NAME)
        self.resize(1180, 760)
        self.battery: BatteryInfo | None = None
        self.link: LinkState | None = None
        self.alerted: set[str] = set()
        self._quitting = False
        self._last_frame = None

        self._save_timer = QTimer(self, singleShot=True, interval=400)
        self._save_timer.timeout.connect(self.s.save)
        self.binder = Binder(self.s, self._changed)

        # engine + hook + data service
        self.bridge = _Bridge()
        self.bridge.action.connect(self._on_action)
        self.hook = MouseHook()
        self.input = InputEngine(self.s, on_action=self.bridge.action.emit, hook=self.hook)
        self.svc = MouseService(self, input_engine=self.input)
        self.svc.frameReady.connect(self.on_frame)
        self.svc.batteryChanged.connect(self.on_battery)
        self.svc.linkChanged.connect(self.on_link)

        root = QWidget()
        h = QHBoxLayout(root)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        h.addWidget(self._build_sidebar())
        self.stack = QStackedWidget()
        self.stack.setObjectName("content")
        h.addWidget(self.stack, 1)
        self.setCentralWidget(root)

        self.pages = [
            (_("Overview"), "◉", self._page_overview()),
            (_("Scrolling"), "↕", self._page_scroll()),
            (_("Clicks"), "◎", self._page_clicks()),
            (_("Tap to click"), "◌", self._page_tap()),
            (_("Gestures"), "⇆", self._page_gestures()),
            (_("Zones"), "▦", self._page_zones()),
            (_("Battery"), "▮", self._page_battery()),
            (_("Application"), "◆", self._page_app()),
            (_("Advanced"), "≡", self._page_advanced()),
        ]
        for name, icon, page in self.pages:
            self.nav.addItem(QListWidgetItem(f"{icon}   {name}"))
            self.stack.addWidget(page)
        self.nav.currentRowChanged.connect(self._on_nav)
        self.nav.setCurrentRow(0)

        self._build_tray()
        self._table_timer = QTimer(self, interval=100)
        self._table_timer.timeout.connect(self._refresh_live)
        self._table_timer.start()
        if start_services:
            if not self.hook.start():
                self._on_action(_("hook not started (error {error})", error=self.hook.error))
            self.input._push_config()
            self.svc.start()
            self._diag_timer = QTimer(self, interval=10000)
            self._diag_timer.timeout.connect(self._write_diag)
            self._diag_timer.start()

    # ------------------------------------------------------------ chrome
    def _build_sidebar(self) -> QWidget:
        sb = QFrame()
        sb.setObjectName("sidebar")
        sb.setFixedWidth(250)
        v = QVBoxLayout(sb)
        v.setContentsMargins(0, 18, 0, 14)
        v.setSpacing(6)
        t = QLabel(f"  {APP_NAME}")
        t.setObjectName("appTitle")
        v.addWidget(t)
        v.addSpacing(8)

        dev = QFrame()
        dev.setObjectName("card")
        dl = QHBoxLayout(dev)
        dl.setContentsMargins(12, 10, 12, 10)
        self.side_icon = QLabel()
        self.side_icon.setPixmap(tray_icon(None, False).pixmap(40, 40))
        dl.addWidget(self.side_icon)
        txt = QVBoxLayout()
        self.side_name = QLabel(self.s.device_name)
        self.side_name.setObjectName("devName")
        self.side_state = QLabel(_("searching…"))
        self.side_state.setObjectName("hint")
        self.side_bar = QProgressBar()
        self.side_bar.setRange(0, 100)
        self.side_bar.setTextVisible(False)
        self.side_bar.setFixedHeight(6)
        txt.addWidget(self.side_name)
        txt.addWidget(self.side_state)
        txt.addWidget(self.side_bar)
        dl.addLayout(txt, 1)
        wrap = QHBoxLayout()
        wrap.setContentsMargins(10, 0, 10, 0)
        wrap.addWidget(dev)
        v.addLayout(wrap)
        v.addSpacing(10)

        self.nav = QListWidget()
        self.nav.setObjectName("nav")
        v.addWidget(self.nav, 1)
        self.side_status = QLabel("")
        self.side_status.setObjectName("hint")
        self.side_status.setWordWrap(True)
        self.side_status.setContentsMargins(16, 0, 12, 0)
        v.addWidget(self.side_status)
        ver = QLabel("  " + _("version {v}", v=__version__))
        ver.setObjectName("hint")
        v.addWidget(ver)
        return sb

    def _page(self, title: str, subtitle: str) -> tuple[QWidget, QVBoxLayout]:
        outer = QScrollArea()
        outer.setWidgetResizable(True)
        outer.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        inner.setObjectName("page")
        v = QVBoxLayout(inner)
        v.setContentsMargins(28, 22, 28, 22)
        v.setSpacing(14)
        tl = QLabel(title)
        tl.setObjectName("pageTitle")
        v.addWidget(tl)
        if subtitle:
            st = QLabel(subtitle)
            st.setObjectName("hint")
            st.setWordWrap(True)
            v.addWidget(st)
        outer.setWidget(inner)
        return outer, v

    def _on_nav(self, i):
        self.stack.setCurrentIndex(i)
        self.zone_view.force_zones = True

    def _changed(self, attr: str):
        if attr == "autostart":
            try:
                set_autostart(self.s.autostart)
            except OSError as e:
                QMessageBox.warning(self, APP_NAME, f"Autostart: {e}")
        if attr == "device_name":
            self.side_name.setText(self.s.device_name)
        if attr == "language" and self.s.language != i18n.current():
            self.s.save()
            QTimer.singleShot(150, self.restart)
            return
        for v in (self.view, self.zone_view):
            v.update()
        self.input._push_config()
        self._save_timer.start()

    def _write_diag(self):
        """Small rolling diagnostics file (hook counters + link state) for troubleshooting."""
        try:
            hs = self.hook.stats()
            st = self.link
            line = (f"{time.strftime('%H:%M:%S')} hook_alive={int(hs.alive)} wheel={hs.wheel_swallowed}/{hs.wheel_seen} "
                    f"click_apple={hs.click_apple} click_other={hs.click_other} "
                    f"frames={st.frames if st else 0} fps={st.fps if st else 0:.0f} "
                    f"speed={self.s.scroll_speed} accel={int(self.s.scroll_accelerated)} smooth={int(self.s.scroll_smooth)} "
                    f"input_ok={int(st.input_ok) if st else 1} blocked={st.input_blocked_s if st else 0:.0f}s "
                    f"reader_restarts={st.reader_restarts if st else 0}\n")
            p = DATA_DIR / "diag.log"
            old = p.read_text(encoding="utf-8").splitlines(True)[-200:] if p.exists() else []
            p.write_text("".join(old) + line, encoding="utf-8")
        except OSError:
            pass

    # ------------------------------------------------------------ pages
    def _page_overview(self):
        page, v = self._page(_("Overview"), _("Live view of the mouse sensor, battery and connection status."))
        row = QHBoxLayout()
        row.setSpacing(16)
        live = Card(_("Touch sensor"), _("Each finger is an ellipse (contact size and angle); the number is the finger ID."))
        self.view = MouseView(self.s)
        # fixed size: the drawing must not grow when the right column gets taller (new lines in "Recent actions")
        self.view.setFixedHeight(400)
        live.add(self.view)
        row.addWidget(live, 3, Qt.AlignTop)

        col = QVBoxLayout()
        bat = Card(_("Battery"))
        self.lbl_pct = QLabel("—")
        self.lbl_pct.setObjectName("big")
        self.bar = QProgressBar()
        self.bar.setRange(0, 100)
        self.bar.setTextVisible(False)
        self.lbl_bsrc = QLabel(_("waiting for the mouse report (sent when it connects)"))
        self.lbl_bsrc.setObjectName("hint")
        self.lbl_bsrc.setWordWrap(True)
        for w in (self.lbl_pct, self.bar, self.lbl_bsrc):
            bat.add(w)
        col.addWidget(bat)

        con = Card(_("Connection"))
        g = QGridLayout()
        self.lbl_bt, self.lbl_drv, self.lbl_rate, self.lbl_eng = QLabel("—"), QLabel("—"), QLabel("—"), QLabel("—")
        for i, (k, w) in enumerate(((_("Bluetooth"), self.lbl_bt), (_("Driver"), self.lbl_drv),
                                    (_("Frames"), self.lbl_rate), (_("Engine"), self.lbl_eng))):
            kl = QLabel(k)
            kl.setObjectName("hint")
            g.addWidget(kl, i, 0)
            g.addWidget(w, i, 1)
        gw = QWidget()
        gw.setLayout(g)
        con.add(gw)
        col.addWidget(con)

        fin = Card(_("Fingers (raw sensor)"))
        self.table = QTableWidget(0, 7)
        self.table.setHorizontalHeaderLabels(["ID", "X", "Y", "Major", "Minor", _("Angle"), _("State")])
        self.table.verticalHeader().setVisible(False)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.table.setFixedHeight(140)
        fin.add(self.table)
        col.addWidget(fin)

        act = Card(_("Recent actions"))
        self.lbl_actions = QLabel("—")
        self.lbl_actions.setObjectName("hint")
        self.lbl_actions.setAlignment(Qt.AlignLeft | Qt.AlignTop)
        self.lbl_actions.setFixedHeight(self.lbl_actions.fontMetrics().lineSpacing() * 6 + 6)   # room for all 6 lines
        act.add(self.lbl_actions)
        col.addWidget(act)
        col.addStretch(1)
        row.addLayout(col, 2)
        v.addLayout(row)
        self.lbl_note = QLabel("")
        self.lbl_note.setObjectName("warn")
        self.lbl_note.setWordWrap(True)
        v.addWidget(self.lbl_note)
        v.addStretch(1)
        self._actions: list[str] = []
        return page

    def _page_scroll(self):
        b = self.binder
        page, v = self._page(_("Scrolling"), _("Scrolling is computed from finger movement on the mouse surface."))
        c = Card(_("Scrolling"))
        c.add(b.combo(_("Scrolling handled by"), "scroll_owner", OWNERS(),
                      _("“Apple driver” = the original Boot Camp scrolling (the other settings here are then not applied).")))
        on = c.add(b.toggle(_("Scrolling"), "scrolling", _("Scroll by sliding a finger.")))
        rows = [
            b.combo(_("Fingers for scrolling"), "scroll_fingers",
                    [(_("One finger"), SCROLL_ONE), (_("One or two fingers"), SCROLL_ONE_OR_TWO), (_("Two fingers only"), SCROLL_TWO)], indent=12),
            b.slider(_("Scroll speed"), "scroll_speed", 1, 100, indent=12),
            b.toggle(_("Accelerated scrolling"), "scroll_accelerated", _("Faster finger movement scrolls proportionally more."), indent=12),
        ]
        for r in rows:
            c.add(r)
            depends(r, on)
        v.addWidget(c)

        d = Card(_("Direction and axes"))
        rows = [
            b.toggle(_("Vertical like a wheel"), "scroll_inverse_v",
                     _("Finger toward the palm = page moves down. Off = natural direction (macOS).")),
            b.toggle(_("Horizontal like a wheel"), "scroll_inverse_h", _("Off = natural direction (macOS).")),
            b.toggle(_("One axis only (orthogonal)"), "scroll_orthogonal_only", _("Lock scrolling to vertical or horizontal.")),
            b.toggle(_("No horizontal scrolling"), "scroll_no_horizontal", _("A fast horizontal stroke is kept for the back/forward gesture.")),
        ]
        for r in rows:
            d.add(r)
            depends(r, on)
        v.addWidget(d)

        e = Card(_("Smoothness"))
        sm = e.add(b.toggle(_("Smooth scrolling"), "scroll_smooth", _("Fine steps instead of wheel “notches” (modern apps).")))
        mo = e.add(b.toggle(_("Momentum after lifting the finger"), "scroll_momentum", indent=12))
        depends(sm, on)
        depends(mo, on, sm)
        st = e.add(b.toggle(_("Stop scrolling when the mouse moves"), "scroll_stop_on_mouse_move"))
        depends(st, on)
        v.addWidget(e)
        v.addStretch(1)
        return page

    def _page_clicks(self):
        b = self.binder
        page, v = self._page(_("Clicks"), _("A physical click is assigned by finger position at the moment of the click."))
        c = Card(_("Buttons"))
        c.add(b.combo(_("Clicks handled by"), "click_owner", OWNERS(),
                      _("“MagicMouse Studio” replaces the Apple mouse’s left/right click; other mice are not affected.")))
        c.add(b.toggle(_("Swap left and right buttons"), "swap_buttons"))
        c.add(b.toggle(_("Left-handed mode"), "left_handed", _("Mirrors the zones and swaps primary/secondary button.")))
        c.add(b.slider(_("Left/right button boundary"), "button_split", 20, 80, _("Share of the width (from the left) that belongs to the primary button."), "%"))
        c.add(b.toggle(_("Simultaneous primary + secondary click"), "simultaneous_clicks",
                       _("Fingers on both sides of the boundary when clicking = both buttons.")))
        v.addWidget(c)

        m = Card(_("Middle (3rd) button"))
        on = m.add(b.toggle(_("Middle click"), "middle_click"))
        k = m.add(b.combo(_("Method"), "middle_click_kind",
                          [(_("One finger in the middle"), MIDDLE_ONE_FINGER_CENTER), (_("Any two fingers"), MIDDLE_ANY_TWO),
                           (_("Two fingers apart"), MIDDLE_WIDE_TWO), (_("Three fingers"), MIDDLE_THREE)], indent=12))
        depends(k, on)
        v.addWidget(m)

        p = Card(_("Pointer"))
        r = p.add(b.slider(_("Base pointer speed"), "pointer_speed", 1, 10,
                           _("Requires driver support (next phase) — the Windows setting would change the other mouse too.")))
        r.setEnabled(False)
        v.addWidget(p)
        v.addStretch(1)
        return page

    def _page_tap(self):
        b = self.binder
        page, v = self._page(_("Tap to click"), _("A light touch without pressing the button."))
        c = Card(_("One-finger tap"))
        on = c.add(b.toggle(_("Tap to click (1 finger)"), "tap1"))
        rows = []
        for label, attr, kattr in ((_("Tap in the left zone"), "tap1_left", "tap1_left_kind"),
                                   (_("Tap in the middle zone"), "tap1_middle", "tap1_middle_kind"),
                                   (_("Tap in the right zone"), "tap1_right", "tap1_right_kind")):
            t = b.toggle(label, attr, indent=12)
            kk = b.combo(_("action"), kattr, KINDS(), indent=24, width=180)
            c.add(t)
            c.add(kk)
            depends(t, on)
            depends(kk, on, t)
        for r in (b.toggle(_("Only in the tap area"), "tap1_use_tap_area", _("Front part of the mouse (see Zones)."), indent=12),
                  b.toggle(_("Ignore taps in ignored zones"), "tap1_filter_ignore_areas", indent=12),
                  b.toggle(_("Ignore physical click"), "tap1_ignore_real_click", _("Click only by tapping (silent operation)."), indent=12),
                  b.toggle(_("Double-tap and drag"), "double_tap_drag", _("Tap, then immediately touch and hold = left button held."), indent=12)):
            c.add(r)
            depends(r, on)
        v.addWidget(c)

        for n, title, label in ((2, _("Two-finger tap"), _("Tap to click (2 fingers)")),
                                (3, _("Three-finger tap"), _("Tap to click (3 fingers)"))):
            cc = Card(title)
            o = cc.add(b.toggle(label, f"tap{n}"))
            for r in (b.combo(_("Action"), f"tap{n}_kind", KINDS(), indent=12),
                      b.toggle(_("Only in the tap area"), f"tap{n}_use_tap_area", indent=12),
                      b.toggle(_("Ignore taps in ignored zones"), f"tap{n}_filter_ignore_areas", indent=12)):
                cc.add(r)
                depends(r, o)
            v.addWidget(cc)
        v.addStretch(1)
        return page

    def _page_gestures(self):
        b = self.binder
        page, v = self._page(_("Gestures"), _("Quick finger strokes on the mouse surface."))
        c = Card(_("Navigation (one finger, quick stroke left/right)"), _("Back / forward in the browser, Explorer, …"))
        c.add(b.toggle(_("Stroke left"), "swipe_navigate_left"))
        c.add(b.toggle(_("Stroke right"), "swipe_navigate_right"))
        c.add(b.toggle(_("Reverse navigation direction"), "swap_navigate", _("On: stroke left = back.")))
        v.addWidget(c)
        d = Card(_("Two fingers"), _("Virtual desktops and window overview."))
        d.add(b.toggle(_("Left: desktop"), "swipe2_left"))
        d.add(b.toggle(_("Right: desktop"), "swipe2_right"))
        d.add(b.toggle(_("Reverse desktop direction"), "swap_desktop_direction"))
        d.add(b.toggle(_("Up: Task View"), "swipe2_up"))
        d.add(b.toggle(_("Down: show desktop"), "swipe2_down"))
        v.addWidget(d)
        v.addStretch(1)
        return page

    def _page_zones(self):
        b = self.binder
        page, v = self._page(_("Zones"), _("Green = tap area, purple = middle button, red = ignored, "
                                           "dashed line = left/right button boundary."))
        row = QHBoxLayout()
        card = Card(_("Surface"))
        self.zone_view = MouseView(self.s)
        self.zone_view.force_zones = True
        self.zone_view.setMinimumHeight(460)
        card.add(self.zone_view, 1)
        row.addWidget(card, 2)
        c = Card(_("Dimensions (sensor units)"), _("Width ≈ 2360, length ≈ 3640 units."))
        for r in (b.spin(_("Ignore left edge"), "ignore_side_left", 0, 800, step=10),
                  b.spin(_("Ignore right edge"), "ignore_side_right", 0, 800, step=10),
                  b.spin(_("Ignore back part"), "ignore_bottom", 0, 2500, step=50),
                  b.spin(_("Tap area (from the front edge)"), "tap_area_from_top", 200, 3640, step=50),
                  b.spin(_("Middle button from"), "middle1_start", 0, 2360, step=10),
                  b.spin(_("Middle button to"), "middle1_end", 0, 2360, step=10),
                  b.spin(_("Min. distance of 2 fingers (middle click)"), "middle2_min_distance", 200, 2360, step=20),
                  b.slider(_("Left/right boundary"), "button_split", 20, 80, suffix="%"),
                  b.toggle(_("Show zones on Overview too"), "show_zones")):
            c.add(r)
        row.addWidget(c, 2)
        v.addLayout(row)
        v.addStretch(1)
        return page

    def _page_battery(self):
        b = self.binder
        page, v = self._page(_("Battery"), _("The mouse reports its battery when it connects; on the cable it is read directly."))
        top = Card(_("Status"))
        self.bat_big = QLabel("—")
        self.bat_big.setObjectName("big")
        self.bat_bar = QProgressBar()
        self.bat_bar.setRange(0, 100)
        self.bat_bar.setTextVisible(False)
        self.bat_src = QLabel("")
        self.bat_src.setObjectName("hint")
        for w in (self.bat_big, self.bat_bar, self.bat_src):
            top.add(w)
        v.addWidget(top)
        c = Card(_("Alerts"))
        on = c.add(b.toggle(_("Battery alerts"), "battery_alerts"))
        for r in (b.spin(_("Low battery below"), "battery_warning", 1, 60, suffix=" %", indent=12),
                  b.spin(_("Critical battery below"), "battery_critical", 1, 30, suffix=" %", indent=12),
                  b.spin(_("Notify when charged to"), "battery_show_charged", 10, 100, suffix=" %", indent=12,
                         hint=_("Notification while the mouse is on the cable.")),
                  b.toggle(_("Notify when fully charged"), "battery_show_fully_charged", indent=12)):
            c.add(r)
            depends(r, on)
        sn = QWidget()
        sh = QHBoxLayout(sn)
        sh.setContentsMargins(12, 6, 0, 6)
        lab = QLabel(_("Snooze alerts:"))
        sh.addWidget(lab)
        for text, secs in ((_("1 h"), 3600), (_("2 h"), 7200), (_("until tomorrow"), -1), (_("cancel"), 0)):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, s=secs: self._snooze(s))
            sh.addWidget(btn)
        sh.addStretch(1)
        self.lbl_snooze = QLabel("")
        self.lbl_snooze.setObjectName("hint")
        c.add(sn)
        c.add(self.lbl_snooze)
        v.addWidget(c)
        v.addStretch(1)
        self._update_snooze_label()
        return page

    def _page_app(self):
        b = self.binder
        page, v = self._page(_("Application"), "")
        lc = Card(_("Language"), _("The application restarts in the selected language."))
        lc.add(b.combo(_("Application language"), "language", [(name, code) for code, name, _rtl in i18n.LANGUAGES]))
        v.addWidget(lc)
        d = Card(_("Device"))
        name = QLineEdit(self.s.device_name)
        name.setFixedWidth(220)
        name.editingFinished.connect(lambda: (setattr(self.s, "device_name", name.text().strip() or "Magic Mouse 2"),
                                              self._changed("device_name")))
        d.add(b._row(_("Mouse name"), "", name))
        d.add(b.combo(_("Color"), "color", [("Silver", "silver"), ("Space Gray", "spacegray"), ("Black", "black")]))
        v.addWidget(d)
        p = Card(_("Display"))
        p.add(b.toggle(_("Live touch display"), "live_touches"))
        p.add(b.toggle(_("Finger trails"), "show_trails"))
        p.add(b.combo(_("View rotation"), "rotate", [("0°", 0), ("90°", 90), ("180°", 180), ("270°", 270)]))
        p.add(b.toggle(_("Mirror left/right"), "mirror_x"))
        p.add(b.toggle(_("Mirror front/back"), "mirror_y"))
        v.addWidget(p)
        a = Card(_("Startup"))
        a.add(b.toggle(_("Start with Windows"), "autostart"))
        a.add(b.toggle(_("Start minimized (tray)"), "start_minimized"))
        v.addWidget(a)
        dr = Card(_("Driver"), _("mmsfilter.sys sits below the Apple driver and only forwards raw sensor data."))
        self.lbl_drv2 = QLabel("—")
        dr.add(self.lbl_drv2)
        btn = QPushButton(_("Open the driver folder (install/uninstall scripts)"))
        btn.clicked.connect(lambda: subprocess.Popen(["explorer", DRIVER_DIR]))
        dr.add(btn)
        v.addWidget(dr)
        v.addStretch(1)
        return page

    def _page_advanced(self):
        b = self.binder
        page, v = self._page(_("Advanced"), _("Engine thresholds (same quantities as in Magic Utilities). Units: sensor / ms."))
        c = Card(_("Gestures"))
        for r in (b.spin(_("1-finger stroke — horizontal"), "swipe_h_offset", 10, 300),
                  b.spin(_("1-finger stroke — vertical"), "swipe_v_offset", 10, 300),
                  b.spin(_("2-finger stroke — horizontal"), "swipe2_h_offset", 10, 300),
                  b.spin(_("2-finger stroke — vertical"), "swipe2_v_offset", 10, 300),
                  b.spin(_("Block after navigation"), "swipe_navi_block", 0, 2000, suffix=" ms", step=50),
                  b.spin(_("Block after other gestures"), "swipe_other_block", 0, 2000, suffix=" ms", step=50)):
            c.add(r)
        v.addWidget(c)
        d = Card(_("Scroll"))
        for r in (b.spin(_("Dead zone — vertical"), "scroll_v_offset", 0, 1000, step=5),
                  b.spin(_("Dead zone — horizontal"), "scroll_h_offset", 0, 1000, step=5),
                  b.spin(_("Wheel step"), "scroll_step_factor", 10, 480, step=10),
                  b.spin(_("“Mouse moved” threshold"), "stop_scroll_move_offset", 1, 50)):
            d.add(r)
        v.addWidget(d)
        e = Card(_("Tap"))
        for r in (b.spin(_("Max. tap duration"), "tap_delay", 50, 600, suffix=" ms", step=10),
                  b.spin(_("Allowed movement"), "tap_offset_allowed", 0, 400, step=5),
                  b.spin(_("Minimum touch size"), "tap_sense", 0, 40),
                  b.spin(_("Double tap — min. pause"), "double_tap_drag_min", 0, 1000, suffix=" ms", step=10),
                  b.spin(_("Double tap — max. pause"), "double_tap_drag_max", 0, 1000, suffix=" ms", step=10)):
            e.add(r)
        v.addWidget(e)
        reset = QPushButton(_("Reset everything to defaults"))
        reset.clicked.connect(self._reset_defaults)
        v.addWidget(reset, 0, Qt.AlignLeft)
        v.addStretch(1)
        return page

    def _reset_defaults(self):
        if QMessageBox.question(self, APP_NAME, _("Reset all settings to their default values?")) != QMessageBox.Yes:
            return
        d = Settings()
        keep = {"autostart", "device_name", "battery_snooze_until"}
        for f in fields(Settings):
            if f.name not in keep:
                setattr(self.s, f.name, getattr(d, f.name))
        self.binder.refresh()
        self._changed("reset")

    # ------------------------------------------------------------ tray
    def _build_tray(self):
        self.tray = QSystemTrayIcon(tray_icon(None, False), self)
        self.tray.setToolTip(APP_NAME)
        menu = QMenu()
        a_show = QAction(_("Show"), self)
        a_show.triggered.connect(self.show_normal)
        menu.addAction(a_show)
        sn = menu.addMenu(_("Snooze battery alerts"))
        for text, secs in ((_("1 hour"), 3600), (_("2 hours"), 7200), (_("until tomorrow"), -1), (_("cancel"), 0)):
            a = QAction(text, self)
            a.triggered.connect(lambda _=False, s=secs: self._snooze(s))
            sn.addAction(a)
        menu.addSeparator()
        self.a_pause = QAction(_("Pause gestures and scrolling"), self, checkable=True)
        self.a_pause.toggled.connect(lambda on: self.input.set_enabled(not on))
        menu.addAction(self.a_pause)
        menu.addSeparator()
        a_quit = QAction(_("Exit"), self)
        a_quit.triggered.connect(self.quit)
        menu.addAction(a_quit)
        self.tray.setContextMenu(menu)
        self.tray.activated.connect(lambda r: self.show_normal() if r == QSystemTrayIcon.Trigger else None)
        self.tray.show()

    # ------------------------------------------------------------ data
    def on_frame(self, fr):
        self._last_frame = fr
        self.view.push(fr)
        self.zone_view.push(fr)

    def _on_action(self, text: str):
        text = action_name(text)
        self._actions = ([time.strftime("%H:%M:%S") + "  " + text] + self._actions)[:6]
        self.lbl_actions.setText("\n".join(self._actions))

    def _refresh_live(self):
        fr = self._last_frame
        if fr is None or not self.isVisible() or self.stack.currentIndex() != 0:
            return
        rows = [t for t in fr.touches if t.present] if self.view.frame and self.view.frame.touches else []
        self.table.setRowCount(len(rows))
        for i, t in enumerate(rows):
            vals = [t.id, t.x, t.y, t.major, t.minor, f"{t.orientation * 90 / 32:.0f}°",
                    {1: _("approaching"), 2: _("approaching"), 3: _("touch"), 4: _("dragging")}.get(t.state >> 4, _("lifting"))]
            for j, val in enumerate(vals):
                it = QTableWidgetItem(str(val))
                it.setTextAlignment(Qt.AlignCenter)
                self.table.setItem(i, j, it)

    def on_battery(self, bi: BatteryInfo):
        self.battery = bi
        col = battery_color(bi.percent, self.s)
        css = f"QProgressBar::chunk {{ background: {col}; border-radius: 5px; }}"
        if bi.on_cable:
            src = _("via USB cable (charging)")
        else:
            age = int(bi.age_s)
            src = _("via Bluetooth") + (_(", report from {m} min ago", m=age // 60) if age >= 60 else "")
        for lbl, bar, srcl in ((self.lbl_pct, self.bar, self.lbl_bsrc), (self.bat_big, self.bat_bar, self.bat_src)):
            lbl.setText(f"{bi.percent} %")
            bar.setValue(bi.percent)
            bar.setStyleSheet(css)
            srcl.setText(src)
        self.side_bar.setValue(bi.percent)
        self.side_bar.setStyleSheet(css)
        icon = tray_icon(bi.percent, bi.on_cable, self.s)
        self.side_icon.setPixmap(icon.pixmap(40, 40))
        self.tray.setIcon(icon)
        self.tray.setToolTip(f"{APP_NAME}: {self.s.device_name} {bi.percent} %")
        self._battery_alerts(bi)

    def _snooze(self, secs: int):
        if secs == 0:
            self.s.battery_snooze_until = 0.0
        elif secs < 0:
            t = time.localtime()
            self.s.battery_snooze_until = time.mktime((t.tm_year, t.tm_mon, t.tm_mday + 1, 8, 0, 0, 0, 0, -1))
        else:
            self.s.battery_snooze_until = time.time() + secs
        self._update_snooze_label()
        self._changed("battery_snooze_until")

    def _update_snooze_label(self):
        u = self.s.battery_snooze_until
        self.lbl_snooze.setText(_("Alerts snoozed until {time}", time=time.strftime('%d.%m. %H:%M', time.localtime(u)))
                                if u > time.time() else "")

    def _battery_alerts(self, bi: BatteryInfo):
        s = self.s
        if not s.battery_alerts or time.time() < s.battery_snooze_until:
            return
        name = s.device_name
        if bi.on_cable:
            self.alerted -= {"low", "crit"}
            if bi.percent >= 100 and s.battery_show_fully_charged and "full" not in self.alerted:
                self.alerted.add("full")
                self.tray.showMessage(APP_NAME, _("{name} is fully charged.", name=name), QSystemTrayIcon.Information, 6000)
            elif bi.percent >= s.battery_show_charged and "charged" not in self.alerted:
                self.alerted.add("charged")
                self.tray.showMessage(APP_NAME, _("{name}: charged to {pct} %.", name=name, pct=bi.percent), QSystemTrayIcon.Information, 5000)
            return
        self.alerted -= {"full", "charged"}
        if bi.percent <= s.battery_critical and "crit" not in self.alerted:
            self.alerted |= {"crit", "low"}
            self.tray.showMessage(APP_NAME, _("Critical: {name} {pct} % — connect the cable.", name=name, pct=bi.percent), QSystemTrayIcon.Critical, 10000)
        elif bi.percent <= s.battery_warning and "low" not in self.alerted:
            self.alerted.add("low")
            self.tray.showMessage(APP_NAME, _("Low battery: {name} {pct} %.", name=name, pct=bi.percent), QSystemTrayIcon.Warning, 8000)

    def on_link(self, st: LinkState):
        self.link = st
        bt = _("connected") if st.bt_connected else (_("not connected (mouse is on the cable)") if st.usb_present else _("not connected"))
        self.lbl_bt.setText(bt)
        self.lbl_drv.setText(_("mmsfilter running") if st.driver else _("not installed"))
        self.lbl_drv2.setText(_("Status: running") if st.driver else _("Status: not loaded"))
        self.lbl_rate.setText(_("{fps}/s · total {total} · lost {lost}", fps=f"{st.fps:.0f}", total=st.frames, lost=st.dropped))
        paused = self.a_pause.isChecked()
        hs = self.hook.stats()
        self.lbl_eng.setText(_("paused") if paused else
                             (_("active · wheel {swallowed}/{seen} · click {clicks}", swallowed=hs.wheel_swallowed, seen=hs.wheel_seen, clicks=hs.click_apple)
                              if hs.alive else _("hook not active ({error})", error=self.hook.error)))
        self.side_state.setText((_("Bluetooth") + " · " if st.bt_connected else "") +
                                (_("on cable") if st.usb_present else (_("connected") if st.bt_connected else _("not connected"))))
        if not st.input_ok:
            self.side_status.setText(_("⚠ Windows is blocking input injection — restart the computer."))
            self.lbl_note.setText(_("Sending scroll/clicks has been blocked for {s} s: some program on the system has a stuck mouse hook (this can also make the cursor stutter). Sensors and the display keep working; restarting the computer fixes it.", s=f"{st.input_blocked_s:.0f}"))
            if "inputblock" not in self.alerted:
                self.alerted.add("inputblock")
                self.tray.showMessage(APP_NAME, _("Windows is blocking input injection (a program’s mouse hook is stuck). Restart the computer."), QSystemTrayIcon.Warning, 10000)
        elif not st.driver:
            self.side_status.setText(_("⚠ Driver not loaded — sensors and gestures don’t work."))
            self.lbl_note.setText(_("The mmsfilter driver is not loaded: the sensor display and gestures don’t work; battery only on the cable. Fix: run MagicMouse Studio Setup again with the “sensor driver” option checked (needs Windows Test Mode)."))
        else:
            self.side_status.setText("")
            self.lbl_note.setText(_("Touch the mouse surface — the mouse only sends data when something changes.")
                                  if st.bt_connected and st.fps == 0 else "")

    # ------------------------------------------------------------ window / tray
    def show_normal(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def closeEvent(self, ev):
        if self._quitting:
            ev.accept()
            return
        ev.ignore()
        self.hide()
        if "hint" not in self.alerted:
            self.alerted.add("hint")
            self.tray.showMessage(APP_NAME, _("Still running in the background (tray). To exit: right-click the icon."),
                                  QSystemTrayIcon.Information, 4000)

    def nativeEvent(self, event_type, message):  # noqa: N802 (Qt API)
        """A second launch posts WM_SHOW_NAME to this window: bring it to the front."""
        wm = getattr(self, "wm_show", 0)
        if wm and event_type == b"windows_generic_MSG":
            import ctypes.wintypes as wt
            msg = wt.MSG.from_address(int(message))
            if msg.message == wm:
                QTimer.singleShot(0, self.show_normal)
                return True, 0
        return super().nativeEvent(event_type, message)

    def quit(self):
        self._quitting = True
        self.s.save()
        self.svc.stop()
        self.hook.stop()
        self.tray.hide()
        QApplication.quit()

    def restart(self):
        """Start a fresh instance (it waits for this process to exit) and quit — used to switch language."""
        exe, args, cwd = launch_spec()
        subprocess.Popen([exe, *args, "--wait-pid", str(os.getpid())], cwd=cwd,
                         creationflags=0x00000008 | 0x00000200)     # DETACHED_PROCESS | NEW_PROCESS_GROUP
        self.quit()


WM_SHOW_NAME = "MagicMouseStudio.ShowWindow"


def _find_live_instance():
    """A living instance owns a top-level window titled APP_NAME (hidden when in the tray).
    A dead process stuck in the kernel has no windows, so it can never block a new start
    (mutexes, lock files and named pipes all can — they outlive a stuck process)."""
    import ctypes
    import ctypes.wintypes as wt
    u32 = ctypes.WinDLL("user32")
    found = []
    proto = ctypes.WINFUNCTYPE(wt.BOOL, wt.HWND, wt.LPARAM)

    def cb(hwnd, _lp):
        buf = ctypes.create_unicode_buffer(64)
        # InternalGetWindowText never sends a message, so a hung window cannot block the new start
        u32.InternalGetWindowText(hwnd, buf, 64)
        if buf.value == APP_NAME:
            pid = wt.DWORD()
            u32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
            if pid.value != os.getpid():
                found.append(hwnd)
        return True

    u32.EnumWindows(proto(cb), 0)
    return found[0] if found else None


def _selftest(argv) -> int:
    """Packaging check (used after a build/install): loads every part of the app WITHOUT touching
    input, settings or a running instance, and writes OK/FAIL lines.
    usage: MagicMouseStudio.exe --selftest [result-file]   (default %LOCALAPPDATA%/MagicMouseStudio/selftest.txt)"""
    import ctypes
    import pathlib
    import traceback
    i = argv.index("--selftest")
    out = argv[i + 1] if len(argv) > i + 1 else str(DATA_DIR / "selftest.txt")
    lines, ok_all = [], True

    def say(ok, what, detail=""):
        nonlocal ok_all
        ok_all &= bool(ok)
        lines.append(f"[{'OK  ' if ok else 'FAIL'}] {what}" + (f" - {detail}" if detail else ""))

    from .. import __version__, hook as hook_mod, i18n as i18n_mod
    say(True, "version", f"{__version__} frozen={FROZEN} exe={sys.executable}")
    for code, name, _rtl in i18n_mod.LANGUAGES:
        active = i18n_mod.set_language(code)
        txt = i18n_mod._("Scrolling")
        say(active == code and (code == "en" or txt != "Scrolling"), f"language {code}", f"{name}: {txt}")
    i18n_mod.set_language("en")
    try:
        ctypes.WinDLL(hook_mod._DLL_PATH)
        say(True, "mmshook.dll", hook_mod._DLL_PATH)
    except OSError as e:
        say(False, "mmshook.dll", repr(e))
    icon = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "app.png")
    say(os.path.exists(icon), "icon", icon)
    try:
        from ..driverlink import DriverLink
        d = DriverLink()
        st = d.status()
        d.close()
        say(True, "driver", f"v{st.version >> 16}.{(st.version >> 8) & 0xFF} devices={st.devices} battery={st.battery_percent}")
    except OSError as e:
        lines.append(f"[INFO] driver not reachable ({e})")
    try:
        app = QApplication.instance() or QApplication(argv)
        app.setStyleSheet(STYLE)
        Settings.save = lambda self: None            # never write the user's settings from a check
        w = MainWindow(Settings(), start_services=False)
        for n in range(w.stack.count()):
            w.nav.setCurrentRow(n)
            app.processEvents()
        say(not w.grab().isNull(), "main window", f"{w.stack.count()} pages rendered")
        w.hook.stop()
    except Exception:                                # noqa: BLE001
        say(False, "main window", traceback.format_exc().strip().splitlines()[-1])
    lines.append("RESULT: " + ("OK" if ok_all else "FAIL"))
    try:
        pathlib.Path(out).parent.mkdir(parents=True, exist_ok=True)
        pathlib.Path(out).write_text("\n".join(lines) + "\n", encoding="utf-8")
    except OSError:
        pass
    return 0 if ok_all else 1


def main(argv=None):
    import ctypes

    argv = argv if argv is not None else sys.argv
    if "--selftest" in argv:
        return _selftest(argv)
    u32 = ctypes.WinDLL("user32")
    wm_show = u32.RegisterWindowMessageW(WM_SHOW_NAME)
    if "--wait-pid" in argv:                 # language switch: wait until the old instance is gone
        try:
            old = int(argv[argv.index("--wait-pid") + 1])
            k32 = ctypes.WinDLL("kernel32")
            h = k32.OpenProcess(0x00100000, False, old)          # SYNCHRONIZE
            if h:
                k32.WaitForSingleObject(h, 10000)
                k32.CloseHandle(h)
        except (ValueError, IndexError):
            pass
    if not os.environ.get("MMS_DEBUG_ALLOW_SECOND"):
        hwnd = _find_live_instance()
        if hwnd:
            u32.PostMessageW(hwnd, wm_show, 0, 0)
            return 0
    app = QApplication(argv)
    app.setApplicationName(APP_NAME)
    app.setQuitOnLastWindowClosed(False)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    try:
        (DATA_DIR / "app.lock").unlink(missing_ok=True)   # old lock-file mechanism
    except OSError:
        pass
    app.setStyleSheet(STYLE)
    settings = Settings.load()
    settings.language = i18n.set_language(settings.language)
    if i18n.is_rtl():
        app.setLayoutDirection(Qt.RightToLeft)
    try:
        with open(DATA_DIR / "diag.log", "a", encoding="utf-8") as fh:
            fh.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} START pid={os.getpid()} args={argv[1:]} "
                     f"autostart={settings.autostart}\n")
    except OSError:
        pass
    if settings.autostart:
        legacy_run = False
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
                winreg.QueryValueEx(k, "MagicMouseStudio")
                legacy_run = True
        except OSError:
            pass
        if legacy_run or not os.path.exists(STARTUP_LNK):
            try:
                set_autostart(True)          # (re)create the Startup shortcut, drop the old Run value
            except (OSError, subprocess.SubprocessError):
                pass
    w = MainWindow(settings)
    icon_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets", "app.png")
    app_icon = QIcon(icon_file) if os.path.exists(icon_file) else tray_icon(None, False)
    app.setWindowIcon(app_icon)
    w.setWindowIcon(app_icon)
    w.wm_show = wm_show
    w.winId()                        # create the native window now, even when starting in the tray
    if not ("--minimized" in argv or settings.start_minimized):
        w.show()
    return app.exec()
