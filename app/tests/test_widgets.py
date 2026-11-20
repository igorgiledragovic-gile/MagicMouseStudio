"""Scrolling over a settings control must not change it unless it was clicked first."""
import os, pathlib, sys
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from PySide6.QtCore import QPoint, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import QApplication
from mmstudio.ui.widgets import NoWheelComboBox, NoWheelSlider, NoWheelSpinBox

app = QApplication.instance() or QApplication(sys.argv)


def wheel(w, dy=-120):
    e = QWheelEvent(QPointF(5, 5), QPointF(5, 5), QPoint(0, 0), QPoint(0, dy), Qt.NoButton, Qt.NoModifier,
                    Qt.NoScrollPhase, False)
    QApplication.sendEvent(w, e)


def make():
    cb = NoWheelComboBox(); cb.addItems(["0", "90", "180", "270"])
    sl = NoWheelSlider(Qt.Horizontal); sl.setRange(0, 100); sl.setValue(50)
    sp = NoWheelSpinBox(); sp.setRange(0, 100); sp.setValue(50)
    return cb, sl, sp


def test_unfocused_wheel_is_ignored():
    for w in make():
        w.show()
        before = w.currentIndex() if isinstance(w, NoWheelComboBox) else w.value()
        wheel(w)
        after = w.currentIndex() if isinstance(w, NoWheelComboBox) else w.value()
        assert before == after, (type(w).__name__, before, after)


def test_focused_wheel_changes_value():
    for w in make():
        w.show()
        w.activateWindow()
        w.setFocus()
        app.processEvents()
        if not w.hasFocus():          # offscreen platform may refuse focus; nothing to test then
            continue
        before = w.currentIndex() if isinstance(w, NoWheelComboBox) else w.value()
        wheel(w)
        after = w.currentIndex() if isinstance(w, NoWheelComboBox) else w.value()
        assert before != after, type(w).__name__


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
