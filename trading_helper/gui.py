from __future__ import annotations

import copy
import re
import threading
import time
from decimal import Decimal, InvalidOperation
from typing import Any, Callable

from PySide6.QtCore import QObject, QTimer, Qt, Signal
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
    QInputDialog,
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
from .config import ConfigStore, ProfileStore
from .models import TradeInstruction
from .sheets import SheetReader
from .windows import (
    AutomationError,
    EmergencyController,
    EmergencyStopped,
    WindowController,
)


PLATFORMS = ("cTrader", "MT5")
MT5_TARGETS = [
    ("new_order_button", "主視窗的新訂單按鈕"),
    ("lot_input", "交易量輸入欄"),
    ("bid_price", "訂單視窗的 Bid 價格"),
    ("ask_price", "訂單視窗的 Ask 價格"),
    ("sl_input", "止損價格輸入欄"),
    ("tp_input", "止盈價格輸入欄"),
    ("position_sl_input", "持倉修改視窗的止損價格輸入欄"),
    ("position_tp_input", "持倉修改視窗的止盈價格輸入欄"),
    ("buy_button", "買入按鈕（第二版使用）"),
    ("sell_button", "賣出按鈕（第二版使用）"),
    ("positions_entry_price", "場內持倉成交價位置（OCR 使用）"),
    ("position_order_lot", "場外已進場訂單手數（第一筆）"),
    ("position_order_lot_next", "場外已進場訂單手數（下一筆，用於列距）"),
    ("position_order_row", "已進場訂單列（雙擊開啟修改視窗）"),
]
CALIBRATION_TARGETS = {
    "GooeyTrade": [
        ("lot_input", "倉位／手數輸入欄"),
        ("sl_checkbox", "止損啟用勾選框"),
        ("sl_input", "止損點數輸入欄"),
        ("tp_checkbox", "止盈啟用勾選框"),
        ("tp_input", "止盈點數輸入欄"),
        ("buy_button", "買入方向按鈕"),
        ("sell_button", "賣出方向按鈕"),
        ("positions_entry_price", "持倉成交價懸浮位置（OCR 使用）"),
        ("new_order_button", "新增訂單按鈕（選用）"),
    ],
    "cTrader": [
        ("lot_input", "倉位／手數輸入欄"),
        ("sl_checkbox", "止損啟用勾選框"),
        ("sl_input", "止損點數輸入欄"),
        ("tp_checkbox", "止盈啟用勾選框"),
        ("tp_input", "止盈點數輸入欄"),
        ("buy_button", "買入方向按鈕"),
        ("sell_button", "賣出方向按鈕"),
        ("positions_entry_price", "持倉成交價懸浮位置（第二版 OCR 使用）"),
        ("new_order_button", "新增訂單按鈕（選用）"),
    ],
    "MT5": MT5_TARGETS,
    "BYBIT MT5": MT5_TARGETS,
    "原版MT5": MT5_TARGETS,
    "TradingView": [
        ("auto_scale_button", "自動適應價格按鈕"),
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


def _window_title_pattern(platform: str, title: str) -> str:
    if platform == "GooeyTrade":
        return "GooeyTrade"
    if platform == "cTrader":
        if "GooeyTrade" in title:
            return "GooeyTrade"
        return "cTrader"
    if platform in {"MT5", "BYBIT MT5", "原版MT5"}:
        parts = [part.strip() for part in title.split(" - ") if part.strip()]
        if len(parts) >= 2:
            return f"{re.escape(parts[0])}.*{re.escape(parts[1])}"
    if platform == "TradingView":
        return r"/\s*常用$"
    return re.escape(title)


class UiSignals(QObject):
    log = Signal(str)
    status = Signal(str)
    error = Signal(str)
    instruction = Signal(object)
    operation_started = Signal()
    operation_finished = Signal()
    operation_minimized = Signal()
    entry_price_reset = Signal()


class TradingHelperApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("交易流程輔助工具 - 第一版")
        self.resize(1200, 445)
        self.setMinimumWidth(900)
        self.setMinimumHeight(405)
        self.setMaximumHeight(475)
        self.store = ConfigStore()
        self.profiles = ProfileStore(self.store.data)
        self.store.data = self.profiles.load_profile()
        self.store.save()
        self._profile_switching = False
        self.reader = SheetReader()
        self.instruction: TradeInstruction | None = None
        self.manual_entry_price: Decimal | None = None
        self.signals = UiSignals()
        self.signals.log.connect(self._append_log)
        self.signals.status.connect(self._set_status)
        self.signals.error.connect(self._show_error)
        self.signals.instruction.connect(self._show_instruction)
        self.signals.operation_started.connect(self._hide_for_operation)
        self.signals.operation_finished.connect(self._restore_after_operation)
        self.signals.operation_minimized.connect(self._minimize_after_operation)
        self.emergency = EmergencyController(self._emergency_callback)
        self.windows = WindowController(self.emergency)
        threading.Thread(target=self.windows.warm_ocr, daemon=True).start()
        self.automation = PlatformAutomation(
            self.store.data, self.windows, self.emergency, self.log
        )
        self._build()
        self.signals.entry_price_reset.connect(self.entry_price_input.clear)
        self.signals.entry_price_reset.connect(self.entry_price_value.clear)
        self._build_operation_hint()
        self._dock_top()
        QShortcut(QKeySequence("Esc"), self, activated=self.emergency.stop)
        self.log("第一版已啟動。目前禁止程式送出訂單。")
        QTimer.singleShot(350, self.read_sheet)

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

    def _minimize_after_operation(self) -> None:
        self.operation_hint.hide()
        self.showMinimized()

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
        self.always_on_top = QCheckBox("保持最上層")
        self.always_on_top.setChecked(False)
        self.always_on_top.toggled.connect(self.set_always_on_top)
        header.addWidget(title)
        header.addSpacing(22)
        header.addWidget(QLabel("方案"))
        self.profile_combo = QComboBox()
        self.profile_combo.setMinimumWidth(180)
        self.profile_combo.addItems(self.profiles.names())
        self.profile_combo.setCurrentText(self.profiles.active_name)
        header.addWidget(self.profile_combo)
        create_profile = QPushButton("建立")
        create_profile.clicked.connect(self.create_profile)
        header.addWidget(create_profile)
        save_profile = QPushButton("儲存")
        save_profile.clicked.connect(self.save_current_profile)
        header.addWidget(save_profile)
        rename_profile = QPushButton("重新命名")
        rename_profile.clicked.connect(self.rename_profile)
        header.addWidget(rename_profile)
        delete_profile = QPushButton("刪除")
        delete_profile.clicked.connect(self.delete_profile)
        header.addWidget(delete_profile)
        header.addStretch()
        header.addWidget(self.always_on_top)
        self.profile_combo.currentTextChanged.connect(self.switch_profile)
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
        data_box.setMinimumHeight(205)
        data_layout = QGridLayout(data_box)
        self.data_labels: dict[str, QLabel] = {}
        labels = [
            ("商品代碼", "symbol"), ("表格方向", "sheet_direction"),
            ("場內方向", "internal_direction"), ("場外方向", "external_direction"),
            ("場內手數", "internal_lot"), ("場外手數", "external_lot"),
            ("場內止盈點數", "internal_tp"), ("場外止盈點數", "external_tp"),
            ("場內止損點數", "internal_sl"), ("場外止損點數", "external_sl"),
        ]
        for index, (text, key) in enumerate(labels):
            row, section = divmod(index, 2)
            base = section * 2
            value = QLabel("-")
            value.setStyleSheet("font-weight: 700;")
            self.data_labels[key] = value
            data_layout.addWidget(QLabel(text), row, base)
            data_layout.addWidget(value, row, base + 1)
        self.entry_price_input = QLineEdit()
        self.entry_price_input.setPlaceholderText("例如 4174.64")
        self.entry_price_input.setFixedHeight(24)
        self.entry_price_input.returnPressed.connect(
            self.update_manual_entry_price
        )
        self.entry_price_value = QLabel("")
        self.entry_price_value.setStyleSheet("font-weight: 700;")
        update_entry_price = QPushButton("更新")
        update_entry_price.setFixedHeight(24)
        update_entry_price.clicked.connect(self.update_manual_entry_price)
        entry_editor = QWidget()
        entry_editor_layout = QHBoxLayout(entry_editor)
        entry_editor_layout.setContentsMargins(0, 0, 0, 0)
        entry_editor_layout.setSpacing(8)
        entry_editor_layout.addWidget(self.entry_price_input, 1)
        entry_editor_layout.addWidget(update_entry_price)
        data_layout.addWidget(QLabel("場內實際進場價"), 5, 0)
        data_layout.addWidget(self.entry_price_value, 5, 1)
        data_layout.addWidget(entry_editor, 5, 2, 1, 2)
        data_layout.setColumnMinimumWidth(0, 110)
        data_layout.setColumnMinimumWidth(2, 110)
        data_layout.setColumnStretch(1, 1)
        data_layout.setColumnStretch(3, 1)
        main.addWidget(data_box, 2, 0, 2, 1)

        actions = QGroupBox("操作")
        action_layout = QGridLayout(actions)
        definitions: list[tuple[str, Callable[[], None], int, int]] = [
            ("讀取試算表", self.read_sheet, 0, 0),
            ("試算表設定", self.open_settings, 0, 1),
            ("綁定場內視窗", lambda: self.bind_role_window("internal"), 0, 2),
            ("綁定場外視窗", lambda: self.bind_role_window("external"), 1, 0),
            ("校準 cTrader", lambda: self.open_calibration("cTrader"), 1, 1),
            ("校準 MT5", lambda: self.open_calibration("MT5"), 1, 2),
            (
                "校準 TradingView",
                lambda: self.open_calibration("TradingView"),
                2,
                0,
            ),
            ("填入場內", lambda: self.fill_role("internal"), 3, 0),
            ("填入場外", lambda: self.fill_role("external"), 3, 1),
            ("填入兩邊", self.fill_both, 3, 2),
        ]
        for text, callback, row, column in definitions:
            button = QPushButton(text)
            button.clicked.connect(callback)
            action_layout.addWidget(button, row, column)
        main.addWidget(actions, 1, 1, 3, 1)

        future = QGroupBox("進場後操作")
        future_layout = QHBoxLayout(future)
        sync_sl_tp_button = QPushButton("同步場外止盈止損")
        sync_sl_tp_button.clicked.connect(self.sync_external_sl_tp)
        future_layout.addWidget(sync_sl_tp_button)
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
        self.resize(width, 445)
        self.move(area.x() + (area.width() - width) // 2, area.y())

    def log(self, message: str) -> None:
        self.signals.log.emit(message)

    def _append_log(self, message: str) -> None:
        self.log_text.appendPlainText(f"[{time.strftime('%H:%M:%S')}] {message}")

    def _set_status(self, value: str) -> None:
        return

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

    def _start(
        self,
        name: str,
        task: Callable[[], None],
        *,
        hide_during: bool = True,
        restore_after: bool = True,
    ) -> None:
        if self.emergency.event.is_set():
            self.emergency.reset()
            self.signals.status.emit("就緒")
            self.log("已解除緊急停止，開始執行新的操作。")

        def worker() -> None:
            if hide_during:
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
                if hide_during:
                    if restore_after:
                        self.signals.operation_finished.emit()
                    else:
                        self.signals.operation_minimized.emit()

        threading.Thread(target=worker, daemon=True).start()

    def read_sheet(self) -> None:
        self._start("讀取中", self._read_sheet_task, hide_during=False)

    def _read_sheet_task(self) -> None:
        self.log("正在讀取 Google 試算表。")
        item = self.reader.read(self.store.data["sheet"])
        self.instruction = item
        self.manual_entry_price = None
        self.signals.entry_price_reset.emit()
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
        self._start(
            "填入場內" if role == "internal" else "填入場外",
            task,
            restore_after=False,
        )

    def fill_both(self) -> None:
        internal_platform = self.internal_platform.currentText()
        external_platform = self.external_platform.currentText()
        self._start(
            "填入兩邊",
            lambda: self._fill_both_task(internal_platform, external_platform),
            restore_after=False,
        )

    def _fill_both_task(
        self, internal_platform: str, external_platform: str
    ) -> None:
        item = self._require_instruction()
        self.automation.fill(internal_platform, "internal", item)
        self.automation.fill(external_platform, "external", item)

    def draw_tradingview(self) -> None:
        internal_platform = self.internal_platform.currentText()

        def task() -> None:
            item = self._require_instruction()
            self.automation.draw_tradingview(
                item,
                internal_platform=internal_platform,
                entry_price_override=self.manual_entry_price,
            )

        self._start("繪製 TradingView", task)

    def sync_external_sl_tp(self) -> None:
        internal_platform = self.internal_platform.currentText()
        external_platform = self.external_platform.currentText()

        def task() -> None:
            item = self._require_instruction()
            self.automation.sync_external_sl_tp(
                item,
                internal_platform=internal_platform,
                external_platform=external_platform,
                entry_price_override=self.manual_entry_price,
            )

        self._start("同步場外止盈止損", task)

    def update_manual_entry_price(self) -> None:
        raw = self.entry_price_input.text().replace(",", "").strip()
        if not raw:
            self.manual_entry_price = None
            self.entry_price_value.clear()
            self.log("已清除手動場內進場價，後續改回自動辨識。")
            return
        try:
            value = Decimal(raw)
        except InvalidOperation:
            QMessageBox.warning(self, "場內進場價", "請輸入有效數字。")
            return
        if value <= 0:
            QMessageBox.warning(self, "場內進場價", "進場價必須大於 0。")
            return
        self.manual_entry_price = value
        self.entry_price_input.setText(format(value, "f"))
        self.entry_price_value.setText(format(value, "f"))
        self.log(f"已更新手動場內實際進場價：{value}")
        self.draw_tradingview()

    def _require_instruction(self) -> TradeInstruction:
        if self.instruction is None:
            raise AutomationError("請先讀取 Google 試算表，再執行這項操作。")
        return self.instruction

    def open_calibration(self, platform: str) -> None:
        CalibrationDialog(self, platform).exec()

    def bind_role_window(self, role: str) -> None:
        platform = (
            self.internal_platform.currentText()
            if role == "internal"
            else self.external_platform.currentText()
        )
        role_text = "場內" if role == "internal" else "場外"
        current_pattern = (
            self.store.data["platforms"]
            .get(platform, {})
            .get("window_title", {})
            .get(role, "")
        )
        if current_pattern:
            QMessageBox.information(
                self,
                f"{role_text}視窗綁定狀態",
                "目前已綁定。\n"
                f"平台：{platform}\n"
                f"角色：{role_text}\n"
                f"視窗規則：{current_pattern}",
            )
            question = "是否要修改這個綁定？"
        else:
            QMessageBox.information(
                self,
                f"{role_text}視窗綁定狀態",
                f"目前未綁定 {role_text} {platform} 視窗。",
            )
            question = "是否要建立新的綁定？"
        answer = QMessageBox.question(
            self,
            f"修改{role_text}視窗綁定",
            question,
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            self.log(f"已取消修改{role_text} {platform} 視窗綁定。")
            return

        def task() -> None:
            self.log(
                f"準備綁定{role_text} {platform} 視窗。"
                "請在 3 秒內把滑鼠移到目標視窗上。"
            )
            for count in (3, 2, 1):
                self.log(f"綁定{role_text} {platform}：{count}")
                time.sleep(1)
            active = self.windows.window_at_cursor()
            pattern = _window_title_pattern(platform, active.title)
            self.store.data["platforms"][platform]["window_title"][role] = pattern
            self.save_config()
            self.automation.config = self.store.data
            self.log(
                f"已綁定{role_text} {platform} 視窗：{active.title}；"
                f"規則：{pattern}"
            )

        self._start(f"綁定{role_text}視窗", task, hide_during=False)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.automation.config = self.store.data
            self.log("設定已儲存。")

    def save_config(self) -> None:
        self.store.save()
        self.profiles.save_profile(self.profiles.active_name, self.store.data)

    def save_ui_state(self) -> None:
        self.store.data["ui"].update(
            {
                "internal_platform": self.internal_platform.currentText(),
                "external_platform": self.external_platform.currentText(),
            }
        )
        self.save_config()

    def switch_profile(self, name: str) -> None:
        if self._profile_switching or not name:
            return
        previous = self.profiles.active_name
        if name == previous:
            return
        try:
            self.save_ui_state()
            self.profiles.set_active(name)
            self.store.data = self.profiles.load_profile(name)
            self.store.save()
            self.automation.config = self.store.data
            self._apply_profile_ui()
            self.log(f"已切換方案：{name}")
            self.read_sheet()
        except Exception as exc:
            self._set_profile_combo(previous)
            QMessageBox.critical(self, "方案", str(exc))

    def create_profile(self) -> None:
        name, accepted = QInputDialog.getText(
            self, "建立方案", "方案名稱："
        )
        name = name.strip()
        if not accepted:
            return
        try:
            self.save_ui_state()
            self.profiles.create(name, self.store.data)
            self._refresh_profile_combo(name)
            self.log(f"已建立方案：{name}")
        except Exception as exc:
            QMessageBox.warning(self, "建立方案", str(exc))

    def save_current_profile(self) -> None:
        try:
            self.save_ui_state()
            self.log(f"已儲存方案：{self.profiles.active_name}")
        except Exception as exc:
            QMessageBox.warning(self, "儲存方案", str(exc))

    def rename_profile(self) -> None:
        old_name = self.profiles.active_name
        name, accepted = QInputDialog.getText(
            self, "重新命名方案", "新名稱：", text=old_name
        )
        name = name.strip()
        if not accepted or name == old_name:
            return
        try:
            self.profiles.rename(old_name, name)
            self._refresh_profile_combo(name)
            self.log(f"方案已重新命名：{old_name} → {name}")
        except Exception as exc:
            QMessageBox.warning(self, "重新命名方案", str(exc))

    def delete_profile(self) -> None:
        name = self.profiles.active_name
        answer = QMessageBox.question(
            self,
            "刪除方案",
            f"確定刪除「{name}」？",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer != QMessageBox.Yes:
            return
        try:
            active = self.profiles.delete(name)
            self.store.data = self.profiles.load_profile(active)
            self.store.save()
            self.automation.config = self.store.data
            self._refresh_profile_combo(active)
            self._apply_profile_ui()
            self.log(f"已刪除方案：{name}")
            self.read_sheet()
        except Exception as exc:
            QMessageBox.warning(self, "刪除方案", str(exc))

    def _apply_profile_ui(self) -> None:
        ui = self.store.data["ui"]
        self.internal_platform.blockSignals(True)
        self.external_platform.blockSignals(True)
        self.internal_platform.setCurrentText(ui["internal_platform"])
        self.external_platform.setCurrentText(ui["external_platform"])
        self.internal_platform.blockSignals(False)
        self.external_platform.blockSignals(False)
        self.instruction = None
        self.manual_entry_price = None
        self.entry_price_input.clear()
        self.entry_price_value.clear()
        for label in self.data_labels.values():
            label.setText("-")

    def _refresh_profile_combo(self, selected: str) -> None:
        self._profile_switching = True
        self.profile_combo.clear()
        self.profile_combo.addItems(self.profiles.names())
        self.profile_combo.setCurrentText(selected)
        self._profile_switching = False

    def _set_profile_combo(self, selected: str) -> None:
        self._profile_switching = True
        self.profile_combo.setCurrentText(selected)
        self._profile_switching = False

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
                profile = self.app.store.data["platforms"][self.platform]
                if self.platform == "TradingView":
                    stable_title = r"/\s*常用$"
                    point["window_title"] = stable_title
                    profile["window_title"]["internal"] = stable_title
                    profile["window_title"]["external"] = stable_title
                else:
                    point.pop("window_title", None)
                profile["points"][key] = point
                if (
                    self.platform != "TradingView"
                    and not profile["window_title"]["internal"]
                ):
                    profile["window_title"]["internal"] = re.escape(active.title)
                    profile["window_title"]["external"] = re.escape(active.title)
                self.app.save_config()
                self.app.profiles.sync_calibration_point(
                    self.platform, key, point
                )
                self.app.store.data = self.app.profiles.load_profile()
                self.app.store.save()
                self.app.automation.config = self.app.store.data
                self.app.log(
                    f"已儲存 {self.platform}「{key}」的相對位置："
                    f"({point['x']:.3f}, {point['y']:.3f})，"
                    f"精確像素 ({point['x_px']}, {point['y_px']})，"
                    f"螢幕座標 ({x}, {y})。"
                )
                if self.platform in {"GooeyTrade", "cTrader"}:
                    sync_target = "cTrader 與所有方案"
                elif self.platform in {"MT5", "BYBIT MT5", "原版MT5"}:
                    sync_target = "MT5 與所有方案"
                else:
                    sync_target = f"{self.platform} 與所有方案"
                self.app.log(f"已同步「{key}」到 {sync_target}。")
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
        for platform in (
            "cTrader",
            "MT5",
            "TradingView",
        ):
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
            self.app.save_config()
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "設定", str(exc))
