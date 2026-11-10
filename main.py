import ctypes
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
    enable_dpi_awareness()
    try:
        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_ID)
    except (AttributeError, OSError):
        pass

    from PySide6.QtCore import QObject, QThread, QTimer, Signal, Slot, QUrl
    from PySide6.QtGui import QDesktopServices, QIcon
    from PySide6.QtWidgets import QApplication, QMessageBox
    from trading_helper.gui import TradingHelperApp
    from trading_helper import __version__
    from trading_helper.update_check import check_for_update

    class UpdateCheckThread(QThread):
        update_found = Signal(object)

        def run(self) -> None:
            notice = check_for_update(__version__)
            if notice is not None:
                self.update_found.emit(notice)

    class UpdatePromptReceiver(QObject):
        def __init__(self, parent_window) -> None:
            super().__init__(parent_window)
            self.parent_window = parent_window

        @Slot(object)
        def show_update_prompt(self, notice) -> None:
            dialog = QMessageBox(self.parent_window)
            dialog.setIcon(QMessageBox.Information)
            dialog.setWindowTitle("有新版本")
            dialog.setText(
                f"GitHub LAB 有較新的版本：{notice.latest_version} "
                f"（目前版本 {notice.current_version}）。\n\n"
                "要開啟 GitHub 更新頁查看嗎？程式不會自動下載或覆蓋檔案。"
            )
            open_button = dialog.addButton(
                "開啟 GitHub 更新頁", QMessageBox.AcceptRole
            )
            dialog.addButton("稍後", QMessageBox.RejectRole)
            dialog.exec()
            if dialog.clickedButton() is open_button:
                QDesktopServices.openUrl(QUrl(notice.page_url))

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
    update_check = UpdateCheckThread(qt)
    update_prompt = UpdatePromptReceiver(app)
    update_check.update_found.connect(update_prompt.show_update_prompt)
    qt._update_check_thread = update_check
    qt._update_prompt_receiver = update_prompt
    QTimer.singleShot(1200, update_check.start)
    exit_code = qt.exec()
    if update_check.isRunning():
        update_check.wait(3500)
    if mutex:
        ctypes.windll.kernel32.CloseHandle(mutex)
    sys.exit(exit_code)


if __name__ == "__main__":
    main()
