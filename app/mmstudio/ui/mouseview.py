"""Live top-view of the mouse surface with finger ellipses (own drawing, QPainter)."""
from __future__ import annotations

import math
import time
from collections import deque

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QBrush, QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

from .. import protocol
from ..i18n import _

THEMES = {
    "silver":    {"top": "#f4f5f7", "bottom": "#c9ccd2", "edge": "#9ea3ab", "text": "#4b5563"},
    "spacegray": {"top": "#6b6f76", "bottom": "#3d4046", "edge": "#2a2c30", "text": "#d1d5db"},
    "black":     {"top": "#2b2b2e", "bottom": "#121214", "edge": "#050506", "text": "#9ca3af"},
}
FINGER_COLORS = ["#3b82f6", "#ef4444", "#22c55e", "#f59e0b", "#a855f7", "#06b6d4", "#ec4899", "#84cc16",
                 "#f97316", "#14b8a6", "#6366f1", "#e11d48", "#0ea5e9", "#65a30d", "#d946ef", "#facc15"]
BODY_ASPECT = 0.52          # width / length of the mouse top view
AXIS_SCALE = 3.0            # touch major/minor raw -> surface units (diameter)


class MouseView(QWidget):
    def __init__(self, settings, parent=None):
        super().__init__(parent)
        self.settings = settings
        self.setMinimumSize(220, 360)
        self.frame: protocol.TouchFrame | None = None
        self.frame_time = 0.0
        self.trails: dict[int, deque] = {}
        self.buttons = 0
        self.force_zones = False
        self._dirty = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(16)   # repaint at most ~60 fps

    # ---- data -----------------------------------------------------------
    def push(self, fr: protocol.TouchFrame):
        self.frame = fr
        self.frame_time = time.monotonic()
        self.buttons = fr.buttons
        live = set()
        for t in fr.touches:
            if not t.down:
                continue
            live.add(t.id)
            q = self.trails.setdefault(t.id, deque(maxlen=28))
            q.append((t.x, t.y))
        for k in list(self.trails):
            if k not in live:
                del self.trails[k]
        self._dirty = True

    def _tick(self):
        # fingers vanish if the mouse stops reporting (it only sends on change)
        if self.frame and self.frame.touches and time.monotonic() - self.frame_time > 1.0:
            self.frame = protocol.TouchFrame(self.buttons, 0, 0, [])
            self.trails.clear()
            self._dirty = True
        if self._dirty:
            self._dirty = False
            self.update()

    # ---- geometry --------------------------------------------------------
    def _body_rect(self) -> QRectF:
        w, h = self.width() - 24, self.height() - 24
        rot = self.settings.rotate % 180 == 90
        aspect = (1 / BODY_ASPECT) if rot else BODY_ASPECT
        bw = min(w, h * aspect)
        bh = bw / aspect
        return QRectF((self.width() - bw) / 2, (self.height() - bh) / 2, bw, bh)

    def _map(self, x: float, y: float) -> tuple[float, float]:
        """surface coords -> normalized (u across, v along; v=0 front) after mirror/rotate."""
        u = (x - protocol.X_MIN) / (protocol.X_MAX - protocol.X_MIN)
        v = (y - protocol.Y_MIN) / (protocol.Y_MAX - protocol.Y_MIN)
        if self.settings.mirror_x:
            u = 1 - u
        if self.settings.mirror_y:
            v = 1 - v
        return u, v

    def _to_widget(self, r: QRectF, u: float, v: float) -> QPointF:
        rot = self.settings.rotate % 360
        if rot == 90:
            u, v = 1 - v, u
        elif rot == 180:
            u, v = 1 - u, 1 - v
        elif rot == 270:
            u, v = v, 1 - u
        inset = 0.06
        return QPointF(r.left() + r.width() * (inset + u * (1 - 2 * inset)),
                       r.top() + r.height() * (inset + v * (1 - 2 * inset)))

    def _zone_poly(self, r: QRectF, x0: float, y0: float, x1: float, y1: float) -> QPainterPath:
        """Rectangle in device coords (from left edge / from front edge) -> widget path."""
        pts = [self._to_widget(r, *self._map(protocol.X_MIN + x, protocol.Y_MIN + y))
               for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1))]
        path = QPainterPath(pts[0])
        for pt in pts[1:]:
            path.lineTo(pt)
        path.closeSubpath()
        return path

    def _draw_zones(self, p: QPainter, r: QRectF, body: QPainterPath) -> None:
        s = self.settings
        W = protocol.X_MAX - protocol.X_MIN
        L = protocol.Y_MAX - protocol.Y_MIN
        lh = s.left_handed

        def X(v):                      # left-handed mirrors the zones left/right
            return W - v if lh else v

        def fill(path, color):
            p.fillPath(body.intersected(path), color)

        # the sensor area is inset from the shell: zones touching an edge are extended to the shell
        ex, ey = W * 0.1, L * 0.1
        # tap area (front part)
        fill(self._zone_poly(r, -ex, -ey, W + ex, s.tap_area_from_top), QColor(34, 197, 94, 38))
        # middle (3rd) button strip
        a, b = sorted((X(s.middle1_start), X(s.middle1_end)))
        fill(self._zone_poly(r, a, -ey, b, s.tap_area_from_top), QColor(168, 85, 247, 45))
        # ignore areas
        red = QColor(239, 68, 68, 60)
        l0, l1 = sorted((X(-ex), X(s.ignore_side_left)))
        r0, r1 = sorted((X(W - s.ignore_side_right), X(W + ex)))
        fill(self._zone_poly(r, l0, -ey, l1, L + ey), red)
        fill(self._zone_poly(r, r0, -ey, r1, L + ey), red)
        fill(self._zone_poly(r, -ex, L - s.ignore_bottom, W + ex, L + ey), red)
        # button split line
        sx = X(W * s.button_split / 100)
        a = self._to_widget(r, *self._map(protocol.X_MIN + sx, protocol.Y_MIN))
        b = self._to_widget(r, *self._map(protocol.X_MIN + sx, protocol.Y_MIN + s.tap_area_from_top))
        p.setPen(QPen(QColor(59, 130, 246, 180), 2, Qt.DashLine))
        p.drawLine(a, b)

    def _units_to_px(self, r: QRectF) -> float:
        long_px = max(r.width(), r.height())
        return long_px / (protocol.Y_MAX - protocol.Y_MIN)

    # ---- painting ---------------------------------------------------------
    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        theme = THEMES.get(self.settings.color, THEMES["silver"])
        r = self._body_rect()
        radius = min(r.width(), r.height()) * 0.46

        body = QPainterPath()
        body.addRoundedRect(r, radius, radius)

        # shadow
        p.save()
        p.translate(0, 6)
        p.fillPath(body, QColor(0, 0, 0, 60))
        p.restore()

        horiz = self.settings.rotate % 180 == 90
        g = QLinearGradient(r.topLeft(), r.topRight() if horiz else r.bottomLeft())
        g.setColorAt(0, QColor(theme["top"]))
        g.setColorAt(1, QColor(theme["bottom"]))
        p.fillPath(body, QBrush(g))
        # glossy highlight
        hl = QRadialGradient(r.center() + QPointF(-r.width() * 0.15, -r.height() * 0.2), max(r.width(), r.height()) * 0.6)
        hl.setColorAt(0, QColor(255, 255, 255, 70))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(body, QBrush(hl))

        # click highlight (front half = button area)
        if self.buttons & 0x03:
            front = QPainterPath()
            a = self._to_widget(r, 0, 0)
            b = self._to_widget(r, 1, 0.45)
            front.addRect(QRectF(a, b).normalized())
            p.fillPath(body.intersected(front), QColor(59, 130, 246, 45))

        if self.settings.show_zones or self.force_zones:
            self._draw_zones(p, r, body)

        p.setPen(QPen(QColor(theme["edge"]), 2))
        p.drawPath(body)

        # front marker
        p.setPen(QColor(theme["text"]))
        p.setFont(QFont("Segoe UI", 8))
        fp = self._to_widget(r, 0.5, 0.0)
        p.drawText(QRectF(fp.x() - 40, fp.y() - 2, 80, 14), Qt.AlignHCenter, _("front"))

        # fingers
        fr = self.frame if self.settings.live_touches else None
        scale = self._units_to_px(r)
        if fr:
            if self.settings.show_trails:
                for fid, pts in self.trails.items():
                    col = QColor(FINGER_COLORS[fid % len(FINGER_COLORS)])
                    for i in range(1, len(pts)):
                        col.setAlpha(int(200 * i / len(pts)))
                        p.setPen(QPen(col, 3, Qt.SolidLine, Qt.RoundCap))
                        a = self._to_widget(r, *self._map(*pts[i - 1]))
                        b = self._to_widget(r, *self._map(*pts[i]))
                        p.drawLine(a, b)
            for t in fr.touches:
                if not t.present:
                    continue
                c = self._to_widget(r, *self._map(t.x, t.y))
                col = QColor(FINGER_COLORS[t.id % len(FINGER_COLORS)])
                maj = max(t.major * AXIS_SCALE * scale, 10)
                mnr = max(t.minor * AXIS_SCALE * scale, 10)
                ang = t.orientation * 90.0 / 32.0 + (self.settings.rotate % 360)
                p.save()
                p.translate(c)
                p.rotate(ang)
                if not t.down:
                    col.setAlpha(70)
                fill = QRadialGradient(QPointF(0, 0), max(maj, mnr) / 2)
                inner = QColor(col); inner.setAlpha(min(230, col.alpha()))
                outer = QColor(col); outer.setAlpha(min(90, col.alpha()))
                fill.setColorAt(0, inner)
                fill.setColorAt(1, outer)
                p.setBrush(QBrush(fill))
                p.setPen(QPen(col.darker(130), 2))
                p.drawEllipse(QPointF(0, 0), mnr / 2, maj / 2)
                p.restore()
                if self.settings.show_labels:
                    p.setPen(QColor("#111827") if self.settings.color == "silver" else QColor("#f9fafb"))
                    p.setFont(QFont("Segoe UI", 9, QFont.Bold))
                    p.drawText(QRectF(c.x() - 20, c.y() - 8, 40, 16), Qt.AlignCenter, str(t.id))
        p.end()
