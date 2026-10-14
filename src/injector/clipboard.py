import ctypes
from ctypes import wintypes
import threading
import time
from typing import Optional
from .keystroke import send_ctrl_v, send_unicode_string

CF_UNICODETEXT = 13
GMEM_MOVEABLE = 0x0002

# Explicit 64-bit Win32 prototypes to prevent pointer truncation
ctypes.windll.kernel32.GlobalLock.restype = ctypes.c_void_p
ctypes.windll.kernel32.GlobalLock.argtypes = [ctypes.c_void_p]

ctypes.windll.kernel32.GlobalUnlock.restype = wintypes.BOOL
ctypes.windll.kernel32.GlobalUnlock.argtypes = [ctypes.c_void_p]

ctypes.windll.kernel32.GlobalAlloc.restype = ctypes.c_void_p
ctypes.windll.kernel32.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]

ctypes.windll.kernel32.GlobalFree.restype = ctypes.c_void_p
ctypes.windll.kernel32.GlobalFree.argtypes = [ctypes.c_void_p]

ctypes.windll.user32.GetClipboardData.restype = ctypes.c_void_p
ctypes.windll.user32.GetClipboardData.argtypes = [wintypes.UINT]

ctypes.windll.user32.SetClipboardData.restype = ctypes.c_void_p
ctypes.windll.user32.SetClipboardData.argtypes = [wintypes.UINT, ctypes.c_void_p]

ctypes.windll.user32.OpenClipboard.restype = wintypes.BOOL
ctypes.windll.user32.OpenClipboard.argtypes = [ctypes.c_void_p]

ctypes.windll.user32.CloseClipboard.restype = wintypes.BOOL
ctypes.windll.user32.CloseClipboard.argtypes = []

class ClipboardInjector:
    """
    Safely injects text into the active cursor.
    Uses atomic direct Unicode SendInput by default (zero clipboard pollution, zero race conditions).
    Supports high-speed clipboard injection for long text buffers with safe restoration.
    """
    def __init__(self, method: str = "direct_unicode", restore_delay_ms: int = 1500):
        self.method = method
        self.restore_delay_sec = restore_delay_ms / 1000.0

    def _get_clipboard_text(self) -> Optional[str]:
        for _ in range(5):
            if ctypes.windll.user32.OpenClipboard(0):
                try:
                    h_data = ctypes.windll.user32.GetClipboardData(CF_UNICODETEXT)
                    if not h_data:
                        return None
                    p_data = ctypes.windll.kernel32.GlobalLock(h_data)
                    if not p_data:
                        return None
                    text = ctypes.wstring_at(p_data)
                    ctypes.windll.kernel32.GlobalUnlock(h_data)
                    return text
                finally:
                    ctypes.windll.user32.CloseClipboard()
            time.sleep(0.01)
        return None

    def _set_clipboard_text(self, text: str) -> bool:
        for _ in range(5):
            if ctypes.windll.user32.OpenClipboard(0):
                try:
                    ctypes.windll.user32.EmptyClipboard()
                    encoded = text.encode("utf-16le") + b"\x00\x00"
                    h_glob = ctypes.windll.kernel32.GlobalAlloc(GMEM_MOVEABLE, len(encoded))
                    if not h_glob:
                        return False
                    p_glob = ctypes.windll.kernel32.GlobalLock(h_glob)
                    if not p_glob:
                        ctypes.windll.kernel32.GlobalFree(h_glob)
                        return False
                    ctypes.memmove(p_glob, encoded, len(encoded))
                    ctypes.windll.kernel32.GlobalUnlock(h_glob)
                    ctypes.windll.user32.SetClipboardData(CF_UNICODETEXT, h_glob)
                    return True
                finally:
                    ctypes.windll.user32.CloseClipboard()
            time.sleep(0.01)
        return False

    def inject_text(self, text: str):
        if not text:
            return

        # For standard text, atomic direct Unicode SendInput is 100% reliable
        # and NEVER causes clipboard race conditions or terminal pastes.
        if self.method == "direct_unicode" or len(text) < 400:
            send_unicode_string(text)
            return

        # Clipboard path for large text blocks (>400 chars)
        original_clipboard = self._get_clipboard_text()
        success = self._set_clipboard_text(text)

        if success:
            send_ctrl_v()
            def _restore():
                time.sleep(self.restore_delay_sec)
                if original_clipboard is not None:
                    self._set_clipboard_text(original_clipboard)
            threading.Thread(target=_restore, daemon=True).start()
        else:
            send_unicode_string(text)
