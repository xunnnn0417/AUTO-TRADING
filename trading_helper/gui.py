from __future__ import annotations

import copy
import re
import threading
import time
from typing import Any, Callable

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QCloseEvent, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from .automation import PlatformAutomation
from .config import ConfigStore
from .models import TradeInstruction
from .sheets import SheetReader
from .windows import (
    AutomationError,
    EmergencyController,
    EmergencyStopped,
    WindowController,
)


PLATFORMS = ("cTrader", "MT5")
CALIBRATION_TARGETS = {
    "cTrader": [
        ("lot_input", "倉位／手數輸入欄"),
        ("sl_checkbox", "止損啟用勾選框"),
        ("sl_input", "止損點數輸入欄"),
        ("tp_checkbox", "止盈啟用勾選框"),
        ("tp_input", "止盈點數輸入欄"),
        ("buy_button", "買入按鈕（第二版使用）"),
        ("sell_button", "賣出按鈕（第二版使用）"),
        ("positions_entry_price", "持倉成交價懸浮位置（第二版 OCR 使用）"),
        ("new_order_button", "新增訂單按鈕（選用）"),
    ],
    "MT5": [
        ("new_order_button", "主視窗的新訂單按鈕"),
        ("lot_input", "交易量輸入欄"),
        ("bid_price", "訂單視窗的 Bid 價格"),
        ("ask_price", "訂單視窗的 Ask 價格"),
        ("sl_input", "止損價格輸入欄"),
        ("tp_input", "止盈價格輸入欄"),
        ("buy_button", "買入按鈕（第二版使用）"),
        ("sell_button", "賣出按鈕（第二版使用）"),
        ("positions_entry_price", "持倉成交價位置（第二版使用）"),
    ],
    "TradingView": [
        ("latest_price_button", "前往最新價格按鈕"),
        ("long_tool", "多頭部位工具"),
        ("short_tool", "空頭部位工具"),
        ("position_placement", "部位放置／雙擊位置"),
        ("entry_input", "部位進場價輸入欄"),
        ("sl_input", "部位止損價輸入欄"),
        ("tp_input", "部位止盈價輸入欄"),
        ("confirm_button", "部位設定確認按鈕"),
    ],
}

FIELD_LABELS = {
    "status": "狀態",
    "symbol": "商品代碼",
    "direction": "方向",
    "internal_lot": "場內手數",
    "internal_sl_points": "場內止損點數",
    "internal_tp_points": "場內止盈點數",
    "external_lot": "場外手數",
    "external_sl_points": "場外止損點數",
    "external_tp_points": "場外止盈點數",
    "estimated_price": "估算價格",
    "point_size": "每點價格",
    "price_digits": "價格小數位數",
    "internal_entry_price": "場內成交價",
    "final_external_sl_price": "場外最終止損價",
    "final_external_tp_price": "場外最終止盈價",
}


def direction_text(value: str) -> str:
    return {"BUY": "買入", "SELL": "賣出"}.get(value, value)


class UiSignals(QObject):
    log = Signal(str)
    status = Signal(str)
    error = Signal(str)
    instruction = Signal(object)
    operation_started = Signal()
    operation_finished = Signal()


class TradingHelperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("交易流程輔助工具 - 第一版")
        self.resize(1200, 430)
        self.setMinimumWidth(900)
        self.setMinimumHeight(390)
        self.setMaximumHeight(460)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.store = ConfigStore()
        self.reader = SheetReader()
        self.instruction: TradeInstruction | None = None
        self.signals = UiSignals()
        self.signals.log.connect(self._append_log)
        self.signals.status.connect(self._set_status)
        self.signals.error.connect(self._show_error)
        self.signals.instruction.connect(self._show_instruction)
        self.signals.operation_started.connect(self._hide_for_operation)
        self.signals.operation_finished.connect(self._restore_after_operation)
        self.emergency = EmergencyController(self._emergency_callback)
        self.windows = WindowController(self.emergency)
        threading.Thread(target=self.windows.warm_ocr, daemon=True).start()
        self.automation = PlatformAutomation(
            self.store.data, self.windows, self.emergency, self.log
        )
        self._build()
        self._build_operation_hint()
        self._dock_top()
        QShortcut(QKeySequence("Esc"), self, activated=self.emergency.stop)
        self.log("第一版已啟動。目前禁止程式送出訂單。")

    def _build_operation_hint(self) -> None:
        self.operation_hint = QLabel("按 ESC 暫停操作")
        self.operation_hint.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self.operation_hint.setAlignment(Qt.AlignCenter)
        self.operation_hint.setStyleSheet(
            "QLabel {"
            "background: rgba(20, 20, 20, 210);"
            "color: white;"
            "padding: 5px 14px;"
            "border-radius: 4px;"
            "font-size: 11px;"
            "}"
        )
        self.operation_hint.adjustSize()

    def _hide_for_operation(self) -> None:
        self.hide()
        screen = QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            self.operation_hint.adjustSize()
            self.operation_hint.move(
                area.x() + (area.width() - self.operation_hint.width()) // 2,
                area.y() + 4,
            )
        self.operation_hint.show()
        self.operation_hint.raise_()

    def _restore_after_operation(self) -> None:
        self.operation_hint.hide()
        self.show()
        self._dock_top()
        self.raise_()
        self.activateWindow()

    def _build(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        main = QGridLayout(central)
        main.setContentsMargins(8, 8, 8, 8)
        main.setHorizontalSpacing(8)
        main.setVerticalSpacing(5)

        header = QHBoxLayout()
        title = QLabel("交易流程輔助工具")
        title.setStyleSheet("font-size: 20px; font-weight: 700;")
        self.status_label = QLabel("就緒")
        self.status_label.setStyleSheet("font-size: 14px; font-weight: 700; color: #176b35;")
        self.always_on_top = QCheckBox("保持最上層")
        self.always_on_top.setChecked(True)
        self.always_on_top.toggled.connect(self.set_always_on_top)
        minimize_button = QPushButton("縮小工具")
        minimize_button.clicked.connect(self.showMinimized)
        header.addWidget(title)
        header.addStretch()
        header.addWidget(self.always_on_top)
        header.addWidget(minimize_button)
        header.addWidget(self.status_label)
        main.addLayout(header, 0, 0, 1, 2)

        platforms = QGroupBox("平台")
        platform_layout = QGridLayout(platforms)
        self.internal_platform = QComboBox()
        self.internal_platform.addItems(PLATFORMS)
        self.internal_platform.setCurrentText(self.store.data["ui"]["internal_platform"])
        self.external_platform = QComboBox()
        self.external_platform.addItems(PLATFORMS)
        self.external_platform.setCurrentText(self.store.data["ui"]["external_platform"])
        platform_layout.addWidget(QLabel("場內平台"), 0, 0)
        platform_layout.addWidget(self.internal_platform, 0, 1)
        platform_layout.addWidget(QLabel("場外平台"), 0, 2)
        platform_layout.addWidget(self.external_platform, 0, 3)
        main.addWidget(platforms, 1, 0)

        data_box = QGroupBox("試算表交易資料")
        data_layout = QGridLayout(data_box)
        self.data_labels: dict[str, QLabel] = {}
        labels = [
            ("商品代碼", "symbol"), ("表格方向", "sheet_direction"),
            ("場內方向", "internal_direction"), ("場外方向", "external_direction"),
            ("場內手數", "internal_lot"), ("場內止損點數", "internal_sl"),
            ("場內止盈點數", "internal_tp"), ("場外手數", "external_lot"),
            ("場外止損點數", "external_sl"), ("場外止盈點數", "external_tp"),
        ]
        for index, (text, key) in enumerate(labels):
            row, section = divmod(index, 2)
            base = section * 2
            value = QLabel("-")
            value.setStyleSheet("font-weight: 700;")
            self.data_labels[key] = value
            data_layout.addWidget(QLabel(text), row, base)
            data_layout.addWidget(value, row, base + 1)
        main.addWidget(data_box, 2, 0, 2, 1)

        options = QHBoxLayout()
        self.simultaneous = QCheckBox("同時進場")
        self.simultaneous.setChecked(self.store.data["ui"]["simultaneous_entry"])
        note = QLabel("第一版僅確認資料，不會點擊下單按鈕。")
        note.setStyleSheet("color: #8a4d00;")
        options.addWidget(self.simultaneous)
        options.addStretch()
        options.addWidget(note)
        main.addLayout(options, 4, 0)

        actions = QGroupBox("操作")
        action_layout = QGridLayout(actions)
        definitions: list[tuple[str, Callable[[], None], int, int]] = [
            ("讀取試算表", self.read_sheet, 0, 0),
            ("試算表設定", self.open_settings, 0, 1),
            ("校準 cTrader", lambda: self.open_calibration("cTrader"), 1, 0),
            ("校準 MT5", lambda: self.open_calibration("MT5"), 1, 1),
            ("校準 TradingView", lambda: self.open_calibration("TradingView"), 1, 2),
            ("填入場內", lambda: self.fill_role("internal"), 2, 0),
            ("填入場外", lambda: self.fill_role("external"), 2, 1),
            ("填入兩邊", self.fill_both, 2, 2),
        ]
        for text, callback, row, column in definitions:
            button = QPushButton(text)
            button.clicked.connect(callback)
            action_layout.addWidget(button, row, column)
        main.addWidget(actions, 1, 1, 3, 1)

        future = QGroupBox("TradingView")
        future_layout = QHBoxLayout(future)
        tradingview_button = QPushButton("繪製 TradingView 部位")
        tradingview_button.clicked.connect(self.draw_tradingview)
        future_layout.addWidget(tradingview_button)
        main.addWidget(future, 4, 1)

        log_box = QGroupBox("操作紀錄")
        log_layout = QVBoxLayout(log_box)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMaximumHeight(72)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        log_layout.addWidget(self.log_text)
        main.addWidget(log_box, 5, 0, 1, 2)
        main.setColumnStretch(0, 3)
        main.setColumnStretch(1, 2)

    def _dock_top(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        width = min(1200, max(900, area.width() - 40))
        self.resize(width, 430)
        self.move(area.x() + (area.width() - width) // 2, area.y())

    def log(self, message: str) -> None:
        self.signals.log.emit(message)

    def _append_log(self, message: str) -> None:
        self.log_text.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {message}")

    def _set_status(self, value: str) -> None:
        self.status_label.setText(value)
        color = "#a00000" if value in {"已停止", "錯誤"} else "#176b35"
        self.status_label.setStyleSheet(
            f"font-size: 14px; font-weight: 700; color: {color};"
        )

    def _show_error(self, message: str) -> None:
        QMessageBox.critical(self, "交易流程輔助工具", message)

    def set_always_on_top(self, enabled: bool) -> None:
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        self.show()
        self.raise_()
        self.activateWindow()

    def _emergency_callback(self) -> None:
        self.signals.status.emit("已停止")
        self.log("緊急停止：已取消所有待執行的滑鼠與鍵盤操作。")

    def _start(self, name: str, task: Callable[[], None]) -> None:
        if self.emergency.event.is_set():
            self.emergency.reset()
            self.signals.status.emit("就緒")
            self.log("已解除緊急停止，開始執行新的操作。")

        def worker() -> None:
            self.signals.operation_started.emit()
            self.signals.status.emit(name.upper())
            try:
                task()
                if not self.emergency.event.is_set():
                    self.signals.status.emit("就緒")
            except EmergencyStopped:
                self.signals.status.emit("已停止")
            except Exception as exc:
                self.signals.status.emit("錯誤")
                self.log(f"錯誤：{exc}")
                self.signals.error.emit(str(exc))
            finally:
                self.signals.operation_finished.emit()

        threading.Thread(target=worker, daemon=True).start()

    def read_sheet(self) -> None:
        self._start("讀取中", self._read_sheet_task)

    def _read_sheet_task(self) -> None:
        self.log("正在讀取 Google 試算表。")
        item = self.reader.read(self.store.data["sheet"])
        self.instruction = item
        self.signals.instruction.emit(item)
        self.log(
            f"已讀取第 {item.source_row} 列：{item.symbol}，"
            f"場內{direction_text(item.internal_direction)}／"
            f"場外{direction_text(item.external_direction)}。"
        )

    def _show_instruction(self, item: TradeInstruction) -> None:
        values = {
            "symbol": item.symbol,
            "sheet_direction": direction_text(item.sheet_direction),
            "internal_direction": direction_text(item.internal_direction),
            "external_direction": direction_text(item.external_direction),
            "internal_lot": str(item.internal.lot),
            "internal_sl": str(item.internal.sl_points),
            "internal_tp": str(item.internal.tp_points),
            "external_lot": str(item.external.lot),
            "external_sl": str(item.external.sl_points),
            "external_tp": str(item.external.tp_points),
        }
        for key, value in values.items():
            self.data_labels[key].setText(value)

    def fill_role(self, role: str) -> None:
        platform = (
            self.internal_platform.currentText()
            if role == "internal"
            else self.external_platform.currentText()
        )

        def task() -> None:
            item = self._require_instruction()
            self.automation.fill(platform, role, item)
        self._start("填入場內" if role == "internal" else "填入場外", task)

    def fill_both(self) -> None:
        internal_platform = self.internal_platform.currentText()
        external_platform = self.external_platform.currentText()
        self._start(
            "填入兩邊",
            lambda: self._fill_both_task(internal_platform, external_platform),
        )

    def _fill_both_task(
        self, internal_platform: str, external_platform: str
    ) -> None:
        item = self._require_instruction()
        self.automation.fill(internal_platform, "internal", item)
        self.automation.fill(external_platform, "external", item)

    def draw_tradingview(self) -> None:
        external_platform = self.external_platform.currentText()

        def task() -> None:
            item = self._require_instruction()
            self.automation.draw_tradingview(
                item,
                external_platform=external_platform,
            )

        self._start("繪製 TradingView", task)

    def _require_instruction(self) -> TradeInstruction:
        if self.instruction is None:
            raise AutomationError("請先讀取 Google 試算表，再執行這項操作。")
        return self.instruction

    def open_calibration(self, platform: str) -> None:
        CalibrationDialog(self, platform).exec()

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.automation.config = self.store.data
            self.log("設定已儲存。")

    def save_ui_state(self) -> None:
        self.store.data["ui"].update(
            {
                "internal_platform": self.internal_platform.currentText(),
                "external_platform": self.external_platform.currentText(),
                "simultaneous_entry": self.simultaneous.isChecked(),
            }
        )
        self.store.save()

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_ui_state()
        self.emergency.close()
        event.accept()


class CalibrationDialog(QDialog):
    capture_finished = Signal(str)

    def __init__(self, app: TradingHelperApp, platform: str):
        super().__init__(app)
        self.app = app
        self.platform = platform
        self.setWindowTitle(f"校準 {platform}")
        self.resize(530, 470)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        layout.addWidget(
            QLabel(
                "選擇要校準的項目並按下「擷取位置」，接著把滑鼠移到平台控制項上。\n"
                "倒數 3 秒後，程式會儲存相對於該視窗的位置。"
            )
        )
        self.radios: dict[str, QRadioButton] = {}
        for index, (key, label) in enumerate(CALIBRATION_TARGETS[platform]):
            radio = QRadioButton(label)
            radio.setChecked(index == 0)
            self.radios[key] = radio
            layout.addWidget(radio)
        self.result = QLabel("")
        self.result.setStyleSheet("color: #176b35;")
        layout.addWidget(self.result)
        layout.addStretch()
        buttons = QHBoxLayout()
        capture = QPushButton("擷取位置")
        capture.clicked.connect(self.capture)
        show_position = QPushButton("顯示位置")
        show_position.clicked.connect(self.show_position)
        close = QPushButton("關閉")
        close.clicked.connect(self.accept)
        buttons.addWidget(capture)
        buttons.addWidget(show_position)
        buttons.addStretch()
        buttons.addWidget(close)
        layout.addLayout(buttons)
        self.capture_finished.connect(self._finish_capture)

    def capture(self) -> None:
        key = next(key for key, radio in self.radios.items() if radio.isChecked())
        self.showMinimized()

        def task() -> None:
            try:
                for count in (3, 2, 1):
                    self.app.log(f"正在校準 {self.platform}「{key}」：{count}")
                    time.sleep(1)
                active = self.app.windows.window_at_cursor()
                x, y = self.app.windows.cursor_position()
                point = self.app.windows.relative_point(active, x, y)
                point["window_title"] = re.escape(active.title)
                profile = self.app.store.data["platforms"][self.platform]
                profile["points"][key] = point
                if key == "new_order_button" or not profile["window_title"]["internal"]:
                    profile["window_title"]["internal"] = re.escape(active.title)
                    profile["window_title"]["external"] = re.escape(active.title)
                self.app.store.save()
                self.app.log(
                    f"已儲存 {self.platform}「{key}」的相對位置："
                    f"({point['x']:.3f}, {point['y']:.3f})，"
                    f"精確像素 ({point['x_px']}, {point['y_px']})，"
                    f"螢幕座標 ({x}, {y})。"
                )
                self.capture_finished.emit(key)
            except Exception as exc:
                self.app.signals.error.emit(str(exc))
                self.capture_finished.emit("")

        threading.Thread(target=task, daemon=True).start()

    def show_position(self) -> None:
        key = next(key for key, radio in self.radios.items() if radio.isChecked())
        profile = self.app.store.data["platforms"][self.platform]
        point = profile.get("points", {}).get(key)
        if not point:
            QMessageBox.warning(self, "顯示位置", "這個項目尚未校準。")
            return
        try:
            title_pattern = str(point.get("window_title", "")).strip()
            if not title_pattern:
                title_pattern = profile["window_title"]["internal"]
            target_window = self.app.windows.find(title_pattern)
            x, y = self.app.windows.screen_point(target_window, point)
        except Exception as exc:
            QMessageBox.critical(self, "顯示位置", str(exc))
            return
        self.app.windows.show_marker(x, y, duration_ms=2500)
        self.result.setText(f"正在顯示：{key}")

    def _finish_capture(self, key: str) -> None:
        self.result.setText(f"已儲存：{key}" if key else "擷取失敗。")
        self.showNormal()
        self.raise_()
        self.activateWindow()


class SettingsDialog(QDialog):
    def __init__(self, app: TradingHelperApp):
        super().__init__(app)
        self.app = app
        self.draft = copy.deepcopy(app.store.data)
        self.setWindowTitle("試算表與視窗設定")
        self.resize(720, 760)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.setWindowFlag(Qt.WindowMinimizeButtonHint, True)
        layout = QVBoxLayout(self)
        tabs = QTabWidget()
        layout.addWidget(tabs)
        self.sheet_fields: dict[str, QLineEdit] = {}
        self.column_fields: dict[str, QLineEdit] = {}
        self.title_fields: dict[tuple[str, str], QLineEdit] = {}
        self.open_panel_checks: dict[str, QCheckBox] = {}
        tabs.addTab(self._sheet_tab(), "Google 試算表")
        tabs.addTab(self._columns_tab(), "欄位對應")
        tabs.addTab(self._windows_tab(), "視窗標題")
        buttons = QDialogButtonBox(QDialogButtonBox.Save | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Save).setText("儲存")
        buttons.button(QDialogButtonBox.Cancel).setText("取消")
        minimize_button = buttons.addButton(
            "縮小設定", QDialogButtonBox.ActionRole
        )
        minimize_button.clicked.connect(self.showMinimized)
        buttons.accepted.connect(self.save)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def _sheet_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        fields = [
            ("mode", "讀取模式（csv 或 service_account）"),
            ("data_layout", "資料位置模式（row 或 cells）"),
            ("spreadsheet_url", "試算表網址"),
            ("worksheet", "工作表名稱"),
            ("gid", "工作表 GID"),
            ("service_account_file", "服務帳戶 JSON 檔案"),
            ("row_number", "備用資料列"),
            ("status_value", "要選取的狀態值"),
        ]
        for key, label in fields:
            entry = QLineEdit(str(self.draft["sheet"].get(key, "")))
            self.sheet_fields[key] = entry
            form.addRow(label, entry)
        note = QLabel(
            "CSV 模式需要開啟連結存取權限。服務帳戶模式需要把試算表\n"
            "分享給服務帳戶的電子郵件地址。\n"
            "row 依資料列讀取；cells 可讓每個欄位直接指定 B5、D8 等儲存格。"
        )
        note.setStyleSheet("color: #555555;")
        form.addRow(note)
        return tab

    def _columns_tab(self) -> QWidget:
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        content = QWidget()
        form = QFormLayout(content)
        for key, value in self.draft["sheet"]["columns"].items():
            entry = QLineEdit(str(value))
            self.column_fields[key] = entry
            form.addRow(FIELD_LABELS.get(key, key), entry)
        note = QLabel(
            "row 模式：輸入完整標題、欄位字母或欄位編號。\n"
            "cells 模式：數值欄位填儲存格位置，例如 B5、D8；\n"
            "商品、方向、每點價格及小數位數也可直接填固定值。"
        )
        note.setStyleSheet("color: #555555;")
        form.addRow(note)
        scroll.setWidget(content)
        return scroll

    def _windows_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        for platform in ("cTrader", "MT5", "TradingView"):
            title = QLabel(platform)
            title.setStyleSheet("font-weight: 700; margin-top: 8px;")
            form.addRow(title)
            for role in ("internal", "external"):
                entry = QLineEdit(
                    self.draft["platforms"][platform]["window_title"][role]
                )
                self.title_fields[(platform, role)] = entry
                role_text = "場內" if role == "internal" else "場外"
                form.addRow(f"{role_text}視窗標題規則", entry)
            checkbox = QCheckBox("填入資料前先點擊已校準的新增訂單按鈕")
            checkbox.setChecked(
                bool(self.draft["platforms"][platform]["open_panel_before_fill"])
            )
            self.open_panel_checks[platform] = checkbox
            form.addRow("下單面板", checkbox)
        note = QLabel(
            "如果同一平台開啟兩個帳戶視窗，請設定不同的視窗標題規則。"
        )
        note.setStyleSheet("color: #555555;")
        form.addRow(note)
        return tab

    def save(self) -> None:
        try:
            for key, entry in self.sheet_fields.items():
                value: Any = entry.text().strip()
                if key == "row_number":
                    value = int(value or "2")
                self.draft["sheet"][key] = value
            for key, entry in self.column_fields.items():
                self.draft["sheet"]["columns"][key] = entry.text().strip()
            for (platform, role), entry in self.title_fields.items():
                self.draft["platforms"][platform]["window_title"][role] = (
                    entry.text().strip()
                )
            for platform, checkbox in self.open_panel_checks.items():
                self.draft["platforms"][platform]["open_panel_before_fill"] = (
                    checkbox.isChecked()
                )
            self.app.store.data = self.draft
            self.app.store.save()
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "設定", str(exc))
