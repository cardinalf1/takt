"""
Takt System Tray Companion (Modern PyQt6 Edition)
Runs silently in the Windows taskbar notification area.
- Vector icon dynamically tinted with the user's accent color (#ffbdd4)
- Double-click tray icon: Opens the full Settings & Preferences GUI
- Context menu: Settings, Updates, Recordings, Logs, and Clean Exit
- Memory footprint: Under 1MB shared inside the main Qt event loop
"""

import os
import sys
from typing import Optional, Callable

from PyQt6.QtWidgets import QSystemTrayIcon, QMenu, QApplication
from PyQt6.QtGui import QIcon, QPixmap, QPainter, QColor, QFont, QPen, QBrush
from PyQt6.QtCore import Qt

from src.core.config import app_dir

class TaktTray:
    def __init__(
        self,
        accent_color: str = "#ffbdd4",
        on_open_settings: Optional[Callable[[], None]] = None,
        on_exit: Optional[Callable[[], None]] = None
    ):
        self.accent_color = accent_color
        self.on_open_settings = on_open_settings
        self.on_exit = on_exit
        self.tray_icon: Optional[QSystemTrayIcon] = None
        self._init_tray()

    def _generate_icon(self, hex_color: str) -> QIcon:
        """Generates a high-DPI 64x64 vector pill icon tinted with the accent color."""
        pixmap = QPixmap(64, 64)
        pixmap.fill(Qt.GlobalColor.transparent)
        
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        
        # Outer dark ring
        painter.setBrush(QBrush(QColor(13, 14, 18)))
        painter.setPen(QPen(QColor(38, 40, 51), 2.0))
        painter.drawRoundedRect(4, 4, 56, 56, 16, 16)
        
        # Inner accent glyph (Stylized 'T' with sound wave dots)
        accent = QColor(hex_color)
        painter.setPen(QPen(accent, 4.0, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
        # Top crossbar
        painter.drawLine(18, 22, 46, 22)
        # Vertical stem
        painter.drawLine(32, 22, 32, 44)

        # Subtle equalizer dots
        painter.setPen(Qt.PenStyle.NoPen)
        painter.setBrush(QBrush(accent))
        painter.drawEllipse(18, 32, 4, 4)
        painter.drawEllipse(42, 32, 4, 4)

        painter.end()
        return QIcon(pixmap)

    def _init_tray(self):
        app = QApplication.instance()
        if not app:
            return

        self.tray_icon = QSystemTrayIcon()
        self.tray_icon.setIcon(self._generate_icon(self.accent_color))
        self.tray_icon.setToolTip("Takt - Voice Dictation (Click for Settings)")

        # Context Menu
        menu = QMenu()
        menu.setStyleSheet("""
            QMenu {
                background-color: #121318;
                border: 1px solid #272A38;
                border-radius: 8px;
                padding: 6px;
                color: #E4E4E7;
                font-family: 'Segoe UI Variable Display', 'Segoe UI', sans-serif;
                font-size: 12px;
            }
            QMenu::item {
                padding: 6px 20px;
                border-radius: 4px;
            }
            QMenu::item:selected {
                background-color: #1F212D;
                color: #FFFFFF;
            }
            QMenu::separator {
                height: 1px;
                background-color: #272A38;
                margin: 4px 6px;
            }
        """)

        act_settings = menu.addAction("⚙️ Preferences & Settings...")
        act_settings.setFont(QFont("Segoe UI Variable Display", 9, QFont.Weight.DemiBold))
        act_settings.triggered.connect(self._handle_open_settings)

        act_update = menu.addAction("🔄 Check for Updates...")
        act_update.triggered.connect(self._handle_open_settings)

        menu.addSeparator()

        act_rec = menu.addAction("📁 Voice Recordings (.wav)...")
        act_rec.triggered.connect(self._open_recordings)

        act_log = menu.addAction("📝 Dictation History Log...")
        act_log.triggered.connect(self._open_log)

        menu.addSeparator()

        act_exit = menu.addAction("❌ Quit Takt")
        act_exit.triggered.connect(self._handle_exit)

        self.tray_icon.setContextMenu(menu)
        
        # Double-click or single-click activation
        self.tray_icon.activated.connect(self._on_tray_activated)

    def _on_tray_activated(self, reason):
        # Single left click on the tray icon opens Preferences (a double-click fires Trigger first)
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._handle_open_settings()

    def _handle_open_settings(self):
        if self.on_open_settings:
            self.on_open_settings()

    def _handle_exit(self):
        if self.on_exit:
            self.on_exit()

    def _open_recordings(self):
        rec_dir = os.path.join(app_dir(), "logs", "recordings")
        os.makedirs(rec_dir, exist_ok=True)
        os.startfile(rec_dir)

    def _open_log(self):
        log_file = os.path.join(app_dir(), "logs", "dictation_history.log")
        if os.path.exists(log_file):
            os.startfile(log_file)

    def show(self):
        if self.tray_icon:
            self.tray_icon.show()

    def hide(self):
        if self.tray_icon:
            self.tray_icon.hide()

    def set_accent_color(self, hex_color: str):
        self.accent_color = hex_color
        if self.tray_icon:
            self.tray_icon.setIcon(self._generate_icon(hex_color))
