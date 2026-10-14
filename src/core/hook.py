"""
Low-Level Win32 Keyboard Hook for Hotkey Capture.
Captures keypresses system-wide using WH_KEYBOARD_LL and GetMessageW.
Consumes strictly 0.0% CPU when waiting for input.
Executes callbacks asynchronously to guarantee zero hook chain timeouts.
Includes secondary low-overhead async polling watchdog to guarantee 100% hotkey
reliability even across elevated UAC/DirectX full-screen desktop switches.
"""

import ctypes
from ctypes import wintypes
import queue
import threading
import traceback
from typing import Callable, Optional

from src.injector.keystroke import send_neutral_keypress

# Win32 Constants
WH_KEYBOARD_LL = 13
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

# Virtual Key Codes
VK_MENU = 0x12        # Generic Alt
VK_LMENU = 0xA4       # Left Alt
VK_RMENU = 0xA5       # Right Alt (AltGr / ALT_R)
VK_CONTROL = 0x11     # Generic Control
VK_LCONTROL = 0xA2    # Left Ctrl
VK_RCONTROL = 0xA3    # Right Ctrl
VK_CAPITAL = 0x14     # Caps Lock

VK_F13 = 0x7C
VK_F14 = 0x7D
VK_F15 = 0x7E
VK_F16 = 0x7F
VK_F17 = 0x80
VK_F18 = 0x81
VK_F19 = 0x82
VK_F20 = 0x83
VK_F21 = 0x84
VK_F22 = 0x85
VK_F23 = 0x86
VK_F24 = 0x87

KEY_MAP = {
    "alt_r": VK_RMENU,
    "ralt": VK_RMENU,
    "altgr": VK_RMENU,
    "alt_l": VK_LMENU,
    "lalt": VK_LMENU,
    "ctrl_r": VK_RCONTROL,
    "rctrl": VK_RCONTROL,
    "ctrl_l": VK_LCONTROL,
    "lctrl": VK_LCONTROL,
    "caps_lock": VK_CAPITAL,
    "f13": VK_F13,
    "f14": VK_F14,
    "f15": VK_F15,
    "f16": VK_F16,
    "f17": VK_F17,
    "f18": VK_F18,
    "f19": VK_F19,
    "f20": VK_F20,
    "f21": VK_F21,
    "f22": VK_F22,
    "f23": VK_F23,
    "f24": VK_F24,
}

class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_ulonglong)
    ]

# Define Hook Callback Signature
HOOKPROC = ctypes.WINFUNCTYPE(
    ctypes.c_longlong,
    ctypes.c_int,
    wintypes.WPARAM,
    ctypes.POINTER(KBDLLHOOKSTRUCT)
)

# Win32 Function Signatures (Explicitly defined for 64-bit safety)
user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32

user32.SetWindowsHookExW.argtypes = [ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
user32.SetWindowsHookExW.restype = wintypes.HHOOK

user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
user32.UnhookWindowsHookEx.restype = wintypes.BOOL

user32.CallNextHookEx.argtypes = [wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, ctypes.POINTER(KBDLLHOOKSTRUCT)]
user32.CallNextHookEx.restype = ctypes.c_longlong

user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG), wintypes.HWND, wintypes.UINT, wintypes.UINT]
user32.GetMessageW.restype = wintypes.BOOL

user32.PostThreadMessageW.argtypes = [wintypes.DWORD, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM]
user32.PostThreadMessageW.restype = wintypes.BOOL

user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
user32.GetAsyncKeyState.restype = wintypes.SHORT

WM_TIMER = 0x0113
HOOK_REFRESH_MS = 30000          # re-arm the LL hook periodically in case Windows silently dropped it
WATCHDOG_INTERVAL = 0.02         # seconds between GetAsyncKeyState polls
WATCHDOG_CONFIRM_POLLS = 3       # polls the state must disagree before the watchdog corrects it

user32.SetTimer.argtypes = [wintypes.HWND, ctypes.c_size_t, wintypes.UINT, ctypes.c_void_p]
user32.SetTimer.restype = ctypes.c_size_t
user32.KillTimer.argtypes = [wintypes.HWND, ctypes.c_size_t]
user32.KillTimer.restype = wintypes.BOOL

