"""
Takt Preferences (Modern Dark Fluent Edition)

A resizable, sidebar-navigated settings window:
  General      hotkey, activation mode, start with Windows, HUD visibility
  Audio        microphone selection, live level meter and silent-device diagnosis
  Appearance   accent colour with a pixel-accurate live preview of the HUD capsule
  Text & AI    formatter mode, Ollama endpoint / model discovery and connection test
  Privacy      redaction shield, history & recordings retention, idle memory sleep
  About        version, hardware summary, logs and update package installer

Settings are saved atomically to the user config (%APPDATA%/Takt/app_config.yaml); a running Takt instance applies them
instantly (in-process callback, or its file watcher when launched via `Takt.exe --settings`).
"""

import copy
import math
import os
import platform
import subprocess
import sys
import time
import winreg
from typing import Callable, List, Optional

import numpy as np
import psutil
import sounddevice as sd

from PyQt6.QtCore import (
    QEasingCurve, QPointF, QPropertyAnimation, QRectF, QSize, Qt, QThread, QTimer, pyqtProperty, pyqtSignal
)
from PyQt6.QtGui import QColor, QFont, QLinearGradient, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QAbstractButton, QButtonGroup, QColorDialog, QComboBox, QFileDialog, QFrame, QHBoxLayout, QLabel,
    QLineEdit, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QStackedWidget, QVBoxLayout, QWidget
)

from src.audio.capture import DEAD_PEAK_THRESHOLD, InputDevice, list_input_devices
from src.core.config import DEFAULT_CONFIG, app_dir, deep_merge, load_config, save_config
from src.engine.formatter import list_ollama_models

REG_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
APP_NAME = "TaktDictation"
APP_VERSION = "1.1.0"

PRESET_COLORS = [
    ("#ffbdd4", "Sakura Rose"),
    ("#a78bfa", "Electric Violet"),
    ("#38bdf8", "Cyber Cyan"),
    ("#34d399", "Emerald Mint"),
    ("#fb923c", "Sunset Peach"),
    ("#f43f5e", "Crimson Neon"),
    ("#e2e8f0", "Titanium Silver"),
]

HOTKEYS = [
    ("alt_r", "Right Alt  (recommended)"),
    ("alt_l", "Left Alt"),
    ("ctrl_r", "Right Ctrl"),
    ("ctrl_l", "Left Ctrl"),
] + [(f"f{n}", f"F{n}") for n in range(13, 25)]

MODES = [
    ("push_to_talk", "Push-to-talk  (hold to speak)"),
    ("toggle", "Toggle  (press to start / stop)"),
]

IDLE_SLEEP = [(60, "After 1 minute"), (180, "After 3 minutes  (recommended)"),
              (300, "After 5 minutes"), (999999, "Never")]
KEEP_RECORDINGS = [(0, "Don't save recordings"), (10, "Keep last 10"), (25, "Keep last 25"), (50, "Keep last 50"),
                   (100, "Keep last 100")]

BG = "#0B0C10"
PANEL = "#101219"
CARD = "#141722"
BORDER = "#222637"
TEXT = "#ECEEF5"
MUTED = "#8087A2"
SUCCESS = "#34D399"
WARN = "#FBBF24"
DANGER = "#F87171"


def _on_color(hex_color: str) -> str:
    return "#0B0C10" if QColor(hex_color).lightness() > 140 else "#FFFFFF"


def build_qss(accent: str) -> str:
    on = _on_color(accent)
    return f"""
    QWidget {{ background: transparent; color: {TEXT};
        font-family: 'Segoe UI Variable Text', 'Segoe UI'; font-size: 13px; }}
    QWidget#Root {{ background: {BG}; }}
    QFrame#Sidebar {{ background: {PANEL}; border-right: 1px solid {BORDER}; }}
    QLabel#Brand {{ font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 20px; font-weight: 700; }}
    QLabel#BrandSub {{ color: {MUTED}; font-size: 11px; }}
    QPushButton#Nav {{ text-align: left; padding: 9px 14px; border: none; border-radius: 8px;
        color: {MUTED}; font-size: 13px; font-weight: 500; background: transparent; }}
    QPushButton#Nav:hover {{ background: #181B28; color: {TEXT}; }}
    QPushButton#Nav:checked {{ background: #1B1F2F; color: {TEXT}; }}
    QLabel#PageTitle {{ font-family: 'Segoe UI Variable Display', 'Segoe UI'; font-size: 22px; font-weight: 700; }}
    QLabel#PageDesc {{ color: {MUTED}; font-size: 12px; }}
    QFrame#Card {{ background: {CARD}; border: 1px solid {BORDER}; border-radius: 12px; }}
    QLabel#CardTitle {{ color: {MUTED}; font-size: 11px; font-weight: 700; letter-spacing: 1px; }}
    QLabel#RowTitle {{ font-size: 13px; font-weight: 600; }}
    QLabel#RowDesc {{ color: {MUTED}; font-size: 11.5px; }}
    QFrame#Sep {{ background: {BORDER}; max-height: 1px; min-height: 1px; border: none; }}
    QScrollArea {{ border: none; background: transparent; }}
    QScrollBar:vertical {{ background: transparent; width: 8px; margin: 2px; }}
    QScrollBar::handle:vertical {{ background: #2A2F44; border-radius: 3px; min-height: 30px; }}
    QScrollBar::handle:vertical:hover {{ background: #3A4160; }}
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
    QComboBox, QLineEdit {{ background: #0E1018; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 7px 12px; min-height: 18px; selection-background-color: {accent}; selection-color: {on}; }}
    QComboBox:hover, QLineEdit:hover {{ border-color: #343A55; }}
    QComboBox:focus, QLineEdit:focus {{ border-color: {accent}; }}
    QComboBox::drop-down {{ border: none; width: 28px; }}
    QComboBox QAbstractItemView {{ background: #0E1018; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 4px; outline: none; selection-background-color: #1E2235; selection-color: {TEXT}; }}
    QPushButton {{ background: #1A1E2D; border: 1px solid {BORDER}; border-radius: 8px;
        padding: 7px 16px; font-weight: 500; }}
    QPushButton:hover {{ background: #222739; border-color: #343A55; }}
    QPushButton:pressed {{ background: #181C2A; }}
    QPushButton:disabled {{ color: #565C74; background: #12141D; }}
    QPushButton#Primary {{ background: {accent}; color: {on}; border: none; font-weight: 700; padding: 8px 22px; }}
    QPushButton#Primary:hover {{ background: {QColor(accent).lighter(110).name()}; }}
    QPushButton#Primary:disabled {{ background: #2A2F44; color: #6B7190; }}
    QFrame#Footer {{ background: {PANEL}; border-top: 1px solid {BORDER}; }}
    QToolTip {{ background: #1B1F2F; color: {TEXT}; border: 1px solid {BORDER}; padding: 4px 8px; }}
    """


