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
        QMessageBox.warning(
            None,
            "對沖小幫手",
            "工具已經在執行中。請先關閉舊視窗，再重新開啟新版。",
        )
        sys.exit(0)
    app = TradingHelperApp()
    app.show()
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
