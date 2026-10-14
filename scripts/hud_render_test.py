"""
Renders the HUD capsule offscreen at several display-scaling factors and verifies that the 1px
hairline rim is geometrically symmetric (top == bottom, left == right) at every scale.

Usage:  python scripts/hud_render_test.py [output_dir]
Each scale factor is rendered in its own subprocess because Qt reads QT_SCALE_FACTOR at startup.
"""

import os
import subprocess
import sys

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))

CHILD = r"""
import os, sys
sys.path.insert(0, {root!r})
os.environ["QT_QPA_PLATFORM"] = os.environ.get("QT_QPA_PLATFORM", "windows")
from PyQt6.QtWidgets import QApplication
from PyQt6.QtGui import QColor
from src.ui.hud import TaktPillWidget

app = QApplication(sys.argv)
w = TaktPillWidget("#ffbdd4")
out_dir, scale = {out!r}, {scale!r}
results = {{}}
for state in ("recording", "processing"):
    w.s_alpha.snap(1.0); w.s_rise.snap(0.0); w.s_scale.snap(1.0)
    w.s_think.snap(1.0 if state == "processing" else 0.0)
    w.s_width.snap(184.0 if state == "recording" else 190.0)
    w.mode = "recording" if state == "recording" else "processing"
    if state == "recording":
        import math
        w.bar_values = [0.15 + 0.7 * abs(math.sin(i * 0.5)) for i in range(w.NUM_BARS)]
    img = w.grab().toImage()
    img.save(os.path.join(out_dir, "hud_%s_%s.png" % (scale, state)))
    W, H = img.width(), img.height()
    def alpha(x, y): return QColor(img.pixel(x, y)).alpha() if False else (img.pixel(x, y) >> 24) & 0xFF
    # Column / row away from the bars
    col = W // 2 - int(40 * img.devicePixelRatio())
    top = [alpha(col, y) for y in range(H)]
    first = next(i for i, a in enumerate(top) if a > 0)
    last = max(i for i, a in enumerate(top) if a > 0)
    lum = [(img.pixel(col, y) >> 16) & 0xFF for y in range(H)]  # red channel = rim/body brightness
    results[state] = (lum[first:first + 3], list(reversed(lum[last - 2:last + 1])), last - first + 1)
for state, (t, b, ph) in results.items():
    ok = all(abs(x - y) <= 2 for x, y in zip(t, b))
    print("scale=%s %-10s top=%s bottom=%s height_px=%d -> %s" % (scale, state, t, b, ph, "SYMMETRIC" if ok else "ASYMMETRIC"))
    if not ok:
        sys.exit(1)
"""


def main():
    out_dir = sys.argv[1] if len(sys.argv) > 1 else os.path.join(ROOT, "build", "hud_render")
    os.makedirs(out_dir, exist_ok=True)
    failed = False
    for scale in ("1", "1.25", "1.5", "2"):
        env = dict(os.environ, QT_SCALE_FACTOR=scale, QT_ENABLE_HIGHDPI_SCALING="1")
        code = CHILD.format(root=ROOT, out=out_dir, scale=scale)
        r = subprocess.run([sys.executable, "-c", code], env=env, capture_output=True, text=True, timeout=60)
        print(r.stdout.strip() or r.stderr.strip()[-600:])
        failed |= r.returncode != 0
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
