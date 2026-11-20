"""Draw the MagicMouse Studio app icon (vector, QPainter) -> mmstudio/assets/app.ico (16..256) + app.png (512).
usage: .venv\\Scripts\\python.exe tools\\make_icon.py
Design: indigo->violet->sky rounded tile, white Magic Mouse seen from above with its touch-sensor dot
matrix lit up like a heat map around one glowing touch with ripple rings (the live sensor view)."""
import io, pathlib, struct, sys
from PySide6.QtCore import QBuffer, QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QGuiApplication, QImage, QLinearGradient, QPainter, QPainterPath, QPen,
                           QRadialGradient)

OUT = pathlib.Path(__file__).resolve().parents[1] / "mmstudio" / "assets"


def draw(size: int) -> QImage:
    img = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    img.fill(Qt.transparent)
    p = QPainter(img)
    p.setRenderHint(QPainter.Antialiasing)
    p.scale(size / 256.0, size / 256.0)          # draw on a 256 grid
    small = size <= 24

    # tile
    tile = QPainterPath()
    tile.addRoundedRect(QRectF(8, 8, 240, 240), 56, 56)
    g = QLinearGradient(QPointF(8, 8), QPointF(248, 248))
    g.setColorAt(0.0, QColor("#4f46e5"))
    g.setColorAt(0.55, QColor("#7c3aed"))
    g.setColorAt(1.0, QColor("#0ea5e9"))
    p.fillPath(tile, g)
    if not small:                                 # soft top highlight
        hl = QLinearGradient(QPointF(0, 8), QPointF(0, 130))
        hl.setColorAt(0, QColor(255, 255, 255, 60))
        hl.setColorAt(1, QColor(255, 255, 255, 0))
        p.fillPath(tile, hl)

    # mouse body (top view): long rounded capsule, slightly wider at the back
    body = QPainterPath()
    if small:
        body.addRoundedRect(QRectF(78, 30, 100, 196), 50, 50)
    else:
        body.moveTo(128, 34)
        body.cubicTo(178, 34, 184, 80, 184, 128)
        body.cubicTo(184, 186, 174, 224, 128, 224)
        body.cubicTo(82, 224, 72, 186, 72, 128)
        body.cubicTo(72, 80, 78, 34, 128, 34)
    if not small:                                 # drop shadow
        p.save()
        p.translate(0, 7)
        p.fillPath(body, QColor(20, 10, 60, 70))
        p.restore()
    bg = QLinearGradient(QPointF(72, 34), QPointF(184, 224))
    bg.setColorAt(0, QColor("#ffffff"))
    bg.setColorAt(1, QColor("#dbe4f3"))
    p.fillPath(body, bg)

    # sensor matrix: dot grid clipped to the body, lit up around the touch (heat-map look)
    tx, ty = 132.0, 104.0
    p.save()
    p.setClipPath(body)
    p.setPen(Qt.NoPen)
    step = 26 if small else 15
    y = 46.0
    while y < 222:
        x = 128 - step * 4
        while x <= 128 + step * 4:
            d = ((x - tx) ** 2 + (y - ty) ** 2) ** 0.5
            heat = max(0.0, 1.0 - d / 70.0)
            c = QColor.fromRgbF(0.80 - 0.45 * heat, 0.84 - 0.70 * heat, 0.93 - 0.02 * heat, 1.0)
            r = (5.5 if small else 3.2) + heat * (2.5 if small else 2.6)
            p.setBrush(c)
            p.drawEllipse(QPointF(x, y), r, r)
            x += step
        y += step
    p.restore()

    # the touch: glow + ripple rings
    p.setPen(Qt.NoPen)
    if not small:
        rg = QRadialGradient(QPointF(tx, ty), 44)
        rg.setColorAt(0, QColor(124, 58, 237, 120))
        rg.setColorAt(1, QColor(124, 58, 237, 0))
        p.setBrush(rg)
        p.drawEllipse(QPointF(tx, ty), 44, 44)
        p.setBrush(Qt.NoBrush)
        for rad, alpha in ((24, 200), (36, 110)):
            p.setPen(QPen(QColor(109, 40, 217, alpha), 4))
            p.drawEllipse(QPointF(tx, ty), rad, rad)
        p.setPen(Qt.NoPen)
    core = QRadialGradient(QPointF(tx - 4, ty - 4), 16)
    core.setColorAt(0, QColor("#a78bfa"))
    core.setColorAt(1, QColor("#5b21b6"))
    p.setBrush(core)
    r = 20 if small else 13
    p.drawEllipse(QPointF(tx, ty), r, r)
    p.end()
    return img


def png_bytes(img: QImage) -> bytes:
    buf = QBuffer()
    buf.open(QBuffer.WriteOnly)
    img.save(buf, "PNG")
    return bytes(buf.data())


def write_ico(path: pathlib.Path, sizes) -> None:
    """ICO container with PNG-compressed entries (supported since Windows Vista)."""
    blobs = [png_bytes(draw(s)) for s in sizes]
    out = io.BytesIO()
    out.write(struct.pack("<HHH", 0, 1, len(sizes)))
    offset = 6 + 16 * len(sizes)
    for s, b in zip(sizes, blobs):
        out.write(struct.pack("<BBBBHHII", s % 256, s % 256, 0, 0, 1, 32, len(b), offset))
        offset += len(b)
    for b in blobs:
        out.write(b)
    path.write_bytes(out.getvalue())


if __name__ == "__main__":
    app = QGuiApplication(sys.argv)
    OUT.mkdir(parents=True, exist_ok=True)
    write_ico(OUT / "app.ico", [16, 20, 24, 32, 40, 48, 64, 128, 256])
    draw(512).save(str(OUT / "app.png"))
    prev = OUT.parents[1] / "captures"              # previews for a visual check (not packaged)
    prev.mkdir(exist_ok=True)
    draw(256).save(str(prev / "icon-preview-256.png"))
    draw(32).scaled(128, 128).save(str(prev / "icon-preview-32x4.png"))
    print("written", *sorted(x.name for x in OUT.iterdir()))
