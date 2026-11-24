import ctypes
import os
import sys
from pathlib import Path

MUTEX_NAME = "Local\\HedgeAssistantTest"
ERROR_ALREADY_EXISTS = 183
APP_ID = "Xun.HedgeAssistant.Test"
APP_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
APP_ICON = APP_BASE / "assets" / "app.ico"


def enable_dpi_awareness() -> None:
    """Keep Win32, Qt, and PyAutoGUI coordinates in the same pixel space."""
    try:
        ctypes.windll.user32.SetProcessDpiAwarenessContext(ctypes.c_void_p(-4))
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
        return
    except (AttributeError, OSError):
        pass
    try:
        ctypes.windll.user32.SetProcessDPIAware()
    except (AttributeError, OSError):
        pass


def acquire_single_instance():
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if not mutex:
        return None, False
    already_running = ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS
    return mutex, not already_running


def focus_running_instance() -> bool:
    """Bring the already-running helper (main window or a calibration
    dialog) to the front. Only visible Qt windows of another python process
    with our window titles are considered; nothing is closed or changed."""
    from ctypes import wintypes
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    own_pid = os.getpid()
    found = []

    def exe_name(pid: int) -> str:
        handle = kernel32.OpenProcess(0x1000, False, pid)  # QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            size = wintypes.DWORD(1024)
            buffer = ctypes.create_unicode_buffer(size.value)
            if kernel32.QueryFullProcessImageNameW(handle, 0, buffer, ctypes.byref(size)):
                return Path(buffer.value).name.lower()
            return ""
        finally:
            kernel32.CloseHandle(handle)

    @ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
    def visit(hwnd, _):
        if not user32.IsWindowVisible(hwnd) or not user32.IsWindowEnabled(hwnd):
            return True
        title = ctypes.create_unicode_buffer(256)
        user32.GetWindowTextW(hwnd, title, 256)
        klass = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW(hwnd, klass, 256)
        text = title.value
        if not klass.value.startswith("Qt") or not (
                text == "對沖小幫手" or text.startswith("校準 ")):
            return True
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if pid.value != own_pid and exe_name(pid.value) in {"pythonw.exe", "python.exe"}:
            found.append(hwnd)
        return True

    try:
        user32.EnumWindows(visit, 0)
        for hwnd in found:
            user32.ShowWindow(hwnd, 9)  # SW_RESTORE
            if user32.SetForegroundWindow(hwnd):
                return True
    except (AttributeError, OSError):
        pass
    return False


def main() -> None:
    # Existing desktop/taskbar shortcuts keep working after a runtime update.
    # Select the private, verified runtime before importing any Qt/OCR DLLs.
    from trading_helper.self_update import installed_python
    selected=installed_python(APP_BASE)
    if selected and Path(sys.executable).resolve()!=selected.resolve():
        import subprocess
        subprocess.Popen([str(selected),str(APP_BASE/"main.py")],cwd=APP_BASE)
        return
    enable_dpi_awareness()
    from trading_helper import crash_log
    crash_log.install()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass

    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication
    from trading_helper.gui import TradingHelperApp, ThemedMessageBox as QMessageBox
    from trading_helper.update_ui import UpdateController

    qt = QApplication(sys.argv)
    if APP_ICON.exists():
        qt.setWindowIcon(QIcon(str(APP_ICON)))
    mutex, is_first = acquire_single_instance()
    if not is_first:
        if not focus_running_instance():
            QMessageBox.warning(
                None,
                "對沖小幫手",
                "工具已經在執行中，但找不到可顯示的視窗。\n"
                "請查看螢幕右側的側邊快捷；若仍無反應，請先關閉舊的小幫手再重新開啟。",
            )
        sys.exit(0)
    app = TradingHelperApp()
    # Only closing the main window ends the helper. With Qt's default, a
    # parentless popup closed while the main window was hidden for an
    # operation (e.g. a sidebar fill) silently quit the whole app.
    qt.setQuitOnLastWindowClosed(False)
    app.main_window_closed.connect(qt.quit)
    app.show()
    QTimer.singleShot(100, app.initialize_side_panel)
    updater = UpdateController(app, APP_BASE)
    qt._update_controller = updater
    QTimer.singleShot(1200, updater.start)
    receipt = os.environ.pop("HEDGE_UPDATE_RECEIPT", "")
    if receipt:
        app.begin_update()
        app.setEnabled(False)
        def confirm_startup():
            Path(receipt).write_text("started", encoding="utf-8")
            app.end_update()
            app.setEnabled(True)
        QTimer.singleShot(2000, confirm_startup)
    error_file = os.environ.pop("HEDGE_UPDATE_ERROR", "")
    if error_file:
        QTimer.singleShot(500, lambda: QMessageBox.warning(
            app, "更新未完成", "已重新開啟原版本。\n" + Path(error_file).read_text(encoding="utf-8")))
    exit_code = qt.exec()
    if updater.job is not None and updater.job.isRunning():
        updater.job.wait(20_000)
    if mutex:
        ctypes.windll.kernel32.CloseHandle(mutex)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
