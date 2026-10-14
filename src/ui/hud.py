"""
Takt Floating Pill HUD

A minimalist, pixel-perfect capsule anchored bottom-centre above the taskbar.

Rendering
- Everything is drawn in *physical* device pixels (the painter is scaled by 1/devicePixelRatio) and
  the capsule geometry is snapped to whole pixels. This is what keeps the 1px hairline rim exactly
  the same thickness on all four sides at 100/125/150/200% display scaling. (The old HUD drew in
  fractional logical pixels, so at 125-150% the top and bottom rim landed on different sub-pixel
  phases and looked thicker on one side.)
- The rim is a single 1px stroke inset by half a pixel on the integer capsule rectangle, drawn once,
  with no gradients, glow or sheen competing with it.
- DWM is told not to add its own border / rounding / backdrop to the window.

Motion
- Frame-rate independent spring physics (critically damped) for opacity, rise, scale, width and
  state cross-fades: opening on key press and closing on release both ease in and out.
- The visualizer is a mirrored, spectrum-driven bar field (wide, not tall) with fast attack and
  liquid release, driven by the real microphone level; a dead microphone stays visibly flat.

Positioning & Taskbar Awareness
- Intelligently detects whether the Windows taskbar is docked or set to auto-hide.
- When the taskbar is auto-hidden, standard Windows work areas report the entire screen, which
  caused the taskbar to cover the capsule whenever it popped up. Takt reserves the standard
  Windows taskbar zone plus a comfortable breathing gap, or detects the live taskbar position,
  ensuring the pill is ALWAYS positioned cleanly above the taskbar whether hidden or revealed.

The widget never takes focus and is click-through (WS_EX_NOACTIVATE | WS_EX_TRANSPARENT).
"""

import ctypes
from ctypes import wintypes
import math
import os
import random
import sys
import time
from typing import List, Optional

from PyQt6.QtCore import QObject, QPointF, QRectF, Qt, QTimer, pyqtSignal
from PyQt6.QtGui import (
    QColor, QCursor, QFont, QFontMetricsF, QGuiApplication,
    QLinearGradient, QPainter, QPainterPath, QPen
)
from PyQt6.QtWidgets import QWidget

from src.core.config import app_dir, resource_dir

# Win32 / DWM constants
GWL_EXSTYLE = -20
WS_EX_TRANSPARENT = 0x00000020
WS_EX_TOOLWINDOW = 0x00000080
WS_EX_TOPMOST = 0x00000008
WS_EX_NOACTIVATE = 0x08000000
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE = 0x0001, 0x0002, 0x0010
DWMWA_NCRENDERING_POLICY = 2
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_SYSTEMBACKDROP_TYPE = 38
DWMWCP_DONOTROUND = 1
DWMWA_COLOR_NONE = 0xFFFFFFFE
DWMNCRP_DISABLED = 1

FALLBACK_VERBS = [
    "Thinking...", "Refining...", "Synthesizing...", "Polishing...",
    "Formulating...", "Considering...", "Structuring...", "Crystallizing...",
]


def load_thinking_words() -> List[str]:
    """Loads Claude-style thinking verbs from config/technical_jargon.txt with a safe fallback."""
    candidates = [
        os.path.join(app_dir(), "config", "technical_jargon.txt"),
        os.path.join(resource_dir(), "config", "technical_jargon.txt"),
        os.path.join(resource_dir(), "_internal", "config", "technical_jargon.txt"),
    ]
    for p in candidates:
        if os.path.exists(p):
            try:
                with open(p, "r", encoding="utf-8") as f:
                    words = [line.strip() for line in f if line.strip()]
                if words:
                    return [w if w.endswith("...") else f"{w}..." for w in words]
            except Exception:
                pass
    return list(FALLBACK_VERBS)