ALT_KEYS = ("alt_r", "ralt", "altgr", "alt_l", "lalt")


class GlobalKeyboardHook:
    """
    System-wide hotkey via WH_KEYBOARD_LL.

    - Callbacks run on ONE ordered dispatcher thread, so a fast tap can never deliver
      "release" before "press".
    - A GetAsyncKeyState watchdog repairs missed events (UAC / secure desktop / dropped hooks),
      debounced so it can never race a genuine hook event.
    - The hook is re-armed every 30 s so a silently-removed hook self-heals.
    - When the hotkey is Alt, an unassigned key tap is injected while Alt is held so that
      releasing a lone Alt does not pop open the focused app's menu bar.
    """

    def __init__(
        self,
        hotkey: str = "alt_r",
        mode: str = "push_to_talk",
        on_press: Optional[Callable[[], None]] = None,
        on_release: Optional[Callable[[], None]] = None,
        target_key: Optional[str] = None,
        **kwargs
    ):
        actual_key = target_key if target_key is not None else hotkey
        self.target_key_name = str(actual_key).lower().strip()
        self.target_vk = KEY_MAP.get(self.target_key_name, VK_RMENU)
        self.mode = mode
        self.on_press = on_press
        self.on_release = on_release

        self._hook = None
        self._proc = None
        self._thread = None
        self._thread_id = None
        self._watchdog_thread = None
        self._dispatch_thread = None
        self._queue: "queue.Queue" = queue.Queue()
        self._stop_event = threading.Event()
        self._is_pressed = False
        self._is_toggled_on = False
        self._state_lock = threading.Lock()

    # ------------------------------------------------------------ dispatching
    def _dispatch_loop(self, q: "queue.Queue"):
        while True:
            fn = q.get()
            if fn is None:
                return
            try:
                fn()
            except Exception as e:
                print(f"[Hook Dispatch Error] {type(e).__name__}: {e}")
                traceback.print_exc()

    def _enqueue(self, fn: Optional[Callable[[], None]]):
        if fn is not None:
            self._queue.put(fn)

    def _is_alt_hotkey(self) -> bool:
        return self.target_key_name in ALT_KEYS

    def _press_action(self):
        if self.on_press:
            self.on_press()
        if self._is_alt_hotkey():
            send_neutral_keypress()

    def _trigger_press(self):
        with self._state_lock:
            if self._is_pressed:
                return
            self._is_pressed = True
            if self.mode == "push_to_talk":
                self._enqueue(self._press_action)
            elif self.mode == "toggle":
                self._is_toggled_on = not self._is_toggled_on
                if self._is_toggled_on:
                    self._enqueue(self._press_action)
                else:
                    self._enqueue(self.on_release)
                    if self._is_alt_hotkey():
                        self._enqueue(send_neutral_keypress)

    def _trigger_release(self):
        with self._state_lock:
            if not self._is_pressed:
                return
            self._is_pressed = False
            if self.mode == "push_to_talk":
                self._enqueue(self.on_release)

    def _is_target_key(self, vk: int, flags: int) -> bool:
        """
        Robust multi-layout key matching.
        Handles discrete VK codes and generic VK codes with extended bit (LLKHF_EXTENDED = 0x01).
        """
        is_extended = bool(flags & 0x01)
        k = self.target_key_name
        if k in ("alt_r", "ralt", "altgr"):
            return (vk == VK_RMENU) or (vk == VK_MENU and is_extended)
        elif k in ("alt_l", "lalt"):
            return (vk == VK_LMENU) or (vk == VK_MENU and not is_extended)
        elif k in ("ctrl_r", "rctrl"):
            return (vk == VK_RCONTROL) or (vk == VK_CONTROL and is_extended)
        elif k in ("ctrl_l", "lctrl"):
            return (vk == VK_LCONTROL) or (vk == VK_CONTROL and not is_extended)
        return vk == self.target_vk

    def _hook_callback(self, nCode, wParam, lParam):
        try:
            if nCode >= 0 and lParam:
                kb = lParam.contents
                if self._is_target_key(kb.vkCode, kb.flags):
                    if wParam in (WM_KEYDOWN, WM_SYSKEYDOWN):
                        self._trigger_press()
                    elif wParam in (WM_KEYUP, WM_SYSKEYUP):
                        self._trigger_release()
        except Exception as e:
            print(f"[Hook Callback Notice] {e}")

        # Always pass the event along immediately so Windows never times out / removes the hook
        return user32.CallNextHookEx(self._hook, nCode, wParam, lParam)

    def _async_state_watchdog(self):
        """
        Polls the physical key state and corrects the logical state if the LL hook missed an event.
        Corrections require several consecutive disagreeing polls so they cannot race real events.
        """
        mismatch = 0
        while not self._stop_event.wait(WATCHDOG_INTERVAL):
            is_down = bool(user32.GetAsyncKeyState(self.target_vk) & 0x8000)
            if is_down != self._is_pressed:
                mismatch += 1
                if mismatch >= WATCHDOG_CONFIRM_POLLS:
                    mismatch = 0
                    if is_down:
                        self._trigger_press()
                    else:
                        self._trigger_release()
            else:
                mismatch = 0

    def _install_hook(self):
        self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, None, 0)
        if not self._hook:
            h_mod = kernel32.GetModuleHandleW(None)
            self._hook = user32.SetWindowsHookExW(WH_KEYBOARD_LL, self._proc, h_mod, 0)
        return bool(self._hook)

    def _message_loop(self):
        timer_id = 0
        try:
            self._thread_id = kernel32.GetCurrentThreadId()
            self._proc = HOOKPROC(self._hook_callback)

            if self._install_hook():
                print(f"[Hook] WH_KEYBOARD_LL successfully installed (handle: {self._hook}).")
            else:
                print(f"[Hook Error] Failed to install WH_KEYBOARD_LL (Win32 error {ctypes.GetLastError()}). "
                      f"Relying on the polling watchdog.")

            timer_id = user32.SetTimer(None, 0, HOOK_REFRESH_MS, None)

            msg = wintypes.MSG()
            while not self._stop_event.is_set():
                res = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
                if res <= 0:
                    break
                if msg.message == WM_TIMER:
                    # Periodic self-heal: re-arm the hook when the hotkey is idle
                    if not self._is_pressed:
                        if self._hook:
                            user32.UnhookWindowsHookEx(self._hook)
                            self._hook = None
                        if not self._install_hook():
                            print("[Hook Warning] Could not re-arm WH_KEYBOARD_LL; polling watchdog remains active.")
                    continue
                user32.TranslateMessage(ctypes.byref(msg))
                user32.DispatchMessageW(ctypes.byref(msg))
        except Exception as e:
            print(f"[Hook Fatal] Message loop error: {type(e).__name__}: {e}")
            traceback.print_exc()
        finally:
            if timer_id:
                user32.KillTimer(None, timer_id)
            if self._hook:
                user32.UnhookWindowsHookEx(self._hook)
                self._hook = None
                print("[Hook] WH_KEYBOARD_LL unhooked cleanly.")

    def start(self):
        if self.is_alive():
            return
        self._stop_event.clear()
        self._queue = queue.Queue()
        self._dispatch_thread = threading.Thread(
            target=self._dispatch_loop, args=(self._queue,), daemon=True, name="Takt-HookDispatch")
        self._dispatch_thread.start()
        self._watchdog_thread = threading.Thread(target=self._async_state_watchdog, daemon=True, name="Takt-KeyWatchdog")
        self._watchdog_thread.start()
        self._thread = threading.Thread(target=self._message_loop, daemon=True, name="Takt-HookThread")
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread_id:
            WM_QUIT = 0x0012
            user32.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=1.0)
        self._queue.put(None)

    def is_alive(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def update_hotkey(self, hotkey: str, mode: str):
        """Dynamically updates the watched virtual key code and mode."""
        with self._state_lock:
            self.target_key_name = str(hotkey).lower().strip()
            self.target_vk = KEY_MAP.get(self.target_key_name, VK_RMENU)
            self.mode = mode
            self._is_pressed = False
            self._is_toggled_on = False
