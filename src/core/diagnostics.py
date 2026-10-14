"""
Takt diagnostics: timestamped log redirection, crash handlers, and the
single-instance guard.

Every uncaught exception on ANY thread (audio, hook, Qt slots, pipeline workers,
unraisable errors) is written to logs/takt.log with a full traceback instead of
silently killing the process. Native crashes dump a Python traceback through
faulthandler.
"""

import ctypes
import datetime
import faulthandler
import os
import sys
import threading
import traceback

from src.core.config import app_dir, is_frozen

_log_file = None
_mutex_handle = None

ERROR_ALREADY_EXISTS = 183
MAX_LOG_BYTES = 2 * 1024 * 1024


class _TimestampedStream:
    """Wraps a text stream, prefixing each new line with HH:MM:SS.mmm."""

    def __init__(self, stream):
        self._stream = stream
        self._at_line_start = True
        self._lock = threading.Lock()

    def write(self, s):
        if not s:
            return 0
        with self._lock:
            out = []
            for chunk in s.splitlines(keepends=True):
                if self._at_line_start and chunk.strip():
                    out.append(datetime.datetime.now().strftime("%H:%M:%S.%f")[:-3] + " ")
                out.append(chunk)
                self._at_line_start = chunk.endswith("\n")
            try:
                self._stream.write("".join(out))
            except Exception:
                pass
        return len(s)

    def flush(self):
        try:
            self._stream.flush()
        except Exception:
            pass

    def isatty(self):
        return False

    def fileno(self):
        return self._stream.fileno()

    def __getattr__(self, name):
        return getattr(self._stream, name)


def setup_logging() -> None:
    """In frozen (windowed) mode there is no console, so route stdout/stderr to logs/takt.log."""
    global _log_file
    if not is_frozen():
        return
    try:
        log_dir = os.path.join(app_dir(), "logs")
        os.makedirs(log_dir, exist_ok=True)
        path = os.path.join(log_dir, "takt.log")
        try:
            if os.path.exists(path) and os.path.getsize(path) > MAX_LOG_BYTES:
                os.replace(path, path + ".1")
        except OSError:
            pass
        _log_file = open(path, "a", encoding="utf-8", buffering=1, errors="replace")
        stream = _TimestampedStream(_log_file)
        sys.stdout = stream
        sys.stderr = stream
        print("\n" + "=" * 60 + f"\n[Boot] Takt starting (pid {os.getpid()})")
    except Exception:
        pass


def install_crash_handlers() -> None:
    def _log_exception(prefix, exc_type, exc, tb):
        try:
            print(f"[{prefix}] Uncaught {exc_type.__name__}: {exc}")
            traceback.print_exception(exc_type, exc, tb)
        except Exception:
            pass

    def _excepthook(exc_type, exc, tb):
        if issubclass(exc_type, KeyboardInterrupt):
            return
        _log_exception("Crash Guard", exc_type, exc, tb)

    def _thread_hook(args):
        if args.exc_type is SystemExit:
            return
        name = args.thread.name if args.thread else "?"
        _log_exception(f"Thread '{name}'", args.exc_type, args.exc_value, args.exc_traceback)

    def _unraisable(args):
        print(f"[Unraisable] {args.err_msg}: {args.exc_value!r}")

    sys.excepthook = _excepthook
    threading.excepthook = _thread_hook
    sys.unraisablehook = _unraisable

    try:
        if _log_file is not None:
            faulthandler.enable(file=_log_file, all_threads=True)
        elif sys.__stderr__ is not None:
            faulthandler.enable(all_threads=True)
    except Exception:
        pass


def install_qt_message_handler() -> None:
    try:
        from PyQt6.QtCore import qInstallMessageHandler, QtMsgType

        def _handler(mode, context, message):
            if mode in (QtMsgType.QtWarningMsg, QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                # Known-harmless noise from Windows layered-window updates
                if "UpdateLayeredWindowIndirect" in message or "QFont::setPointSize" in message:
                    return
                print(f"[Qt] {message}")

        qInstallMessageHandler(_handler)
    except Exception:
        pass


def acquire_single_instance(name: str = "Takt_SingleInstance_Mutex") -> bool:
    """Returns False if another Takt instance already owns the global hotkey hook."""
    global _mutex_handle
    try:
        kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
        kernel32.CreateMutexW.restype = ctypes.c_void_p
        kernel32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        _mutex_handle = kernel32.CreateMutexW(None, False, name)
        if ctypes.get_last_error() == ERROR_ALREADY_EXISTS:
            return False
    except Exception:
        pass
    return True
