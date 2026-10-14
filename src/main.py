import ctypes
import os
import signal
import sys

# Ensure project root is in sys.path regardless of how the script is launched
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.core.config import app_dir, is_frozen, load_config, config_mtime
from src.core import diagnostics

# Always anchor the working directory to the application root, and (frozen) route output to logs/takt.log
os.chdir(app_dir())
diagnostics.setup_logging()
diagnostics.install_crash_handlers()

from PyQt6.QtCore import QTimer
from PyQt6.QtGui import QIcon
from PyQt6.QtWidgets import QApplication, QMessageBox

# Win32 Process Priority Constants
HIGH_PRIORITY_CLASS = 0x00000080
APP_USER_MODEL_ID = "DesertAntLabs.Takt.Dictation"


def set_high_priority():
    """Sets current process to HIGH priority for real-time keystroke responsiveness."""
    try:
        proc = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(proc, HIGH_PRIORITY_CLASS)
        print("[System] Elevated process priority to HIGH_PRIORITY_CLASS.")
    except Exception as e:
        print(f"[System] Priority adjustment notice: {e}")


def _app_icon() -> QIcon:
    for base in (app_dir(), getattr(sys, "_MEIPASS", app_dir())):
        p = os.path.join(base, "assets", "takt.ico")
        if os.path.exists(p):
            return QIcon(p)
    return QIcon()


def main():
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:
        pass

    app = QApplication.instance() or QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setApplicationName("Takt")
    app.setWindowIcon(_app_icon())
    diagnostics.install_qt_message_handler()

    from src.ui.settings_gui import SettingsWindow

    # `Takt.exe --settings` (used by the Start-menu shortcut) runs only the preferences window;
    # a running instance picks the saved changes up through its config watcher.
    if "--settings" in sys.argv:
        win = SettingsWindow()
        app.setQuitOnLastWindowClosed(True)
        win.show()
        sys.exit(app.exec())

    if not diagnostics.acquire_single_instance():
        print("[Boot] Another Takt instance is already running. Exiting.")
        QMessageBox.information(None, "Takt", "Takt is already running in the system tray.")
        sys.exit(0)

    print("=" * 60)
    print(" Takt - Local System-Wide Voice Dictation for Windows")
    print(" Powered by Desert Ant Labs (Clear & Voz) + Contextual Engine")
    print("=" * 60)

    set_high_priority()

    from src.core.hook import GlobalKeyboardHook
    from src.core.pipeline import TaktPipeline
    from src.ui.tray import TaktTray

    config = load_config()
    state = {
        "config": config,
        "mtime": config_mtime(),
        "settings": None,
        "tray": None,
        "closing": False,
    }

    # 2. Voice dictation pipeline
    pipeline = TaktPipeline(config)

    # 3. Global keyboard hook
    hotkey_cfg = config.get("hotkey", {})
    hook = GlobalKeyboardHook(
        hotkey=hotkey_cfg.get("key", "alt_r"),
        mode=hotkey_cfg.get("mode", "push_to_talk"),
        on_press=pipeline.handle_press,
        on_release=pipeline.handle_release
    )
    hook.start()

    def apply_config(new_config: dict):
        """Applies freshly saved settings to the live hook, pipeline, HUD and tray."""
        old = state["config"]
        state["mtime"] = config_mtime()   # prevents the file watcher re-applying our own save
        if new_config == old:
            return
        state["config"] = new_config
        print("[Config] Settings changed. Applying to running instance...")
        try:
            new_hk = new_config.get("hotkey", {})
            old_hk = old.get("hotkey", {})
            if new_hk != old_hk:
                hook.update_hotkey(new_hk.get("key", "alt_r"), new_hk.get("mode", "push_to_talk"))
                print(f"[Hook] Updated hotkey to [{new_hk.get('key', 'alt_r').upper()}] ({new_hk.get('mode')})")

            pipeline.apply_config(new_config)

            tray = state["tray"]
            accent = new_config.get("ui", {}).get("accent_color", "#ffbdd4")
            if tray and accent != old.get("ui", {}).get("accent_color"):
                tray.set_accent_color(accent)
        except Exception as e:
            print(f"[Config Error] Failed to apply settings: {type(e).__name__}: {e}")

    def show_settings():
        if state["settings"] is None:
            state["settings"] = SettingsWindow(on_save_callback=apply_config)
        win = state["settings"]
        win.reload_from_disk()
        win.show()
        win.showNormal()
        win.raise_()
        win.activateWindow()

    # 4. System tray companion
    ui_cfg = config.get("ui", {})
    if ui_cfg.get("tray_enabled", True):
        try:
            tray = TaktTray(
                accent_color=ui_cfg.get("accent_color", "#ffbdd4"),
                on_open_settings=show_settings,
                on_exit=lambda: app.quit()
            )
            tray.show()
            state["tray"] = tray
            print("[UI] System Tray companion active in Windows taskbar.")
        except Exception as e:
            print(f"[UI Notice] Tray initialization: {e}")

    key_name = hotkey_cfg.get("key", "alt_r").upper()
    print(f"[Ready] Hotkey: [{key_name}] | Mode: [{hotkey_cfg.get('mode', 'push_to_talk')}]")
    print("[Instructions] Hold the hotkey and speak. Release to dictate.")

    # 5. Hot-reload: pick up config changes saved by a separate `--settings` process
    def poll_config():
        mtime = config_mtime()
        if mtime and mtime != state["mtime"]:
            state["mtime"] = mtime
            try:
                apply_config(load_config())
            except Exception as e:
                print(f"[Config Error] Reload failed: {e}")

    cfg_timer = QTimer()
    cfg_timer.setInterval(1500)
    cfg_timer.timeout.connect(poll_config)
    cfg_timer.start()

    # 6. Orderly shutdown (runs exactly once, from the Qt thread, for any exit path)
    def cleanup():
        if state["closing"]:
            return
        state["closing"] = True
        print("\n[Shutdown] Cleaning up Takt subsystems...")
        for name, fn in (("hook", hook.stop), ("pipeline", pipeline.shutdown),
                         ("tray", lambda: state["tray"] and state["tray"].hide())):
            try:
                fn()
            except Exception as e:
                print(f"[Shutdown Notice] {name}: {e}")

    app.aboutToQuit.connect(cleanup)

    # Signals only set a flag via the Qt loop; never call sys.exit() from inside Qt callbacks
    signal.signal(signal.SIGINT, lambda *_: app.quit())
    signal.signal(signal.SIGTERM, lambda *_: app.quit())
    sig_timer = QTimer()
    sig_timer.setInterval(250)
    sig_timer.timeout.connect(lambda: None)
    sig_timer.start()

    code = app.exec()
    cleanup()
    sys.exit(code)


if __name__ == "__main__":
    try:
        main()
    except SystemExit:
        raise
    except Exception:
        import traceback
        print("[Fatal] Unhandled exception in main():")
        traceback.print_exc()
        sys.exit(1)
