# make_icon.py
# Run once before building the exe:
#   python make_icon.py
#
# Generates icon.ico (16, 32, 48, 256 px) using the same orange
# ring + crosshair as the system tray icon.
# Requires Pillow:  pip install pillow

import io
import sys

from PyQt6.QtCore    import QBuffer, QIODevice, Qt
from PyQt6.QtGui     import QColor, QPainter, QPen, QPixmap
from PyQt6.QtWidgets import QApplication

COLOR_ORANGE = "#FF6B00"


def _draw(size: int) -> QPixmap:
    px = QPixmap(size, size)
    px.fill(QColor(0, 0, 0, 0))
    p = QPainter(px)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)

    orange   = QColor(COLOR_ORANGE)
    pen_w    = max(1.0, size * 2.0 / 32)
    margin   = max(1,   round(size * 3   / 32))
    gap      = max(2,   round(size * 4   / 32))
    edge     = margin + round(pen_w / 2)
    c        = size // 2

    p.setPen(QPen(orange, pen_w))
    p.setBrush(Qt.BrushStyle.NoBrush)

    # Ring
    p.drawEllipse(margin, margin, size - 2 * margin, size - 2 * margin)

    # Crosshair (four arms with centre gap)
    p.drawLine(c, edge,      c, c - gap)
    p.drawLine(c, c + gap,   c, size - edge)
    p.drawLine(edge,     c,  c - gap, c)
    p.drawLine(c + gap,  c,  size - edge, c)

    p.end()
    return px


def _png_bytes(px: QPixmap) -> bytes:
    buf = QBuffer()
    buf.open(QIODevice.OpenModeFlag.WriteOnly)
    px.save(buf, "PNG")
    buf.close()
    return bytes(buf.data())


def main():
    app = QApplication(sys.argv)  # noqa: F841  (needed for QPainter)

    sizes   = [16, 20, 24, 32, 48, 256]
    out     = "icon.ico"

    try:
        from PIL import Image
    except ImportError:
        print("ERROR: Pillow is required.  Run:  pip install pillow")
        sys.exit(1)

    frames = [
        Image.open(io.BytesIO(_png_bytes(_draw(s)))).convert("RGBA")
        for s in sizes
    ]

    frames[0].save(
        out,
        format="ICO",
        append_images=frames[1:],
        sizes=[(s, s) for s in sizes],
    )
    print(f"Written: {out}  ({', '.join(str(s) for s in sizes)} px)")


if __name__ == "__main__":
    main()