# ------------------------------------------------------------------------------ widgets
ROUTERS = (
    ("Smart Hybrid (Zero-Latency Heuristic - Recommended)", "heuristic"),
    ("Always Smart (Format Every Dictation)", "always_smart"),
    ("Jev (TypeSafe Cloud API)", "jev"),
    ("Disabled", "disabled"),
)
GROQ_MODELS = (
    ("Qwen 3.8 27B (Ultra-Fast - Recommended)", "qwen/qwen3.8-27b"),
    ("GPT-OSS 120B (Deep Reasoning)", "openai/gpt-oss-120b"),
    ("GPT-OSS 20B (Fast)", "openai/gpt-oss-20b"),
    ("Allam 2 7B", "allam-2-7b"),
)


class Combo(QComboBox):
    """QComboBox that keeps a visible chevron under the custom stylesheet."""

    def wheelEvent(self, e):          # don't change values while scrolling the page
        e.ignore()

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.setPen(QPen(QColor(MUTED), 1.6, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap, Qt.PenJoinStyle.RoundJoin))
        cx, cy = self.width() - 17.0, self.height() / 2.0
        p.drawPolyline([QPointF(cx - 4, cy - 2), QPointF(cx, cy + 2), QPointF(cx + 4, cy - 2)])
        p.end()


class ToggleSwitch(QAbstractButton):
    """Windows 11 style switch (keyboard accessible, animated)."""

    def __init__(self, checked: bool = False, accent: str = "#ffbdd4", parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setFixedSize(44, 24)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)
        self._accent = QColor(accent)
        self._pos = 1.0 if checked else 0.0
        self.setChecked(checked)
        self._anim = QPropertyAnimation(self, b"pos_", self)
        self._anim.setDuration(150)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutCubic)
        self.toggled.connect(self._animate)

    def _get(self) -> float:
        return self._pos

    def _set(self, v: float):
        self._pos = v
        self.update()

    pos_ = pyqtProperty(float, _get, _set)

    def _animate(self, on: bool):
        self._anim.stop()
        self._anim.setStartValue(self._pos)
        self._anim.setEndValue(1.0 if on else 0.0)
        self._anim.start()

    def set_accent(self, hex_code: str):
        self._accent = QColor(hex_code)
        self.update()

    def set_checked_instant(self, value: bool):
        """Sets the state without animating (used when loading saved values)."""
        self.setChecked(value)
        self._anim.stop()
        self._pos = 1.0 if value else 0.0
        self.update()

    def sizeHint(self):
        return QSize(44, 24)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h, t = float(self.width()), float(self.height()), self._pos
        off, on = QColor("#262B3F"), self._accent
        track = QColor(int(off.red() + (on.red() - off.red()) * t), int(off.green() + (on.green() - off.green()) * t),
                       int(off.blue() + (on.blue() - off.blue()) * t))
        p.setBrush(track)
        p.setPen(QPen(QColor(255, 255, 255, 28 if t < 0.5 else 0), 1.0))
        p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), (h - 1) / 2, (h - 1) / 2)
        d = h - 8.0
        x = 4.0 + t * (w - d - 8.0)
        thumb = QColor("#0B0C10") if (t > 0.5 and on.lightness() > 150) else QColor("#FFFFFF")
        thumb.setAlpha(255 if t > 0.5 else 215)
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(thumb)
        p.drawEllipse(QRectF(x, 4.0, d, d))
        if self.hasFocus():
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.setPen(QPen(QColor(on.red(), on.green(), on.blue(), 160), 1.5))
            p.drawRoundedRect(QRectF(0.5, 0.5, w - 1, h - 1), (h - 1) / 2, (h - 1) / 2)
        p.end()


class Swatch(QAbstractButton):
    def __init__(self, hex_code: str, name: str, parent=None):
        super().__init__(parent)
        self.hex = hex_code
        self.setCheckable(True)
        self.setFixedSize(30, 30)
        self.setToolTip(f"{name}  {hex_code}")
        self.setCursor(Qt.CursorShape.PointingHandCursor)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        if self.isChecked():
            p.setPen(QPen(QColor(255, 255, 255, 230), 2.0))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(1.0, 1.0, 28.0, 28.0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor(self.hex))
        inset = 5.0 if self.isChecked() else 3.0
        p.drawEllipse(QRectF(inset, inset, 30 - 2 * inset, 30 - 2 * inset))
        p.end()


class LevelMeter(QWidget):
    """Smoothed dBFS level bar with peak hold."""

    def __init__(self, accent: str = "#ffbdd4", parent=None):
        super().__init__(parent)
        self.setFixedHeight(14)
        self.setMinimumWidth(120)
        self._accent = QColor(accent)
        self._target = 0.0
        self._level = 0.0
        self._peak = 0.0
        self._peak_t = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(16)
        self._timer.timeout.connect(self._tick)

    def set_accent(self, hex_code: str):
        self._accent = QColor(hex_code)
        self.update()

    def set_rms(self, rms: float):
        db = 20.0 * math.log10(max(rms, 1e-6))
        self._target = max(0.0, min(1.0, (db + 66.0) / 56.0))   # -66 dBFS .. -10 dBFS

    def start(self):
        self._timer.start()

    def stop(self):
        self._timer.stop()
        self._target = self._level = self._peak = 0.0
        self.update()

    def _tick(self):
        self._level += (self._target - self._level) * (0.5 if self._target > self._level else 0.12)
        now = time.perf_counter()
        if self._level >= self._peak:
            self._peak, self._peak_t = self._level, now
        elif now - self._peak_t > 0.6:
            self._peak = max(self._level, self._peak - 0.01)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = float(self.width()), float(self.height())
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QColor("#0E1018"))
        p.drawRoundedRect(QRectF(0, 0, w, h), h / 2, h / 2)
        fw = max(0.0, w * self._level)
        if fw > 1:
            g = QLinearGradient(0, 0, w, 0)
            g.setColorAt(0.0, QColor(SUCCESS))
            g.setColorAt(0.7, self._accent)
            g.setColorAt(1.0, QColor(DANGER))
            p.setBrush(g)
            p.drawRoundedRect(QRectF(0, 0, max(h, fw), h), h / 2, h / 2)
        if self._peak > 0.02:
            p.setBrush(QColor(255, 255, 255, 190))
            p.drawRoundedRect(QRectF(min(w - 3, w * self._peak - 1.5), 2, 3, h - 4), 1.5, 1.5)
        p.end()


