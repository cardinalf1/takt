import ctypes
from ctypes import wintypes
import time

# Win32 SendInput constants
INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002
KEYEVENTF_UNICODE = 0x0004
KEYEVENTF_SCANCODE = 0x0008

VK_CONTROL = 0x11
VK_V = 0x56
VK_RETURN = 0x0D
VK_UNASSIGNED = 0xE8  # Unassigned virtual key: used to cancel Alt-tap menu activation

# SendInput is chunked so a very long dictation never exceeds the per-call input queue limits.
CHUNK_CHARS = 200


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", wintypes.WORD),
        ("wScan", wintypes.WORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t)
    ]

class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [
        ("uMsg", wintypes.DWORD),
        ("wParamL", wintypes.WORD),
        ("wParamH", wintypes.WORD)
    ]

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [
        ("dx", wintypes.LONG),
        ("dy", wintypes.LONG),
        ("mouseData", wintypes.DWORD),
        ("dwFlags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t)
    ]

class _INPUT_UNION(ctypes.Union):
    _fields_ = [
        ("mi", MOUSEINPUT),
        ("ki", KEYBDINPUT),
        ("hi", HARDWAREINPUT)
    ]

class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", wintypes.DWORD),
        ("union", _INPUT_UNION)
    ]

_user32 = ctypes.WinDLL("user32", use_last_error=True)
_user32.SendInput.argtypes = [wintypes.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
_user32.SendInput.restype = wintypes.UINT
_user32.MapVirtualKeyW.argtypes = [wintypes.UINT, wintypes.UINT]
_user32.MapVirtualKeyW.restype = wintypes.UINT


def _send(inputs, count: int) -> int:
    """Wraps SendInput; returns the number of events actually injected (0 if blocked by UIPI)."""
    sent = _user32.SendInput(count, inputs, ctypes.sizeof(INPUT))
    if sent != count:
        print(f"[Injector Warning] SendInput delivered {sent}/{count} events "
              f"(Win32 error {ctypes.get_last_error()}). Target window may be elevated.")
    return sent


def _key_event(inp, vk: int, flags: int = 0, scan: int = 0):
    inp.type = INPUT_KEYBOARD
    inp.union.ki.wVk = vk
    inp.union.ki.wScan = scan
    inp.union.ki.dwFlags = flags
    inp.union.ki.time = 0
    inp.union.ki.dwExtraInfo = 0


def send_ctrl_v():
    """Simulates physical hardware Ctrl + V using Win32 SendInput."""
    inputs = (INPUT * 4)()
    sc_ctrl = _user32.MapVirtualKeyW(VK_CONTROL, 0)
    sc_v = _user32.MapVirtualKeyW(VK_V, 0)
    _key_event(inputs[0], VK_CONTROL, 0, sc_ctrl)
    _key_event(inputs[1], VK_V, 0, sc_v)
    _key_event(inputs[2], VK_V, KEYEVENTF_KEYUP, sc_v)
    _key_event(inputs[3], VK_CONTROL, KEYEVENTF_KEYUP, sc_ctrl)
    _send(inputs, 4)


def send_neutral_keypress():
    """
    Taps an unassigned virtual key. When a lone Alt press/release is followed by a key event,
    Windows does NOT activate the target app's menu bar, so call this right after Alt is released.
    """
    inputs = (INPUT * 2)()
    _key_event(inputs[0], VK_UNASSIGNED, 0, 0)
    _key_event(inputs[1], VK_UNASSIGNED, KEYEVENTF_KEYUP, 0)
    _send(inputs, 2)


def _utf16_units(text: str):
    """Yields UTF-16 code units so characters beyond the BMP (emoji) are sent as surrogate pairs."""
    data = text.encode("utf-16-le", errors="replace")
    for i in range(0, len(data), 2):
        yield data[i] | (data[i + 1] << 8)


def _send_units(units) -> None:
    n = len(units)
    if n == 0:
        return
    inputs = (INPUT * (n * 2))()
    for i, unit in enumerate(units):
        _key_event(inputs[i * 2], 0, KEYEVENTF_UNICODE, unit)
        _key_event(inputs[i * 2 + 1], 0, KEYEVENTF_UNICODE | KEYEVENTF_KEYUP, unit)
    _send(inputs, n * 2)


def send_unicode_string(text: str):
    """
    Batched Win32 SendInput with KEYEVENTF_UNICODE.
    Injects text without touching the clipboard. Newlines are sent as real Enter key presses
    (a raw U+000A is ignored by many editors), and long strings are chunked.
    """
    if not text:
        return

    text = text.replace("\r\n", "\n").replace("\r", "\n")
    segments = text.split("\n")
    for seg_idx, segment in enumerate(segments):
        if seg_idx > 0:
            enter = (INPUT * 2)()
            _key_event(enter[0], VK_RETURN, 0, _user32.MapVirtualKeyW(VK_RETURN, 0))
            _key_event(enter[1], VK_RETURN, KEYEVENTF_KEYUP, _user32.MapVirtualKeyW(VK_RETURN, 0))
            _send(enter, 2)
        units = list(_utf16_units(segment))
        # Chunk on code-unit boundaries without splitting a surrogate pair
        pos = 0
        while pos < len(units):
            end = min(len(units), pos + CHUNK_CHARS)
            if end < len(units) and 0xD800 <= units[end - 1] <= 0xDBFF:
                end -= 1
            _send_units(units[pos:end])
            pos = end
            if pos < len(units):
                time.sleep(0.002)
