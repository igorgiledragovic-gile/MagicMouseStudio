"""Small UI building blocks: switch, setting cards and rows bound to Settings attributes."""
from __future__ import annotations

from PySide6.QtCore import Property, QEasingCurve, QPropertyAnimation, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (QAbstractButton, QComboBox, QFrame, QHBoxLayout, QLabel, QSlider, QSpinBox,
                               QVBoxLayout, QWidget)

ACCENT = "#3b82f6"


class _WheelOnlyWhenFocused:
    """Scrolling a settings page must never change a value the pointer happens to pass over
    (a combo silently switched "View rotation" to 270° on 2026-11-20). The wheel only changes the
    control after it was clicked; otherwise the event goes on to the page, which scrolls."""

    def _init_wheel(self):
        self.setFocusPolicy(Qt.StrongFocus)

    def wheelEvent(self, e):          # noqa: N802
        if self.hasFocus():
            super().wheelEvent(e)
        else:
            e.ignore()


class NoWheelComboBox(_WheelOnlyWhenFocused, QComboBox):
    def __init__(self, *a):
        super().__init__(*a)
        self._init_wheel()


class NoWheelSlider(_WheelOnlyWhenFocused, QSlider):
    def __init__(self, *a):
        super().__init__(*a)
        self._init_wheel()


class NoWheelSpinBox(_WheelOnlyWhenFocused, QSpinBox):
    def __init__(self, *a):
        super().__init__(*a)
        self._init_wheel()