def _detect_taskbar_baseline(screen, bottom_gap: int) -> int:
    """
    Calculates the bottom baseline (in Qt logical pixels) above which the capsule should sit.

    Ensures the capsule sits cleanly above the taskbar in all Windows configurations:
    1. Standard docked taskbar: detected via Qt screen.availableGeometry() where Windows
       already excludes the taskbar from the work area (full.bottom() - avail.bottom() > 10).
    2. Auto-hidden taskbar: Windows availableGeometry spans the full screen. When the taskbar
       is revealed (by mouse hover, Win key, etc.), it slides up ~48 logical pixels on Windows 11.
       We check if the live taskbar window is currently up via Win32, or reserve the 48px
       taskbar zone by default so the capsule sits comfortably above it from the start without
       jumping around or ever being covered when the taskbar pops up.
    """
    full = screen.geometry()
    avail = screen.availableGeometry()

    # 1. Docked taskbar: availableGeometry already sits above the taskbar
    docked_bottom_bar = full.bottom() - avail.bottom()
    if docked_bottom_bar > 10:
        return avail.bottom() + 1 - bottom_gap

    # 2. Check Win32 live taskbar window if accessible and popped up
    try:
        user32 = ctypes.windll.user32
        hwnd = user32.FindWindowW("Shell_TrayWnd", None)
        if hwnd and user32.IsWindowVisible(hwnd):
            rect = wintypes.RECT()
            if user32.GetWindowRect(hwnd, ctypes.byref(rect)):
                dpr = screen.devicePixelRatio() or 1.0
                tb_top = int(rect.top / dpr)
                # If taskbar is on this screen near the bottom and popped up
                if full.top() <= tb_top < full.bottom() and (full.bottom() - tb_top) < 120:
                    if tb_top < (full.bottom() - 10):
                        return tb_top - bottom_gap
    except Exception:
        pass

    # 3. Auto-hidden taskbar default reservation:
    # Windows 11 taskbar height is standard 48 logical pixels.
    # Reserving this height ensures that when the hidden taskbar pops up, the capsule
    # is already cleanly hovering above it with the specified bottom_gap.
    WIN11_TASKBAR_HEIGHT = 48
    return full.bottom() + 1 - WIN11_TASKBAR_HEIGHT - bottom_gap


class _Spring:
    """Damped spring integrated in fixed sub-steps: frame-rate independent and overshoot-free at zeta>=1."""

    def __init__(self, value: float = 0.0, omega: float = 16.0, zeta: float = 1.0):
        self.value = value
        self.target = value
        self.vel = 0.0
        self.omega = omega
        self.zeta = zeta

    def snap(self, value: float):
        self.value = self.target = value
        self.vel = 0.0

    def step(self, dt: float):
        h = 1.0 / 240.0
        n = max(1, min(40, int(math.ceil(dt / h))))
        h = dt / n
        w, z = self.omega, self.zeta
        for _ in range(n):
            acc = -2.0 * z * w * self.vel - w * w * (self.value - self.target)
            self.vel += acc * h
            self.value += self.vel * h

    @property
    def settled(self) -> bool:
        return abs(self.value - self.target) < 5e-3 and abs(self.vel) < 5e-2


class _HUDSignalBridge(QObject):
    sig_show_recording = pyqtSignal()
    sig_update_levels = pyqtSignal(float, list)
    sig_update_text = pyqtSignal(str)
    sig_show_processing = pyqtSignal()
    sig_show_success = pyqtSignal(str)
    sig_show_notice = pyqtSignal(str)
    sig_hide = pyqtSignal()
    sig_set_accent = pyqtSignal(str)
    sig_set_bottom_offset = pyqtSignal(int)


