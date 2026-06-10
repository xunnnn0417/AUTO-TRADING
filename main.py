import ctypes
import sys

MUTEX_NAME = "Local\\TradingWorkflowHelperMVP"
ERROR_ALREADY_EXISTS = 183


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

    from PySide6.QtWidgets import QApplication, QMessageBox
    from trading_helper.gui import TradingHelperApp

    qt = QApplication(sys.argv)
    mutex, is_first = acquire_single_instance()
    if not is_first:
        QMessageBox.warning(
            None,
            "交易流程輔助工具",
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