class PillPreview(QWidget):
    """Live preview that mirrors the real HUD capsule (same geometry, rim and bar layout)."""

    def __init__(self, accent: str = "#ffbdd4", parent=None):
        super().__init__(parent)
        self.accent = QColor(accent)
        self.setFixedHeight(104)
        self._t0 = time.perf_counter()
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self.update)
        self._timer.start()

    def set_accent(self, hex_code: str):
        self.accent = QColor(hex_code)
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        bg = QLinearGradient(0, 0, w, h)
        bg.setColorAt(0.0, QColor("#232842"))
        bg.setColorAt(1.0, QColor("#161A2B"))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(bg)
        p.drawRoundedRect(QRectF(0, 0, w, h), 10, 10)

        dpr = self.devicePixelRatioF()
        p.save()
        p.scale(1.0 / dpr, 1.0 / dpr)
        W, H = w * dpr, h * dpr
        pw = 2 * round(184 * dpr / 2)
        ph = 2 * round(36 * dpr / 2)
        left, top = round((W - pw) / 2), round((H - ph) / 2)
        r = ph / 2.0
        path = QPainterPath()
        path.addRoundedRect(QRectF(left, top, pw, ph), r, r)
        p.setBrush(QColor(12, 12, 14, 246))
        p.drawPath(path)
        rim = QPainterPath()
        rim.addRoundedRect(QRectF(left + 0.5, top + 0.5, pw - 1, ph - 1), r - 0.5, r - 0.5)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 34), 1.0))
        p.drawPath(rim)

        n, bar_w, gap = 28, max(1.0, round(2.4 * dpr)), max(1.0, round(2.8 * dpr))
        x0 = round(W / 2 - (n * bar_w + (n - 1) * gap) / 2)
        cy = top + ph / 2.0
        t = time.perf_counter() - self._t0
        p.setPen(Qt.PenStyle.NoPen)
        for i in range(n):
            d = (i - (n - 1) / 2) / ((n - 1) / 2)
            env = math.exp(-(d / 0.78) ** 2)
            v = max(0.0, 0.5 + 0.5 * math.sin(t * 5.0 - abs(d) * 4.2 + i * 0.35)) * (0.25 + 0.75 * env)
            hh = 2 * round((3.0 + 14.0 * v * (0.55 + 0.45 * math.sin(t * 1.7) ** 2)) * dpr / 2)
            col = QColor(self.accent)
            col.setAlphaF(0.45 + 0.55 * v)
            p.setBrush(col)
            p.drawRoundedRect(QRectF(x0 + i * (bar_w + gap), round(cy - hh / 2), bar_w, hh), bar_w / 2, bar_w / 2)
        p.restore()
        p.end()


class _Worker(QThread):
    done = pyqtSignal(object)

    def __init__(self, fn: Callable, parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self):
        try:
            self.done.emit(("ok", self._fn()))
        except Exception as e:
            self.done.emit(("err", e))


# ---------------------------------------------------------------------------- layout helpers
def _label(text: str, name: str, wrap: bool = False) -> QLabel:
    lbl = QLabel(text)
    lbl.setObjectName(name)
    lbl.setWordWrap(wrap)
    return lbl


class Card(QFrame):
    def __init__(self, title: str):
        super().__init__()
        self.setObjectName("Card")
        self._lay = QVBoxLayout(self)
        self._lay.setContentsMargins(20, 16, 20, 18)
        self._lay.setSpacing(14)
        self._lay.addWidget(_label(title.upper(), "CardTitle"))
        self._first = True

    def add_row(self, title: str, desc: str, control: QWidget, stack: bool = False) -> QWidget:
        if not self._first:
            sep = QFrame()
            sep.setObjectName("Sep")
            self._lay.addWidget(sep)
        self._first = False

        row = QWidget()
        text = QVBoxLayout()
        text.setSpacing(2)
        text.addWidget(_label(title, "RowTitle"))
        if desc:
            text.addWidget(_label(desc, "RowDesc", wrap=True))
        if stack:
            lay = QVBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(10)
            lay.addLayout(text)
            lay.addWidget(control)
        else:
            lay = QHBoxLayout(row)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(18)
            lay.addLayout(text, 1)
            lay.addWidget(control, 0, Qt.AlignmentFlag.AlignVCenter)
        self._lay.addWidget(row)
        return row

    def add_widget(self, w: QWidget):
        self._lay.addWidget(w)


def _page(title: str, desc: str) -> (QScrollArea, QVBoxLayout):
    scroll = QScrollArea()
    scroll.setWidgetResizable(True)
    scroll.setFrameShape(QFrame.Shape.NoFrame)
    body = QWidget()
    lay = QVBoxLayout(body)
    lay.setContentsMargins(32, 28, 28, 24)
    lay.setSpacing(16)
    lay.addWidget(_label(title, "PageTitle"))
    sub = _label(desc, "PageDesc", wrap=True)
    lay.addWidget(sub)
    lay.addSpacing(4)
    scroll.setWidget(body)
    return scroll, lay