class TaktPillWidget(QWidget):
    CANVAS_W = 380
    CANVAS_H = 76
    PILL_H = 36.0
    PILL_W_WAVE = 184.0
    DEFAULT_BASE_GAP = 24            # logical px between the capsule and the taskbar / work-area edge

    NUM_BARS = 28
    BAR_W = 2.4
    BAR_GAP = 2.8
    BAR_MAX_H = 17.0
    BAR_MIN_H = 3.0

    def __init__(self, accent_color: str = "#ffbdd4", bottom_offset: int = DEFAULT_BASE_GAP):
        super().__init__()
        self.accent = QColor(accent_color)
        if not self.accent.isValid():
            self.accent = QColor("#ffbdd4")
        self.bottom_gap = max(0, int(bottom_offset))

        self.thinking_words = load_thinking_words()
        self.thinking_text = "Refining..."
        self.notice_text = ""
        self.mode = "idle"          # idle | recording | processing | notice | closing

        # Springs: opacity, vertical rise, scale, width, and the two state cross-fades
        self.s_alpha = _Spring(0.0, 15.0)
        self.s_rise = _Spring(10.0, 14.0)
        self.s_scale = _Spring(0.90, 17.0, 0.82)
        self.s_width = _Spring(self.PILL_W_WAVE, 15.0)
        self.s_think = _Spring(0.0, 14.0)
        self.s_notice = _Spring(0.0, 14.0)

        # Audio reactive state
        self.noise_floor = 0.0005
        self.level_ref = 0.02
        self.loudness = 0.0
        self.bands: List[float] = []
        self.bar_targets = [0.0] * self.NUM_BARS
        self.bar_values = [0.0] * self.NUM_BARS
        self.wave_phase = 0.0

        self._last_tick = time.perf_counter()
        self._t0 = self._last_tick
        self._processing_since = 0.0
        self._pending_close = QTimer(self)
        self._pending_close.setSingleShot(True)
        self._pending_close.timeout.connect(self._begin_close)

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
            | Qt.WindowType.WindowTransparentForInput
            | Qt.WindowType.NoDropShadowWindowHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating, True)
        self.setAttribute(Qt.WidgetAttribute.WA_NoSystemBackground, True)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent, False)
        self.setFixedSize(self.CANVAS_W, self.CANVAS_H)

        self.anim_timer = QTimer(self)
        self.anim_timer.setTimerType(Qt.TimerType.PreciseTimer)
        self.anim_timer.setInterval(15)
        self.anim_timer.timeout.connect(self._on_anim_tick)

        self._apply_win32_attributes()

    # ------------------------------------------------------------------ window
    def _apply_win32_attributes(self):
        """Click-through, non-activating, topmost; and stop DWM from adding borders or rounding."""
        try:
            hwnd = int(self.winId())
            user32 = ctypes.windll.user32
            style = user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_TRANSPARENT
            )
            user32.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE)

            dwm = ctypes.windll.dwmapi
            for attr, value in (
                (DWMWA_WINDOW_CORNER_PREFERENCE, DWMWCP_DONOTROUND),
                (DWMWA_BORDER_COLOR, DWMWA_COLOR_NONE),
                (DWMWA_NCRENDERING_POLICY, DWMNCRP_DISABLED),
                (DWMWA_SYSTEMBACKDROP_TYPE, 1),
            ):
                v = ctypes.c_uint(value)
                dwm.DwmSetWindowAttribute(hwnd, attr, ctypes.byref(v), ctypes.sizeof(v))
        except Exception as e:
            print(f"[HUD Notice] Win32 attribute adjustment: {e}")

    def _reposition_canvas(self):
        screen = QGuiApplication.screenAt(QCursor.pos()) or QGuiApplication.primaryScreen()
        if not screen:
            return
        avail = screen.availableGeometry()
        x = avail.x() + (avail.width() - self.CANVAS_W) // 2
        # Baseline sits safely above the taskbar (docked or auto-hidden)
        baseline = _detect_taskbar_baseline(screen, self.bottom_gap)
        centre_y = baseline - int(self.PILL_H / 2)
        y = centre_y - self.CANVAS_H // 2
        self.move(x, y)

    def set_accent_color(self, hex_code: str):
        c = QColor(hex_code)
        if c.isValid():
            self.accent = c
            self.update()

    def set_bottom_offset(self, offset: int):
        self.bottom_gap = max(0, int(offset))
        if self.isVisible():
            self._reposition_canvas()

    # ----------------------------------------------------------------- states
    def _ensure_running(self):
        self._last_tick = time.perf_counter()
        if not self.anim_timer.isActive():
            self.anim_timer.start()

    def on_show_recording(self):
        self._pending_close.stop()
        was_hidden = not self.isVisible() or self.s_alpha.value < 0.05
        self.mode = "recording"

        self.loudness = 0.0
        self.bands = []
        self.bar_targets = [0.0] * self.NUM_BARS
        self.level_ref = max(self.level_ref * 0.7, 0.02)

        if was_hidden:
            self.s_alpha.snap(0.0)
            self.s_rise.snap(10.0)
            self.s_scale.snap(0.90)
            self.s_width.snap(self.PILL_W_WAVE)
            self.s_think.snap(0.0)
            self.s_notice.snap(0.0)
            self.bar_values = [0.0] * self.NUM_BARS
        self.s_alpha.target = 1.0
        self.s_rise.target = 0.0
        self.s_scale.target = 1.0
        self.s_width.target = self.PILL_W_WAVE
        self.s_think.target = 0.0
        self.s_notice.target = 0.0

        self._reposition_canvas()
        if not self.isVisible():
            self.show()
            self._apply_win32_attributes()
        self._ensure_running()

    def on_show_processing(self):
        self._pending_close.stop()
        if self.mode in ("idle", "closing") and not self.isVisible():
            self.on_show_recording()
        self.mode = "processing"
        self._processing_since = time.perf_counter()
        if not self.thinking_words:
            self.thinking_words = load_thinking_words()
        self.thinking_text = random.choice(self.thinking_words)

        fm = QFontMetricsF(self._font(1.0))
        text_w = fm.horizontalAdvance(self.thinking_text)
        self.s_width.target = max(150.0, text_w + 70.0)
        self.s_think.target = 1.0
        self.s_notice.target = 0.0
        self.s_alpha.target = 1.0
        self.s_rise.target = 0.0
        self.s_scale.target = 1.0
        self._ensure_running()

    def on_show_notice(self, text: str):
        self._pending_close.stop()
        if not self.isVisible():
            self.s_alpha.snap(0.0)
            self.s_rise.snap(10.0)
            self.s_scale.snap(0.90)
            self.s_think.snap(0.0)
            self.s_notice.snap(0.0)
            self._reposition_canvas()
            self.show()
            self._apply_win32_attributes()
        self.mode = "notice"
        self.notice_text = text
        fm = QFontMetricsF(self._font(1.0))
        max_pill_w = self.CANVAS_W - 16.0
        self.s_width.target = max(150.0, min(max_pill_w, fm.horizontalAdvance(text) + 44.0))
        self.s_think.target = 0.0
        self.s_notice.target = 1.0
        self.s_alpha.target = 1.0
        self.s_rise.target = 0.0
        self.s_scale.target = 1.0
        self._pending_close.start(2200)

    def on_show_success(self, text: str = ""):
        # Completion: smoothly and immediately begin closing without lingering or displaying transcript
        self._pending_close.stop()
        self._begin_close()

    def on_hide(self):
        self._begin_close()

    def _begin_close(self):
        if self.mode == "idle":
            return
        self.mode = "closing"
        self.s_alpha.target = 0.0
        self.s_rise.target = 8.0
        self.s_scale.target = 0.92
        self._ensure_running()

    def on_update_text(self, text: str):
        pass  # intentionally no running transcript on the capsule (minimal design)

    def on_update_levels(self, rms: float, bands: list):
        if self.mode != "recording":
            return
        # Noise floor follows quiet passages down quickly and speech up very slowly
        if rms < self.noise_floor:
            self.noise_floor = self.noise_floor * 0.8 + rms * 0.2
        else:
            self.noise_floor = self.noise_floor * 0.998 + rms * 0.002
        # Auto-ranging reference lets quiet and hot microphones both fill the visualizer
        if rms > self.level_ref:
            self.level_ref = self.level_ref * 0.6 + rms * 0.4
        else:
            self.level_ref = max(0.012, self.level_ref * 0.9992)

        net = max(0.0, rms - self.noise_floor * 1.3)
        x = min(1.0, net / (self.level_ref * 0.85))
        self.loudness = math.pow(x, 0.62) if net > 3e-4 else 0.0

        if bands:
            peak = max(max(bands), 1e-9)
            self.bands = [math.pow(b / peak, 0.7) for b in bands]
        else:
            self.bands = []

    # ---------------------------------------------------------------- animation
    def _bar_envelope(self, i: int) -> float:
        d = (i - (self.NUM_BARS - 1) / 2.0) / ((self.NUM_BARS - 1) / 2.0)   # -1 .. 1
        return math.exp(-(d / 0.78) ** 2)

    def _band_at(self, d_abs: float) -> float:
        """Mirrored spectrum: low frequencies in the centre, highs toward the edges."""
        if not self.bands:
            return 0.7
        pos = d_abs * (len(self.bands) - 1)
        lo = int(pos)
        hi = min(len(self.bands) - 1, lo + 1)
        f = pos - lo
        return self.bands[lo] * (1 - f) + self.bands[hi] * f

    def _on_anim_tick(self):
        now = time.perf_counter()
        dt = min(0.05, max(0.001, now - self._last_tick))
        self._last_tick = now

        for sp in (self.s_alpha, self.s_rise, self.s_scale, self.s_width, self.s_think, self.s_notice):
            sp.step(dt)

        # Visualizer physics (recording only; otherwise bars relax to rest)
        self.wave_phase += dt * (3.2 + 5.0 * self.loudness)
        n = self.NUM_BARS
        for i in range(n):
            d = (i - (n - 1) / 2.0) / ((n - 1) / 2.0)
            env = self._bar_envelope(i)
            ripple = 0.5 + 0.5 * math.sin(self.wave_phase - abs(d) * 4.2 + i * 0.35)
            band = self._band_at(abs(d))
            level = self.loudness * (0.30 + 0.70 * band) * (0.55 + 0.45 * ripple) * (0.25 + 0.75 * env)
            idle = 0.045 * env * (0.5 + 0.5 * math.sin(self.wave_phase * 0.55 + i * 0.5))
            target = (level + idle) if self.mode == "recording" else 0.0
            cur = self.bar_values[i]
            rate = 26.0 if target > cur else 9.0           # fast attack, liquid release (1/s)
            self.bar_values[i] = cur + (target - cur) * (1.0 - math.exp(-rate * dt))

        if self.mode == "closing" and self.s_alpha.value < 0.012 and self.s_alpha.target == 0.0:
            self.anim_timer.stop()
            self.s_alpha.snap(0.0)
            self.hide()
            self.mode = "idle"
            return

        self.update()

    # ----------------------------------------------------------------- painting
    def _font(self, dpr: float) -> QFont:
        font = QFont()
        font.setFamilies(["Segoe UI Variable Text", "Segoe UI"])
        font.setPixelSize(max(8, int(round(13 * dpr))))
        font.setWeight(QFont.Weight.Medium)
        font.setItalic(False)
        font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
        font.setHintingPreference(QFont.HintingPreference.PreferNoHinting)
        return font

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_Source)
        painter.fillRect(self.rect(), QColor(0, 0, 0, 0))
        painter.setCompositionMode(QPainter.CompositionMode.CompositionMode_SourceOver)

        alpha = max(0.0, min(1.0, self.s_alpha.value))
        if alpha <= 0.002:
            painter.end()
            return

        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        painter.setRenderHint(QPainter.RenderHint.TextAntialiasing, True)

        # Work in physical pixels from here on
        dpr = self.devicePixelRatioF()
        painter.scale(1.0 / dpr, 1.0 / dpr)
        W = int(round(self.width() * dpr))
        H = int(round(self.height() * dpr))

        scale = max(0.5, self.s_scale.value)
        pw = 2 * int(round(self.s_width.value * scale * dpr / 2.0))
        ph = 2 * int(round(self.PILL_H * scale * dpr / 2.0))
        left = (W - pw) // 2
        top = int(round((H - ph) / 2.0 + self.s_rise.value * dpr))
        r = ph / 2.0

        painter.setOpacity(alpha)

        # 1. Capsule body (whole-pixel rectangle -> symmetric edges)
        body = QPainterPath()
        body.addRoundedRect(QRectF(left, top, pw, ph), r, r)
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QColor(12, 12, 14, 246))
        painter.drawPath(body)

        # 2. 1px hairline rim: centred on the outermost pixel ring (inset 0.5px, width 1px)
        rim = QPainterPath()
        rim.addRoundedRect(QRectF(left + 0.5, top + 0.5, pw - 1.0, ph - 1.0), r - 0.5, r - 0.5)
        painter.setBrush(Qt.BrushStyle.NoBrush)
        painter.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        painter.drawPath(rim)

        cx = left + pw / 2.0
        cy = top + ph / 2.0

        wave_w = 1.0 - max(0.0, min(1.0, self.s_think.value + self.s_notice.value))
        if wave_w > 0.01:
            self._draw_wave(painter, cx, cy, dpr, scale, wave_w)
        if self.s_think.value > 0.01:
            self._draw_thinking(painter, cx, cy, dpr, self.s_think.value)
        if self.s_notice.value > 0.01:
            self._draw_notice(painter, cx, cy, dpr, self.s_notice.value)
        painter.end()

    def _draw_wave(self, painter: QPainter, cx: float, cy: float, dpr: float, scale: float, weight: float):
        n = self.NUM_BARS
        step = (self.BAR_W + self.BAR_GAP) * dpr * scale
        total_w = (n - 1) * step + (self.BAR_W * dpr * scale)
        start_x = cx - total_w / 2.0

        accent = self.accent
        r_acc, g_acc, b_acc = accent.red(), accent.green(), accent.blue()
        bar_w_phys = max(1.0, round(self.BAR_W * dpr * scale))

        for i in range(n):
            v = self.bar_values[i]
            h_val = (self.BAR_MIN_H + (self.BAR_MAX_H - self.BAR_MIN_H) * v) * dpr * scale
            h_phys = max(2, 2 * int(round(h_val / 2.0)))
            bx = round(start_x + i * step)
            by = round(cy - h_phys / 2.0)

            intensity = max(0.0, min(1.0, v * 1.25))
            r = int(round(180 + (r_acc - 180) * intensity))
            g = int(round(184 + (g_acc - 184) * intensity))
            b = int(round(192 + (b_acc - 192) * intensity))
            a = int(round((140 + 115 * intensity) * weight))

            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QColor(r, g, b, a))
            cr = bar_w_phys / 2.0
            painter.drawRoundedRect(QRectF(bx, by, bar_w_phys, h_phys), cr, cr)

    def _draw_thinking(self, painter: QPainter, cx: float, cy: float, dpr: float, weight: float):
        font = self._font(dpr)
        painter.setFont(font)
        fm = QFontMetricsF(font)
        text_w = fm.horizontalAdvance(self.thinking_text)

        elapsed = time.perf_counter() - self._processing_since
        sweep = (elapsed * 1.8) % 1.0
        grad = QLinearGradient(QPointF(cx - text_w / 2.0, 0), QPointF(cx + text_w / 2.0, 0))
        c_base = QColor(190, 194, 204, int(220 * weight))
        c_bright = QColor(self.accent.red(), self.accent.green(), self.accent.blue(), int(255 * weight))

        s0 = max(0.0, sweep - 0.28)
        s1 = sweep
        s2 = min(1.0, sweep + 0.28)
        grad.setColorAt(0.0, c_base)
        if s0 > 0.0:
            grad.setColorAt(s0, c_base)
        grad.setColorAt(s1, c_bright)
        if s2 < 1.0:
            grad.setColorAt(s2, c_base)
        grad.setColorAt(1.0, c_base)

        painter.setPen(QPen(grad, 1.0))
        baseline = round(cy + (fm.ascent() - fm.descent()) / 2.0)
        painter.drawText(QPointF(round(cx - text_w / 2.0), baseline), self.thinking_text)

    def _draw_notice(self, painter: QPainter, cx: float, cy: float, dpr: float, weight: float):
        font = self._font(dpr)
        painter.setFont(font)
        fm = QFontMetricsF(font)
        max_text_w = max(20.0, (self.s_width.value - 28.0) * dpr)
        display_text = fm.elidedText(self.notice_text, Qt.TextElideMode.ElideRight, max_text_w)
        text_w = fm.horizontalAdvance(display_text)
        painter.setPen(QColor(244, 245, 248, int(235 * weight)))
        baseline = round(cy + (fm.ascent() - fm.descent()) / 2.0)
        painter.drawText(QPointF(round(cx - text_w / 2.0), baseline), display_text)


