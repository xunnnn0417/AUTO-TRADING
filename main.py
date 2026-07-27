import ctypes
import sys
from pathlib import Path

MUTEX_NAME = "Local\\HedgeAssistant"
ERROR_ALREADY_EXISTS = 183
APP_ID = "Xun.HedgeAssistant.App"
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
    enable_dpi_awareness()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass

    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from trading_helper.gui import TradingHelperApp

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
    exit_code = qt.exec()
    if mutex:
        ctypes.windll.kernel32.CloseHandle(mutex)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