class Switch(QAbstractButton):
    """iOS-style toggle."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self._pos = 0.0
        # NOTE: must not be called "pos" — that is QWidget's own position property
        self._anim = QPropertyAnimation(self, b"knob", self)
        self._anim.setDuration(140)
        self._anim.setEasingCurve(QEasingCurve.OutCubic)
        self.toggled.connect(self._animate)

    def sizeHint(self):
        return QSize(44, 24)

    def _animate(self, on):
        self._anim.stop()
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def setChecked(self, on):  # noqa: N802 (Qt API) — programmatic set: jump, no animation
        super().setChecked(on)
        self._anim.stop()
        self._pos = 1.0 if on else 0.0
        self.update()

    def _get(self):
        return self._pos

    def _set(self, v):
        self._pos = v
        self.update()

    knob = Property(float, _get, _set)

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        r = QRectF(1, 1, self.width() - 2, self.height() - 2)
        off, on = QColor("#3a3f4b"), QColor(ACCENT)
        if not self.isEnabled():
            off, on = QColor("#262a33"), QColor("#2b3a55")
        c = QColor(int(off.red() + (on.red() - off.red()) * self._pos),
                   int(off.green() + (on.green() - off.green()) * self._pos),
                   int(off.blue() + (on.blue() - off.blue()) * self._pos))
        p.setPen(Qt.NoPen)
        p.setBrush(c)
        p.drawRoundedRect(r, r.height() / 2, r.height() / 2)
        d = r.height() - 4
        x = r.left() + 2 + (r.width() - d - 4) * self._pos
        p.setBrush(QColor("#ffffff") if self.isEnabled() else QColor("#8a8f99"))
        p.drawEllipse(QRectF(x, r.top() + 2, d, d))
        p.end()


class Card(QFrame):
    def __init__(self, title: str, subtitle: str = "", parent=None):
        super().__init__(parent)
        self.setObjectName("card")
        self.lay = QVBoxLayout(self)
        self.lay.setContentsMargins(18, 14, 18, 14)
        self.lay.setSpacing(4)
        t = QLabel(title)
        t.setObjectName("cardTitle")
        self.lay.addWidget(t)
        if subtitle:
            st = QLabel(subtitle)
            st.setObjectName("hint")
            st.setWordWrap(True)
            self.lay.addWidget(st)
        self.lay.addSpacing(6)

    def add(self, w: QWidget, stretch: int = 0):
        self.lay.addWidget(w, stretch)
        return w


class Binder:
    """Creates rows bound to attributes of a Settings object; calls on_change after every edit."""

    def __init__(self, settings, on_change):
        self.s = settings
        self.on_change = on_change
        self.refreshers = []          # callables that reload widgets from settings

    def _row(self, label: str, hint: str, control: QWidget, indent: int = 0) -> QWidget:
        w = QWidget()
        h = QHBoxLayout(w)
        h.setContentsMargins(indent, 6, 0, 6)
        txt = QVBoxLayout()
        txt.setSpacing(1)
        lb = QLabel(label)
        lb.setObjectName("rowLabel")
        txt.addWidget(lb)
        if hint:
            hl = QLabel(hint)
            hl.setObjectName("hint")
            hl.setWordWrap(True)
            txt.addWidget(hl)
        h.addLayout(txt, 1)
        h.addWidget(control, 0, Qt.AlignRight | Qt.AlignVCenter)
        w.control = control
        return w

    def _set(self, attr, value):
        setattr(self.s, attr, value)
        self.on_change(attr)

    def toggle(self, label, attr, hint="", indent=0, invert=False):
        sw = Switch()
        sw.setChecked(bool(getattr(self.s, attr)) ^ invert)
        sw.toggled.connect(lambda v: self._set(attr, bool(v) ^ invert))
        self.refreshers.append(lambda: (sw.blockSignals(True), sw.setChecked(bool(getattr(self.s, attr)) ^ invert),
                                        sw.blockSignals(False)))
        return self._row(label, hint, sw, indent)

    def combo(self, label, attr, options: list[tuple[str, object]], hint="", indent=0, width=220):
        cb = NoWheelComboBox()
        cb.setFixedWidth(width)
        for text, val in options:
            cb.addItem(text, val)

        def load():
            cb.blockSignals(True)
            i = cb.findData(getattr(self.s, attr))
            cb.setCurrentIndex(max(i, 0))
            cb.blockSignals(False)

        load()
        cb.currentIndexChanged.connect(lambda _i: self._set(attr, cb.currentData()))
        self.refreshers.append(load)
        return self._row(label, hint, cb, indent)

    def slider(self, label, attr, lo, hi, hint="", suffix="", indent=0):
        box = QWidget()
        h = QHBoxLayout(box)
        h.setContentsMargins(0, 0, 0, 0)
        sl = NoWheelSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setFixedWidth(180)
        val = QLabel()
        val.setFixedWidth(46)
        val.setObjectName("value")

        def load():
            sl.blockSignals(True)
            sl.setValue(int(getattr(self.s, attr)))
            sl.blockSignals(False)
            val.setText(f"{sl.value()}{suffix}")

        load()
        sl.valueChanged.connect(lambda v: (val.setText(f"{v}{suffix}"), self._set(attr, int(v))))
        h.addWidget(sl)
        h.addWidget(val)
        self.refreshers.append(load)
        return self._row(label, hint, box, indent)

    def spin(self, label, attr, lo, hi, hint="", suffix="", indent=0, step=1):
        sp = NoWheelSpinBox()
        sp.setRange(lo, hi)
        sp.setSingleStep(step)
        sp.setSuffix(suffix)
        sp.setFixedWidth(120)

        def load():
            sp.blockSignals(True)
            sp.setValue(int(getattr(self.s, attr)))
            sp.blockSignals(False)

        load()
        sp.valueChanged.connect(lambda v: self._set(attr, int(v)))
        self.refreshers.append(load)
        return self._row(label, hint, sp, indent)

    def refresh(self):
        for f in self.refreshers:
            f()


def depends(row: QWidget, *masters: QWidget):
    """Enable `row` only while all master switches are on."""
    sws = [m.control for m in masters]

    def upd(*_):
        row.setEnabled(all(s.isChecked() for s in sws))

    for s in sws:
        s.toggled.connect(upd)
    upd()