class TaktHUD:
    """
    Public thread-safe interface for the pipeline and background threads.
    Every call is marshalled onto the Qt UI thread through signals.
    """

    def __init__(self, accent_color: str = "#ffbdd4", bottom_offset: int = 24):
        self.bridge = _HUDSignalBridge()
        self.widget = TaktPillWidget(accent_color=accent_color, bottom_offset=bottom_offset)

        self.bridge.sig_show_recording.connect(self.widget.on_show_recording)
        self.bridge.sig_update_levels.connect(self.widget.on_update_levels)
        self.bridge.sig_update_text.connect(self.widget.on_update_text)
        self.bridge.sig_show_processing.connect(self.widget.on_show_processing)
        self.bridge.sig_show_success.connect(self.widget.on_show_success)
        self.bridge.sig_show_notice.connect(self.widget.on_show_notice)
        self.bridge.sig_hide.connect(self.widget.on_hide)
        self.bridge.sig_set_accent.connect(self.widget.set_accent_color)
        self.bridge.sig_set_bottom_offset.connect(self.widget.set_bottom_offset)

    def set_accent_color(self, hex_code: str):
        self.bridge.sig_set_accent.emit(hex_code)

    def set_bottom_offset(self, offset: int):
        self.bridge.sig_set_bottom_offset.emit(int(offset))

    def show_recording(self):
        self.bridge.sig_show_recording.emit()

    def update_levels(self, rms: float, bands: Optional[List[float]] = None):
        try:
            self.bridge.sig_update_levels.emit(float(rms), [float(b) for b in (bands or [])])
        except Exception:
            pass

    def update_rms(self, rms: float):
        self.update_levels(rms, [])

    def update_text(self, text: str):
        self.bridge.sig_update_text.emit(text)

    def show_processing(self):
        self.bridge.sig_show_processing.emit()

    def show_success(self, text: str = ""):
        self.bridge.sig_show_success.emit(text)

    def show_notice(self, text: str):
        self.bridge.sig_show_notice.emit(text)

    def hide(self):
        self.bridge.sig_hide.emit()