# -------------------------------------------------------------------------------- window
class SettingsWindow(QWidget):
    def __init__(self, on_save_callback: Optional[Callable[[dict], None]] = None):
        super().__init__()
        self.setObjectName("Root")
        self.on_save_callback = on_save_callback
        self.config = load_config()
        self.accent = self.config["ui"]["accent_color"]
        self._dirty = False
        self._loading = True
        self._devices: List[InputDevice] = []
        self._test_stream = None
        self._test_rms = 0.0
        self._test_peak = 0.0
        self._test_started = 0.0
        self._workers: List[_Worker] = []

        self.setWindowTitle("Takt Preferences")
        self.resize(900, 680)
        self.setMinimumSize(760, 560)

        self._build_ui()
        self._load_values()
        self.setStyleSheet(build_qss(self.accent))

        self._meter_timer = QTimer(self)
        self._meter_timer.setInterval(30)
        self._meter_timer.timeout.connect(self._poll_mic_test)
        self._loading = False

    # ------------------------------------------------------------------ construction
    def _build_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        mid = QHBoxLayout()
        mid.setSpacing(0)
        outer.addLayout(mid, 1)

        # Sidebar
        side = QFrame()
        side.setObjectName("Sidebar")
        side.setFixedWidth(206)
        sl = QVBoxLayout(side)
        sl.setContentsMargins(14, 22, 14, 16)
        sl.setSpacing(4)
        sl.addWidget(_label("Takt", "Brand"))
        sl.addWidget(_label("Voice dictation for Windows", "BrandSub"))
        sl.addSpacing(18)

        self.stack = QStackedWidget()
        self.nav_group = QButtonGroup(self)
        self.nav_group.setExclusive(True)
        pages = [
            ("General", self._page_general),
            ("Audio", self._page_audio),
            ("Appearance", self._page_appearance),
            ("Text && AI", self._page_text),
            ("Privacy && Performance", self._page_privacy),
            ("About", self._page_about),
        ]
        for i, (name, builder) in enumerate(pages):
            btn = QPushButton(name)
            btn.setObjectName("Nav")
            btn.setCheckable(True)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.nav_group.addButton(btn, i)
            sl.addWidget(btn)
            self.stack.addWidget(builder())
        self.nav_group.button(0).setChecked(True)
        self.nav_group.idClicked.connect(self._on_nav)
        sl.addStretch(1)
        self.status_dot = _label("● Engine running", "BrandSub")
        self.status_dot.setStyleSheet(f"color: {SUCCESS};")
        sl.addWidget(self.status_dot)
        mid.addWidget(side)
        mid.addWidget(self.stack, 1)

        # Footer
        footer = QFrame()
        footer.setObjectName("Footer")
        fl = QHBoxLayout(footer)
        fl.setContentsMargins(24, 12, 24, 12)
        self.save_status = _label("", "RowDesc")
        fl.addWidget(self.save_status, 1)
        self.revert_btn = QPushButton("Revert")
        self.revert_btn.clicked.connect(self._revert)
        self.save_btn = QPushButton("Save changes")
        self.save_btn.setObjectName("Primary")
        self.save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_btn.setDefault(True)
        self.save_btn.clicked.connect(self._save_and_apply)
        fl.addWidget(self.revert_btn)
        fl.addWidget(self.save_btn)
        outer.addWidget(footer)

    def _on_nav(self, idx: int):
        self.stack.setCurrentIndex(idx)
        if idx != 1:
            self._stop_mic_test()
        if idx == 5:
            self._load_hardware_info()

    def _page_general(self) -> QWidget:
        page, lay = _page("General", "How you start and stop dictation.")
        card = Card("Activation")
        self.hotkey_combo = Combo()
        for key, label in HOTKEYS:
            self.hotkey_combo.addItem(label, key)
        self.hotkey_combo.setMinimumWidth(240)
        card.add_row("Dictation hotkey", "Hold this key anywhere in Windows and speak.", self.hotkey_combo)
        self.mode_combo = Combo()
        for key, label in MODES:
            self.mode_combo.addItem(label, key)
        self.mode_combo.setMinimumWidth(240)
        card.add_row("Activation mode", "Push-to-talk records while held; toggle starts and stops on each press.",
                     self.mode_combo)
        lay.addWidget(card)

        card2 = Card("Startup & interface")
        self.startup_switch = ToggleSwitch(accent=self.accent)
        card2.add_row("Start with Windows", "Launch silently into the system tray when you sign in.",
                      self.startup_switch)
        self.hud_switch = ToggleSwitch(accent=self.accent)
        card2.add_row("Show floating pill", "The small capsule that appears while you dictate.", self.hud_switch)
        lay.addWidget(card2)
        lay.addStretch(1)
        for w in (self.hotkey_combo, self.mode_combo):
            w.currentIndexChanged.connect(self._mark_dirty)
        for w in (self.startup_switch, self.hud_switch):
            w.toggled.connect(self._mark_dirty)
        return page

    def _page_audio(self) -> QWidget:
        page, lay = _page("Audio", "Choose the microphone Takt listens to and make sure it is actually picking you up.")
        card = Card("Input device")
        self.device_combo = Combo()
        self.device_combo.setMinimumWidth(320)
        self.device_combo.currentIndexChanged.connect(self._on_device_changed)
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        rl.addWidget(self.device_combo, 1)
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self._populate_devices)
        rl.addWidget(refresh)
        card.add_row("Microphone", "“System default” follows whatever Windows has selected. "
                                   "Takt automatically skips silent virtual devices.", row, stack=True)
        lay.addWidget(card)

        card2 = Card("Level test")
        self.meter = LevelMeter(self.accent)
        self.test_btn = QPushButton("Start test")
        self.test_btn.setMinimumWidth(110)
        self.test_btn.clicked.connect(self._toggle_mic_test)
        mrow = QWidget()
        ml = QHBoxLayout(mrow)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(12)
        ml.addWidget(self.test_btn)
        ml.addWidget(self.meter, 1)
        card2.add_widget(mrow)
        self.test_result = _label("Press “Start test”, then speak normally.", "RowDesc", wrap=True)
        card2.add_widget(self.test_result)
        lay.addWidget(card2)
        lay.addStretch(1)
        return page

    def _page_appearance(self) -> QWidget:
        page, lay = _page("Appearance", "Make the floating capsule yours.")
        card = Card("Live preview")
        self.preview = PillPreview(self.accent)
        card.add_widget(self.preview)
        lay.addWidget(card)

        card2 = Card("Accent colour")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        self.swatches: List[Swatch] = []
        group = QButtonGroup(self)
        group.setExclusive(True)
        for hex_code, name in PRESET_COLORS:
            sw = Swatch(hex_code, name)
            group.addButton(sw)
            sw.clicked.connect(lambda _=False, c=hex_code: self._set_accent(c))
            rl.addWidget(sw)
            self.swatches.append(sw)
        rl.addStretch(1)
        custom = QPushButton("Custom…")
        custom.clicked.connect(self._pick_custom_color)
        rl.addWidget(custom)
        card2.add_widget(row)
        lay.addWidget(card2)

        card3 = Card("Position & Taskbar")
        self.offset_combo = Combo()
        self.offset_combo.addItem("Default (24 px above taskbar)", 24)
        self.offset_combo.addItem("Slightly higher (36 px above taskbar)", 36)
        self.offset_combo.addItem("High (48 px above taskbar)", 48)
        self.offset_combo.addItem("Extra high (64 px above taskbar)", 64)
        self.offset_combo.addItem("Compact (14 px above taskbar)", 14)
        self.offset_combo.setMinimumWidth(260)
        self.offset_combo.currentIndexChanged.connect(self._mark_dirty)
        card3.add_row("Capsule elevation",
                      "Distance above the taskbar. Automatically elevates for auto-hidden taskbars "
                      "so the capsule is never covered when the taskbar appears.",
                      self.offset_combo)
        lay.addWidget(card3)
        lay.addStretch(1)
        return page

    def _page_text(self) -> QWidget:
        page, lay = _page("Text & AI", "How transcribed speech is cleaned up before it is typed.")
        card = Card("Formatting")
        self.fmt_combo = Combo()
        self.fmt_combo.addItem("Built-in rules  (instant, offline)", "lightweight")
        self.fmt_combo.addItem("Groq  (ultra-fast cloud, smart cleanup)", "smart_groq")
        self.fmt_combo.addItem("Anthropic Claude  (smart cleanup)", "smart_anthropic")
        self.fmt_combo.addItem("OpenAI  (smart cleanup)", "smart_openai")
        self.fmt_combo.addItem("Local LLM via Ollama  (smarter punctuation)", "ollama")
        self.fmt_combo.setMinimumWidth(300)
        self.fmt_combo.currentIndexChanged.connect(self._on_formatter_changed)
        card.add_row("Formatter", "Smart providers turn a rambling train of thought into clean text "
                                  "(fixing self-corrections, fillers and false starts). Short phrases and any "
                                  "network error fall back instantly to the built-in rules.",
                     self.fmt_combo)
        self.style_combo = Combo()
        self.style_combo.addItem("Smart Clean  (Wispr Flow style)", "clean")
        self.style_combo.addItem("Verbatim  (punctuation & caps only)", "verbatim")
        self.style_combo.addItem("Bullet points", "bullets")
        self.style_combo.setMinimumWidth(300)
        self.style_combo.currentIndexChanged.connect(self._mark_dirty)
        card.add_row("Style", "How the text is rewritten by Ollama and the smart providers.", self.style_combo)
        lay.addWidget(card)

        self.smart_card = Card("Smart formatter provider")
        self.smart_key = QLineEdit()
        self.smart_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.smart_key.setPlaceholderText("API key")
        self.smart_key.textChanged.connect(self._on_smart_field_changed)
        self.smart_card.add_row("API key", "Stored locally in your Takt config; sent only to the selected provider.",
                                self.smart_key, stack=True)
        self.smart_model = Combo()
        self.smart_model.setEditable(True)
        self.smart_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.smart_model.editTextChanged.connect(self._on_smart_field_changed)
        self.smart_card.add_row("Model", "Model name used for formatting.", self.smart_model, stack=True)
        lay.addWidget(self.smart_card)

        self.router_card = Card("Smart routing")
        self.router_combo = Combo()
        for label, data in ROUTERS:
            self.router_combo.addItem(label, data)
        self.router_combo.setMinimumWidth(300)
        self.router_combo.currentIndexChanged.connect(self._on_router_changed)
        self.router_card.add_row("Router", "Decides per dictation whether the cloud model is needed. Clean, "
                                           "direct sentences are formatted instantly without a network call.",
                                 self.router_combo)
        self.typesafe_key = QLineEdit()
        self.typesafe_key.setEchoMode(QLineEdit.EchoMode.Password)
        self.typesafe_key.setPlaceholderText("TypeSafe API key")
        self.typesafe_key.textChanged.connect(self._mark_dirty)
        self.router_card.add_row(
            "TypeSafe API key", "Used only by the Jev router. Without a key, or if the request fails, "
                                "Takt falls back to the fast heuristic router.",
            self.typesafe_key, stack=True)
        lay.addWidget(self.router_card)

        self.ollama_card = Card("Ollama")
        self.ollama_url = QLineEdit()
        self.ollama_url.setPlaceholderText("http://127.0.0.1:11434")
        self.ollama_url.textChanged.connect(self._mark_dirty)
        self.ollama_card.add_row("Endpoint", "Address of your local Ollama server.", self.ollama_url, stack=True)
        self.ollama_model = Combo()
        self.ollama_model.setEditable(True)
        self.ollama_model.setInsertPolicy(QComboBox.InsertPolicy.NoInsert)
        self.ollama_model.editTextChanged.connect(self._mark_dirty)
        mrow = QWidget()
        ml = QHBoxLayout(mrow)
        ml.setContentsMargins(0, 0, 0, 0)
        ml.setSpacing(8)
        ml.addWidget(self.ollama_model, 1)
        self.ollama_test_btn = QPushButton("Test && list models")
        self.ollama_test_btn.clicked.connect(self._test_ollama)
        ml.addWidget(self.ollama_test_btn)
        self.ollama_model_row = self.ollama_card.add_row(
            "Model", "Pick an installed model or type a name (small models such as qwen2.5:1.5b are fastest).",
            mrow, stack=True)
        self.ollama_status = _label("", "RowDesc", wrap=True)
        self.ollama_card.add_widget(self.ollama_status)
        lay.addWidget(self.ollama_card)
        lay.addStretch(1)
        return page

    def _page_privacy(self) -> QWidget:
        page, lay = _page("Privacy & Performance", "What Takt remembers and how it uses your machine.")
        card = Card("Privacy")
        self.redact_switch = ToggleSwitch(accent=self.accent)
        card.add_row("Redaction shield", "Mask credit cards, API keys, e-mails, phone numbers and SSNs before typing.",
                     self.redact_switch)
        self.keep_combo = Combo()
        for n, label in KEEP_RECORDINGS:
            self.keep_combo.addItem(label, n)
        self.keep_combo.setMinimumWidth(200)
        card.add_row("Voice recordings", "Recent dictations are kept locally as .wav files so you can review them.",
                     self.keep_combo)
        self.history_switch = ToggleSwitch(accent=self.accent)
        card.add_row("Dictation history", "Keep a text log of what was dictated.", self.history_switch)
        lay.addWidget(card)

        card2 = Card("Performance")
        self.ttl_combo = Combo()
        for secs, label in IDLE_SLEEP:
            self.ttl_combo.addItem(label, secs)
        self.ttl_combo.setMinimumWidth(240)
        card2.add_row("Free memory when idle", "Unloads the speech models after inactivity; they reload instantly "
                                               "when you press the hotkey.", self.ttl_combo)
        lay.addWidget(card2)
        lay.addStretch(1)
        for w in (self.keep_combo, self.ttl_combo):
            w.currentIndexChanged.connect(self._mark_dirty)
        for w in (self.redact_switch, self.history_switch):
            w.toggled.connect(self._mark_dirty)
        return page

    def _page_about(self) -> QWidget:
        page, lay = _page("About", f"Takt {APP_VERSION} — local, private voice dictation.")
        card = Card("This computer")
        self.hw_labels = {}
        for key, title in (("cpu", "Processor"), ("ram", "Memory"), ("gpu", "Graphics")):
            lbl = _label("Detecting…", "RowDesc")
            lbl.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
            self.hw_labels[key] = lbl
            card.add_row(title, "", lbl)
        lay.addWidget(card)

        card2 = Card("Files & updates")
        row = QWidget()
        rl = QHBoxLayout(row)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(8)
        for text, fn in (("Recordings", self._open_recordings), ("History", self._open_history),
                         ("Diagnostic log", self._open_log), ("Install update…", self._install_update_pkg)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            rl.addWidget(b)
        rl.addStretch(1)
        card2.add_widget(row)
        lay.addWidget(card2)

        card3 = Card("Position & Taskbar")
        self.offset_combo = Combo()
        self.offset_combo.addItem("Default (24 px above taskbar)", 24)
        self.offset_combo.addItem("Slightly higher (36 px above taskbar)", 36)
        self.offset_combo.addItem("High (48 px above taskbar)", 48)
        self.offset_combo.addItem("Extra high (64 px above taskbar)", 64)
        self.offset_combo.addItem("Compact (14 px above taskbar)", 14)
        self.offset_combo.setMinimumWidth(260)
        self.offset_combo.currentIndexChanged.connect(self._mark_dirty)
        card3.add_row("Capsule elevation",
                      "Distance above the taskbar. Automatically elevates for auto-hidden taskbars "
                      "so the capsule is never covered when the taskbar appears.",
                      self.offset_combo)
        lay.addWidget(card3)
        lay.addStretch(1)
        return page

    # --------------------------------------------------------------------- values
    def reload_from_disk(self):
        if self._dirty:
            return
        self.config = load_config()
        self._load_values()

    def _load_values(self):
        self._loading = True
        cfg = self.config
        self.accent = cfg["ui"]["accent_color"]

        self._select_data(self.hotkey_combo, cfg["hotkey"]["key"])
        self._select_data(self.mode_combo, cfg["hotkey"]["mode"])
        self.startup_switch.set_checked_instant(self._is_startup_enabled())
        self.hud_switch.set_checked_instant(bool(cfg["ui"]["hud_enabled"]))
        offset = int(cfg.get("ui", {}).get("bottom_offset", 24))
        if self.offset_combo.findData(offset) < 0:
            self.offset_combo.addItem(f"Custom ({offset} px)", offset)
        self._select_data(self.offset_combo, offset)
        self.redact_switch.set_checked_instant(bool(cfg["privacy_shield"]["enabled"]))
        self.history_switch.set_checked_instant(bool(cfg["logging"]["enabled"]))
        keep = int(cfg["logging"]["max_audio_recordings"]) if cfg["logging"]["save_audio_recordings"] else 0
        if self.keep_combo.findData(keep) < 0:
            self.keep_combo.addItem(f"Keep last {keep}", keep)
        self._select_data(self.keep_combo, keep)
        ttl = int(cfg["performance"]["idle_eviction_ttl_sec"])
        if self.ttl_combo.findData(ttl) < 0:
            self.ttl_combo.addItem(f"After {ttl} seconds", ttl)
        self._select_data(self.ttl_combo, ttl)

        fmt = cfg["models"]["formatter"]
        self._smart_vals = {
            m: {"key": fmt.get(f"{p}_api_key", ""), "model": fmt.get(f"{p}_model", "")}
            for m, p in self._SMART_PREFIX.items()
        }
        self._select_data(self.fmt_combo, fmt["mode"])
        self.ollama_url.setText(fmt["ollama_endpoint"])
        self.ollama_model.setEditText(fmt["ollama_model"])
        self.ollama_card.setVisible(fmt["mode"] == "ollama")
        self._select_data(self.style_combo, fmt.get("style", "clean"))
        self._select_data(self.router_combo, fmt.get("router", "heuristic"))
        self.typesafe_key.setText(fmt.get("typesafe_api_key", ""))
        self.typesafe_key.setEnabled(self.router_combo.currentData() == "jev")
        self._smart_active = None
        self._refresh_smart_card()

        self._populate_devices()
        self._apply_accent(self.accent, mark=False)
        self._set_dirty(False)
        self._loading = False

    @staticmethod
    def _select_data(combo: QComboBox, data):
        idx = combo.findData(data)
        combo.setCurrentIndex(idx if idx >= 0 else 0)

    def _mark_dirty(self, *_):
        if not self._loading:
            self._set_dirty(True)

    def _set_dirty(self, dirty: bool):
        self._dirty = dirty
        self.save_btn.setEnabled(dirty)
        self.revert_btn.setEnabled(dirty)
        self.save_status.setText("You have unsaved changes" if dirty else "")
        self.save_status.setStyleSheet(f"color: {WARN};" if dirty else "")

    def _revert(self):
        self._dirty = False
        self.config = load_config()
        self._load_values()

    # ------------------------------------------------------------------- appearance
    def _apply_accent(self, hex_code: str, mark: bool = True):
        self.accent = hex_code
        self.setStyleSheet(build_qss(hex_code))
        self.preview.set_accent(hex_code)
        self.meter.set_accent(hex_code)
        for sw in (self.startup_switch, self.hud_switch, self.redact_switch, self.history_switch):
            sw.set_accent(hex_code)
        matched = False
        for sw in self.swatches:
            on = sw.hex.lower() == hex_code.lower()
            sw.setChecked(on)
            matched |= on
            sw.update()
        if not matched:
            for sw in self.swatches:
                sw.setChecked(False)
        if mark:
            self._mark_dirty()

    def _set_accent(self, hex_code: str):
        self._apply_accent(hex_code)

    def _pick_custom_color(self):
        col = QColorDialog.getColor(QColor(self.accent), self, "Accent colour")
        if col.isValid():
            self._apply_accent(col.name())

    # ------------------------------------------------------------------------ audio
    def _populate_devices(self):
        was_loading = self._loading
        self._loading = True
        self._stop_mic_test()
        self.device_combo.clear()
        self._devices = list_input_devices()
        default = next((d for d in self._devices if d.is_default), None)
        label = f"System default  ({default.name})" if default else "System default"
        self.device_combo.addItem(label, None)
        for d in self._devices:
            self.device_combo.addItem(d.name, d.name)

        spec = self.config["audio"].get("device")
        if isinstance(spec, int):           # legacy index -> device name
            try:
                spec = " ".join(str(sd.query_devices(spec)["name"]).split())
            except Exception:
                spec = None
        if spec:
            idx = next((i for i in range(1, self.device_combo.count())
                        if str(self.device_combo.itemData(i)).lower().startswith(str(spec).lower()[:28])), -1)
            if idx < 0:
                self.device_combo.addItem(f"{spec}  (not connected)", spec)
                idx = self.device_combo.count() - 1
            self.device_combo.setCurrentIndex(idx)
        else:
            self.device_combo.setCurrentIndex(0)
        self._loading = was_loading

    def _on_device_changed(self, *_):
        self._mark_dirty()
        if self._test_stream is not None:
            self._stop_mic_test()

    def _selected_device(self) -> Optional[InputDevice]:
        name = self.device_combo.currentData()
        if name is None:
            return next((d for d in self._devices if d.is_default), self._devices[0] if self._devices else None)
        return next((d for d in self._devices if str(name).lower().startswith(d.name.lower()[:28])), None)

    def _toggle_mic_test(self):
        if self._test_stream is not None:
            self._stop_mic_test()
        else:
            self._start_mic_test()

    def _start_mic_test(self):
        dev = self._selected_device()
        if dev is None:
            self.test_result.setText("No microphone found. Plug one in, then press Refresh.")
            return

        def callback(indata, frames, t, status):
            mono = indata.mean(axis=1) if indata.ndim > 1 else indata
            self._test_rms = float(np.sqrt(np.mean(mono * mono)))
            self._test_peak = max(self._test_peak, float(np.max(np.abs(mono))))

        extra = None
        if dev.hostapi == "Windows WASAPI":
            try:
                extra = sd.WasapiSettings(auto_convert=True)
            except Exception:
                extra = None
        stream, err = None, None
        for sr in (dev.default_samplerate, 48000.0):
            for ex in ([extra, None] if extra is not None else [None]):
                try:
                    stream = sd.InputStream(device=dev.index, channels=1, samplerate=sr, dtype="float32",
                                            blocksize=int(sr * 0.03), callback=callback, extra_settings=ex)
                    stream.start()
                    break
                except Exception as e:
                    stream, err = None, e
            if stream:
                break
        if stream is None:
            QMessageBox.warning(self, "Microphone", f"Could not open “{dev.name}”:\n{err}")
            return

        self._test_stream = stream
        self._test_peak = self._test_rms = 0.0
        self._test_started = time.perf_counter()
        self.test_btn.setText("Stop test")
        self.test_result.setText(f"Listening on {dev.name} … speak now.")
        self.test_result.setStyleSheet(f"color: {MUTED};")
        self.meter.start()
        self._meter_timer.start()

    def _stop_mic_test(self):
        if getattr(self, "_meter_timer", None):
            self._meter_timer.stop()
        if self._test_stream is not None:
            try:
                self._test_stream.abort()
                self._test_stream.close()
            except Exception:
                pass
            self._test_stream = None
        if hasattr(self, "meter"):
            self.meter.stop()
            self.test_btn.setText("Start test")

    def _poll_mic_test(self):
        self.meter.set_rms(self._test_rms)
        elapsed = time.perf_counter() - self._test_started
        if elapsed > 1.5:
            if self._test_peak < DEAD_PEAK_THRESHOLD:
                self.test_result.setText("No signal at all — this device is silent. It may be a virtual microphone "
                                         "with nothing connected, a Bluetooth headset that isn't in call mode, or "
                                         "muted in Windows. Try another device.")
                self.test_result.setStyleSheet(f"color: {DANGER};")
            elif self._test_peak < 0.02:
                self.test_result.setText("Signal detected but very quiet. Takt will boost it automatically; "
                                         "raising the input volume in Windows gives better accuracy.")
                self.test_result.setStyleSheet(f"color: {WARN};")
            else:
                self.test_result.setText("Microphone is working.")
                self.test_result.setStyleSheet(f"color: {SUCCESS};")

    # ----------------------------------------------------------------------- Ollama
    _SMART_PREFIX = {"smart_groq": "groq", "smart_anthropic": "anthropic", "smart_openai": "openai"}

    def _on_formatter_changed(self, *_):
        self.ollama_card.setVisible(self.fmt_combo.currentData() == "ollama")
        self._refresh_smart_card()
        self._mark_dirty()

    def _refresh_smart_card(self):
        """Shows the key/model fields for the selected smart provider (values are kept per provider)."""
        mode = self.fmt_combo.currentData()
        self.smart_card.setVisible(mode in self._SMART_PREFIX)
        self._smart_active = mode if mode in self._SMART_PREFIX else None
        if self._smart_active is None:
            return
        vals = self._smart_vals[mode]
        was = self._loading
        self._loading = True
        self.smart_key.setText(vals["key"])
        self.smart_model.clear()
        if mode == "smart_groq":
            for label, name in GROQ_MODELS:
                self.smart_model.addItem(label, name)
            idx = self.smart_model.findData(vals["model"])
            if idx >= 0:
                self.smart_model.setCurrentIndex(idx)
            else:
                self.smart_model.setEditText(vals["model"])
        else:
            self.smart_model.setEditText(vals["model"])
        self._loading = was

    def _smart_model_name(self) -> str:
        text = self.smart_model.currentText().strip()
        idx = self.smart_model.findText(text)
        data = self.smart_model.itemData(idx) if idx >= 0 else None
        return data or text

    def _on_router_changed(self, *_):
        self.typesafe_key.setEnabled(self.router_combo.currentData() == "jev")
        self._mark_dirty()

    def _on_smart_field_changed(self, *_):
        if self._loading:
            return
        if self._smart_active:
            self._smart_vals[self._smart_active] = {
                "key": self.smart_key.text().strip(), "model": self._smart_model_name()}
        self._mark_dirty()

    def _test_ollama(self):
        endpoint = self.ollama_url.text().strip() or DEFAULT_CONFIG["models"]["formatter"]["ollama_endpoint"]
        self.ollama_test_btn.setEnabled(False)
        self.ollama_status.setText("Contacting Ollama…")
        self.ollama_status.setStyleSheet(f"color: {MUTED};")
        worker = _Worker(lambda: list_ollama_models(endpoint), self)
        worker.done.connect(self._on_ollama_result)
        worker.finished.connect(lambda w=worker: self._workers.remove(w) if w in self._workers else None)
        self._workers.append(worker)
        worker.start()

    def _on_ollama_result(self, result):
        self.ollama_test_btn.setEnabled(True)
        kind, payload = result
        if kind == "err":
            self.ollama_status.setText(f"Couldn't reach Ollama ({type(payload).__name__}). "
                                       f"Is it running? Takt will use the built-in rules until it is.")
            self.ollama_status.setStyleSheet(f"color: {DANGER};")
            return
        current = self.ollama_model.currentText()
        self._loading = True
        self.ollama_model.clear()
        self.ollama_model.addItems(payload)
        self.ollama_model.setEditText(current)
        self._loading = False
        if payload:
            self.ollama_status.setText(f"Connected — {len(payload)} model(s) installed.")
            self.ollama_status.setStyleSheet(f"color: {SUCCESS};")
        else:
            self.ollama_status.setText("Connected, but no models are installed. Run “ollama pull qwen2.5:1.5b”.")
            self.ollama_status.setStyleSheet(f"color: {WARN};")

    # ---------------------------------------------------------------------- system
    def _load_hardware_info(self):
        if getattr(self, "_hw_loaded", False):
            return
        self._hw_loaded = True

        def probe():
            info = {"cpu": platform.processor() or "Unknown", "ram": "Unknown", "gpu": "Unknown"}
            try:
                info["cpu"] = f"{info['cpu']}  ({psutil.cpu_count(logical=False)} cores / {psutil.cpu_count()} threads)"
                info["ram"] = f"{psutil.virtual_memory().total / 1024 ** 3:.1f} GB"
            except Exception:
                pass
            try:
                out = subprocess.run(
                    ["powershell", "-NoProfile", "-Command", "(Get-CimInstance Win32_VideoController).Name -join '; '"],
                    capture_output=True, text=True, timeout=6, creationflags=0x08000000)
                if out.stdout.strip():
                    info["gpu"] = out.stdout.strip()
            except Exception:
                pass
            return info

        w = _Worker(probe, self)
        w.done.connect(lambda r: [self.hw_labels[k].setText(v) for k, v in r[1].items()] if r[0] == "ok" else None)
        w.finished.connect(lambda ww=w: self._workers.remove(ww) if ww in self._workers else None)
        self._workers.append(w)
        w.start()

    def _is_startup_enabled(self) -> bool:
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_READ) as key:
                return bool(winreg.QueryValueEx(key, APP_NAME)[0])
        except OSError:
            return False

    def _set_startup_enabled(self, enabled: bool):
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, REG_KEY, 0, winreg.KEY_SET_VALUE) as key:
                if enabled:
                    if getattr(sys, "frozen", False):
                        cmd = f'"{sys.executable}"'
                    else:
                        pythonw = os.path.join(os.path.dirname(sys.executable), "pythonw.exe")
                        cmd = f'"{pythonw}" "{os.path.join(app_dir(), "src", "main.py")}"'
                    winreg.SetValueEx(key, APP_NAME, 0, winreg.REG_SZ, cmd)
                else:
                    try:
                        winreg.DeleteValue(key, APP_NAME)
                    except OSError:
                        pass
        except Exception as e:
            print(f"[Settings] Failed to update Windows startup entry: {e}")

    def _install_update_pkg(self):
        zip_path, _ = QFileDialog.getOpenFileName(self, "Select Takt update package", "", "Zip files (*.zip);;All files (*.*)")
        if not zip_path:
            return
        candidates = [os.path.join(app_dir(), "TaktUpdate.exe"),
                      os.path.join(app_dir(), "dist", "Takt", "TaktUpdate.exe")]
        updater = next((c for c in candidates if os.path.exists(c)), None)
        if not updater:
            QMessageBox.warning(self, "Updater not found",
                                "TaktUpdate.exe was not found. Extract the update package manually.")
            return
        try:
            subprocess.Popen([updater, zip_path])
            self.close()
        except Exception as e:
            QMessageBox.critical(self, "Update error", f"Failed to launch updater:\n{e}")

    @staticmethod
    def _open_path(path: str, make_dir: bool = False):
        if make_dir:
            os.makedirs(path, exist_ok=True)
        if os.path.exists(path):
            os.startfile(path)

    def _open_recordings(self):
        self._open_path(os.path.join(app_dir(), "logs", "recordings"), make_dir=True)

    def _open_history(self):
        self._open_path(os.path.join(app_dir(), "logs", "dictation_history.log"))

    def _open_log(self):
        self._open_path(os.path.join(app_dir(), "logs", "takt.log"))

    # ------------------------------------------------------------------------ save
    def _save_and_apply(self):
        endpoint = self.ollama_url.text().strip()
        if self.fmt_combo.currentData() == "ollama" and not endpoint.lower().startswith(("http://", "https://")):
            QMessageBox.warning(self, "Ollama endpoint", "The Ollama endpoint must start with http:// or https://")
            self.stack.setCurrentIndex(3)
            return

        cfg = copy.deepcopy(self.config)
        cfg["hotkey"]["key"] = self.hotkey_combo.currentData()
        cfg["hotkey"]["mode"] = self.mode_combo.currentData()
        cfg["audio"]["device"] = self.device_combo.currentData()
        cfg["ui"]["accent_color"] = self.accent
        cfg["ui"]["hud_enabled"] = self.hud_switch.isChecked()
        cfg["ui"]["bottom_offset"] = int(self.offset_combo.currentData())
        cfg["privacy_shield"]["enabled"] = self.redact_switch.isChecked()
        cfg["logging"]["enabled"] = self.history_switch.isChecked()
        keep = int(self.keep_combo.currentData())
        cfg["logging"]["save_audio_recordings"] = keep > 0
        if keep > 0:
            cfg["logging"]["max_audio_recordings"] = keep
        cfg["performance"]["idle_eviction_ttl_sec"] = int(self.ttl_combo.currentData())
        fmt = cfg["models"]["formatter"]
        fmt["mode"] = self.fmt_combo.currentData()
        fmt["ollama_endpoint"] = endpoint or DEFAULT_CONFIG["models"]["formatter"]["ollama_endpoint"]
        fmt["ollama_model"] = self.ollama_model.currentText().strip() or DEFAULT_CONFIG["models"]["formatter"]["ollama_model"]
        fmt["style"] = self.style_combo.currentData()
        fmt["router"] = self.router_combo.currentData()
        fmt["typesafe_api_key"] = self.typesafe_key.text().strip()
        for m, p in self._SMART_PREFIX.items():
            fmt[f"{p}_api_key"] = self._smart_vals[m]["key"]
            fmt[f"{p}_model"] = self._smart_vals[m]["model"] or DEFAULT_CONFIG["models"]["formatter"][f"{p}_model"]

        try:
            save_config(cfg)
        except Exception as e:
            QMessageBox.critical(self, "Couldn't save", f"Preferences could not be written:\n{e}")
            return
        self._set_startup_enabled(self.startup_switch.isChecked())
        self.config = cfg
        self._set_dirty(False)

        if self.on_save_callback:
            try:
                self.on_save_callback(copy.deepcopy(cfg))
            except Exception as e:
                print(f"[Settings] Apply callback failed: {e}")

        self.save_status.setText("✓ Saved and applied")
        self.save_status.setStyleSheet(f"color: {SUCCESS}; font-weight: 600;")
        QTimer.singleShot(2500, lambda: self.save_status.setText("") if not self._dirty else None)

    # ------------------------------------------------------------------- lifecycle
    def closeEvent(self, event):
        if self._dirty:
            box = QMessageBox(self)
            box.setWindowTitle("Unsaved changes")
            box.setText("Save your changes before closing?")
            box.setStandardButtons(QMessageBox.StandardButton.Save | QMessageBox.StandardButton.Discard
                                   | QMessageBox.StandardButton.Cancel)
            choice = int(box.exec())
            if choice == QMessageBox.StandardButton.Cancel.value:
                event.ignore()
                return
            if choice == QMessageBox.StandardButton.Save.value:
                self._save_and_apply()
                if self._dirty:
                    event.ignore()
                    return
            else:
                self._revert()
        self._stop_mic_test()
        super().closeEvent(event)

    def hideEvent(self, event):
        self._stop_mic_test()
        super().hideEvent(event)


if __name__ == "__main__":
    from PyQt6.QtWidgets import QApplication
    _app = QApplication(sys.argv)
    _win = SettingsWindow()
    _win.show()
    sys.exit(_app.exec())
