from __future__ import annotations

import copy
import os
import re
import sys
import threading
import time
import webbrowser
from dataclasses import replace
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Callable

from PySide6.QtCore import QEvent, QObject, QTimer, Qt, Signal, QSize
from PySide6.QtGui import (
    QColor,
    QCloseEvent,
    QIcon,
    QPainter,
    QPen,
    QKeySequence,
    QShortcut,
    QStandardItem,
    QStandardItemModel,
)
from PySide6.QtWidgets import (
    QAbstractItemView,
    QButtonGroup,
    QCheckBox,
    QApplication,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QLineEdit,
    QLayout,
    QListView,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPlainTextEdit,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSizePolicy,
    QStackedWidget,
    QTabWidget,
    QTabBar,
    QTextBrowser,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QToolButton,
    QVBoxLayout,
    QWidgetAction,
    QWidget,
)

from .automation import (
    PlatformAutomation, CTraderDecimalInputSuggestion,
)
from .auto_entry import (
    AutoEntryJournal, AutoEntryWorkflow, RecoveryRequired,
    DuplicateEntryDecisionRequired,
)
from .demo_broker_port import DemoUiBrokerPort
from .entry_status_report import build_entry_status_report
from .config import APP_DIR
from .field_detection import inspect_uia_window
from .calibration_scan import ScanReport, inspect_all_targets
from .calibration_confirm import (
    CalibrationConfirmationError, candidate_calibration_points,
    save_confirmed_points,
)
from .post_entry_scan import PostEntryReport, POST_ENTRY_TARGETS, inspect_post_entry
from .position_calibration import (
    POSITION_GRID_KEYS, POSITION_EDIT_KEYS,
    scan_position_grid, select_broker_main_window,
    select_modify_dialog, scan_open_modify_dialog,
)
from .ui_inspector import CandidateOutline, hover_snapshot, process_id_for_window
from .config import (
    ConfigStore, ProfileStore, ctrader_mode_for_profile,
    set_ctrader_mode_for_profile,
)
from .models import TradeInstruction, ValidationError
from .automation import REQUIRED_POINTS
from .sheets import SheetReader
from .trading_day import trading_day_key
from .ui_theme import MAIN_THEME, themed_icon
from .delayed_help import DelayedHoverHelp
from .calibration_status import completion
from .progress_ruler import (
    AccountRuler, SHEET_RULER_REFERENCES, calculate_ruler_from_sheet,
    decimal_value, money,
)
from .window_chrome import CompactTitleBar, FramelessNativeMixin, WindowChromeButton
from .windows import (
    AutomationError,
    EmergencyController,
    EmergencyStopped,
    WindowController,
    WindowInfo,
)


PLATFORMS = ("cTrader", "MT5")
APP_BASE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent.parent))
APP_ICON = APP_BASE / "assets" / "app.ico"
MT5_TARGETS = [
    ("positions_entry_price", "已進場持倉的進場價（Trade 列，未開修改視窗）"),
    ("new_order_button", "新訂單按鈕（填單前必需）"),
    ("lot_input", "交易量輸入欄"),
    ("ask_price", "目前價格（單一參考價格）"),
    ("trade_tab", "MT5 交易欄位 / 交易分頁"),
    ("sl_input", "止損價格輸入欄"),
    ("tp_input", "止盈價格輸入欄"),
    ("order_submit_buy", "確認進場：Buy by Market（送單鍵）"),
    ("order_submit_sell", "確認進場：Sell by Market（送單鍵）"),
    ("position_modify_confirm", "修改持倉：確認／套用 SL／TP 按鈕"),
    ("position_sl_input", "持倉修改視窗的止損價格輸入欄"),
    ("position_tp_input", "持倉修改視窗的止盈價格輸入欄"),
    ("position_order_lot", "場外已進場訂單手數（第一筆）"),
    ("position_order_row", "持倉列表的 SL 欄位（雙擊開啟持倉修改視窗）"),
]
CALIBRATION_TARGETS = {
    "GooeyTrade": [
        ("account_number", "帳號數字位置"),
        ("lot_input", "倉位／手數輸入欄"),
        ("sl_checkbox", "止損啟用勾選框"),
        ("sl_input", "止損點數輸入欄"),
        ("tp_checkbox", "止盈啟用勾選框"),
        ("tp_input", "止盈點數輸入欄"),
        ("buy_button", "買入方向按鈕"),
        ("sell_button", "賣出方向按鈕"),
        ("positions_entry_price", "持倉成交價懸浮位置（OCR 使用）"),
        ("position_sl_input", "持倉修改視窗的止損價格輸入欄"),
        ("position_tp_input", "持倉修改視窗的止盈價格輸入欄"),
        ("position_order_lot", "場外已進場訂單手數（第一筆）"),
        ("position_order_row", "已進場訂單列（雙擊開啟修改視窗）"),
    ],
    "cTrader": [
        ("account_number", "帳號數字位置"),
        ("lot_input", "倉位／手數輸入欄"),
        ("sl_checkbox", "止損啟用勾選框"),
        ("sl_input", "止損點數輸入欄"),
        ("tp_checkbox", "止盈啟用勾選框"),
        ("tp_input", "止盈點數輸入欄"),
        ("buy_button", "買入方向按鈕"),
        ("sell_button", "賣出方向按鈕（只切換方向，不送單）"),
        ("order_submit_button", "確認進場：真正送出 cTrader 訂單的按鈕"),
        ("positions_entry_price", "持倉成交價懸浮位置（第二版 OCR 使用）"),
        ("position_sl_input", "持倉修改視窗的止損價格輸入欄"),
        ("position_tp_input", "持倉修改視窗的止盈價格輸入欄"),
        ("position_order_lot", "已進場持倉手數（需唯一持倉）"),
        ("position_order_row", "持倉列表 TP 欄位（雙擊開啟修改視窗）"),
        ("position_modify_confirm", "修改持倉視窗的 Protect／套用按鈕"),
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
    "internal_entry_price": "場內進場點位",
    "final_external_sl_price": "場外最終止損價",
    "final_external_tp_price": "場外最終止盈價",
    "daily_pnl": "每日獲利/虧損",
    "internal_balance": "場內餘額",
    "original_sl_points": "原本止損點數",
    "expected_sl_points": "預期止損點/%數",
    "expected_sl_percent": "預期止損%",
}


def _resolve_relative_decimal(raw: str, base: Decimal | None) -> Decimal:
    text = raw.replace(",", "").strip()
    if text.startswith(("=+", "=-")):
        return (base or Decimal("0")) + Decimal(text[1:])
    return Decimal(text)


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
    sheet_note = Signal(str)
    ruler_sheet = Signal(object)
    operation_started = Signal()
    operation_finished = Signal()
    operation_minimized = Signal()
    entry_price_reset = Signal()
    parameter_inputs_reset = Signal(object)
    parameter_write_busy = Signal(bool)
    parameter_write_retry = Signal()
    external_price_result = Signal(object)
    ctrader_decimal_suggestion = Signal(object)
    duplicate_entry_decision = Signal(object)
    window_binding_result = Signal(object)
    auto_entry_result = Signal(object)


class ProfileItemDelegate(QStyledItemDelegate):
    def initStyleOption(self, option: QStyleOptionViewItem, index) -> None:
        super().initStyleOption(option, index)
        option.text = f"☰  {option.text}"


class ChevronCombo(QComboBox):
    """Native QComboBox behaviour, with an always-visible optical chevron.

    This only draws the dropdown affordance; it does not change the underlying
    model, popup, keyboard navigation, or selected text.
    """
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        ink = QColor("#b2a9ba" if self.isEnabled() else "#6e6973")
        pen = QPen(ink, 1.5)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        x = self.width() - 15
        y = self.height() / 2
        painter.drawLine(int(x - 4), int(y - 2), int(x), int(y + 2))
        painter.drawLine(int(x), int(y + 2), int(x + 4), int(y - 2))
        painter.end()


class ToolbarMenuButton(QToolButton):
    """Menu trigger with a restrained chevron, never a boxed split-button."""
    def paintEvent(self, event) -> None:
        super().paintEvent(event)
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        pen = QPen(QColor("#aba5ae" if self.isEnabled() else "#6e6973"), 1.4)
        pen.setCapStyle(Qt.RoundCap)
        pen.setJoinStyle(Qt.RoundJoin)
        painter.setPen(pen)
        x = self.width() - 11
        y = self.height() // 2
        painter.drawLine(x - 3, y - 1, x, y + 2)
        painter.drawLine(x, y + 2, x + 3, y - 1)
        painter.end()


class DraggableProfileCombo(ChevronCombo):
    orderChanged = Signal(list)

    def __init__(self):
        super().__init__()
        self._model = QStandardItemModel(self)
        self.setModel(self._model)
        view = QListView()
        view.setDragDropMode(QAbstractItemView.InternalMove)
        view.setDefaultDropAction(Qt.MoveAction)
        view.setDragDropOverwriteMode(False)
        view.setSelectionMode(QAbstractItemView.SingleSelection)
        view.setItemDelegate(ProfileItemDelegate(view))
        self.setView(view)
        self._model.rowsMoved.connect(self._emit_order)
        self._model.layoutChanged.connect(self._emit_order)

    def set_names(self, names: list[str]) -> None:
        self._model.clear()
        for name in names:
            item = QStandardItem(name)
            item.setDragEnabled(True)
            item.setDropEnabled(False)
            self._model.appendRow(item)

    def _emit_order(self) -> None:
        self.orderChanged.emit(
            [self.itemText(index) for index in range(self.count())]
        )


class SheetNoteIndicator(QLabel):
    def __init__(self) -> None:
        super().__init__("")
        self._note = ""
        self.setFixedSize(22, 22)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip("試算表提醒")

        # Build the popup exactly once. Recreating it in paintEvent would
        # discard previous hover content whenever the titlebar repaints.
        self._popup = QWidget(None)
        self._popup.setWindowFlags(
            Qt.Tool
            | Qt.FramelessWindowHint
            | Qt.WindowStaysOnTopHint
            | Qt.WindowDoesNotAcceptFocus
        )
        self._popup.setFixedSize(520, 230)
        self._popup.setStyleSheet(
            "QWidget {"
            "background: #222;"
            "border: 1px solid #777;"
            "border-radius: 6px;"
            "}"
            "QPlainTextEdit {"
            "background: transparent;"
            "border: none;"
            "color: #f2f2f2;"
            "font-size: 13px;"
            "padding: 8px;"
            "}"
        )
        popup_layout = QVBoxLayout(self._popup)
        popup_layout.setContentsMargins(8, 8, 8, 8)
        self._popup_text = QPlainTextEdit()
        self._popup_text.setReadOnly(True)
        popup_layout.addWidget(self._popup_text)
        self._popup.installEventFilter(self)
        self._popup_text.installEventFilter(self)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._hide_if_left)
        self.set_note("")

    def paintEvent(self, event) -> None:
        """Draw centered circle and ! without relying on a font baseline."""
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        color = QColor("#d8d4db" if self.isEnabled() else "#77727d")
        painter.setPen(QPen(color, 1.3))
        painter.setBrush(Qt.NoBrush)
        center_x = self.width() / 2
        center_y = self.height() / 2
        painter.drawEllipse(2, 2, self.width() - 4, self.height() - 4)
        painter.setPen(QPen(color, 1.7, Qt.SolidLine, Qt.RoundCap))
        painter.drawLine(int(center_x), int(center_y - 4), int(center_x), int(center_y + 1))
        painter.setPen(Qt.NoPen)
        painter.setBrush(color)
        painter.drawEllipse(int(center_x - 1), int(center_y + 4), 2, 2)
        painter.end()

    def set_note(self, value: str) -> None:
        self._note = str(value or "").strip()
        self.setEnabled(bool(self._note))
        self._popup_text.setPlainText(self._note)
        if not self._note:
            self._popup.hide()

    def enterEvent(self, event) -> None:
        self._hide_timer.stop()
        if self._note:
            self._show_popup()
        super().enterEvent(event)

    def leaveEvent(self, event) -> None:
        self._schedule_hide()
        super().leaveEvent(event)

    def eventFilter(self, watched, event) -> bool:
        if watched in {self._popup, self._popup_text}:
            if event.type() == QEvent.Enter:
                self._hide_timer.stop()
            elif event.type() == QEvent.Leave:
                self._schedule_hide()
        return super().eventFilter(watched, event)

    def _show_popup(self) -> None:
        point = self.mapToGlobal(self.rect().bottomLeft())
        screen = QApplication.screenAt(point) or QApplication.primaryScreen()
        if screen is not None:
            area = screen.availableGeometry()
            x = min(point.x(), area.right() - self._popup.width())
            y = point.y() + 8
            if y + self._popup.height() > area.bottom():
                y = self.mapToGlobal(self.rect().topLeft()).y() - self._popup.height() - 8
            point.setX(max(area.left(), x))
            point.setY(max(area.top(), y))
        self._popup.move(point)
        self._popup.show()
        self._popup.raise_()

    def _schedule_hide(self) -> None:
        self._hide_timer.start(180)

    def _hide_if_left(self) -> None:
        if self.underMouse() or self._popup.underMouse() or self._popup_text.underMouse():
            return
        self._popup.hide()


class TradingHelperApp(FramelessNativeMixin, QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("對沖小幫手")
        self.setObjectName("tradingHelperMain")
        self.setWindowFlags(Qt.Window | Qt.FramelessWindowHint)
        if APP_ICON.exists():
            self.setWindowIcon(QIcon(str(APP_ICON)))
        self.resize(1150, 630)
        self.setMinimumWidth(1020)
        self.setMinimumHeight(630)
        self.store = ConfigStore()
        self.profiles = ProfileStore(self.store.data)
        self.store.data = self.profiles.load_profile()
        self.store.save()
        self._profile_switching = False
        self.reader = SheetReader()
        self.instruction: TradeInstruction | None = None
        self.ruler_sheet_values: dict[str, dict[str, str]] | None = None
        self.ruler_sheet_status = "等待試算表資料"
        # A typed balance/P&L is a draft until that field's Enter key or
        # the existing 更新 button confirms it for the visual ruler.
        self._ruler_confirmed_parameters = {
            "internal_balance": "", "daily_pnl": "",
        }
        self.manual_entry_price: Decimal | None = None
        # A main-page price becomes the manual override only AFTER the sheet
        # read-back confirms the requested price; entering text isn't enough.
        self._primary_entry_price_pending: Decimal | None = None
        self._last_log_trading_day: str | None = None
        self._parameter_write_active = False
        self._parameter_write_pending = False
        # Only one fill operation may control broker windows at any time.
        self._fill_task_lock = threading.Lock()
        self._fill_confirmed_text: dict[str, str] = {}
        self._fill_waiting_for_sheet: dict | None = None
        self._parameter_write_active_signature: tuple[tuple[str, str], ...] | None = None
        self._parameter_write_pending_signature: tuple[tuple[str, str], ...] | None = None
        self._parameter_write_last_signature: tuple[tuple[str, str], ...] | None = None
        self.signals = UiSignals()
        self.signals.log.connect(self._append_log)
        self.signals.status.connect(self._set_status)
        self.signals.error.connect(self._show_error)
        self.signals.ctrader_decimal_suggestion.connect(
            self._show_ctrader_decimal_suggestion
        )
        self.signals.duplicate_entry_decision.connect(
            self._show_duplicate_entry_decision
        )
        self.signals.instruction.connect(self._show_instruction)
        self.signals.sheet_note.connect(self._show_sheet_note)
        self.signals.ruler_sheet.connect(self._show_ruler_sheet)
        self.signals.operation_started.connect(self._hide_for_operation)
        self.signals.operation_finished.connect(self._restore_after_operation)
        self.signals.operation_minimized.connect(self._minimize_after_operation)
        self.signals.window_binding_result.connect(self._on_window_binding_result)
        self.signals.auto_entry_result.connect(self._queue_auto_entry_result)
        self._window_binding_dialog = None
        self._auto_entry_receipt = None
        self.emergency = EmergencyController(self._emergency_callback)
        self.windows = WindowController(self.emergency)
        threading.Thread(target=self.windows.warm_ocr, daemon=True).start()
        self.automation = PlatformAutomation(
            self.store.data, self.windows, self.emergency, self.log,
            profile_name=self.profiles.active_name,
        )
        self._build()
        # Style only our test helper widgets; all existing business callbacks remain intact.
        self.setStyleSheet(MAIN_THEME)
        self.signals.entry_price_reset.connect(self.entry_price_input.clear)
        self.signals.entry_price_reset.connect(self.entry_price_value.clear)
        self.signals.parameter_inputs_reset.connect(self._clear_parameter_inputs)
        self.signals.parameter_write_busy.connect(self._set_parameter_write_busy)
        self.signals.parameter_write_retry.connect(self.update_all_trade_parameters)
        self.signals.external_price_result.connect(self._show_external_price_result)
        self._build_operation_hint()
        self._dock_top()
        QApplication.instance().installEventFilter(self)
        QShortcut(QKeySequence("Esc"), self, activated=self.emergency.stop)
        self.log("對沖小幫手已啟動。目前禁止程式送出訂單。")
        # Some Windows launcher/chrome combinations apply startup placement
        # *after* QWidget.__init__. Reapply the compact size once shown.
        QTimer.singleShot(80, self._dock_top)
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
        # Three independent, directly accessible workspaces. Trade is a
        # compact NON-SCROLLING page; lower-frequency controls live in Edit.
        self.main_pages = QStackedWidget(self)
        self.main_pages.setObjectName("mainPages")
        self.setCentralWidget(self.main_pages)
        central = QWidget()
        central.setObjectName("appSurface")
        self.trade_page = central
        self.main_pages.addWidget(central)
        main = QVBoxLayout(central)
        main.setContentsMargins(22, 14, 22, 10)
        main.setSpacing(9)

        # Phase 3: one compact, truly window-integrated titlebar. The main
        # scrollable content starts immediately beneath it, with no second
        # dashboard toolbar row.
        self.title_bar = CompactTitleBar(self)
        top_row = QHBoxLayout(self.title_bar)
        top_row.setContentsMargins(10, 2, 3, 2)
        top_row.setSpacing(5)
        self.setMenuWidget(self.title_bar)

        title = QLabel("對沖小幫手")
        title.setObjectName("appTitle")
        title.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        top_row.addWidget(title)
        top_row.addSpacing(6)
        self.page_nav: dict[str, QPushButton] = {}
        for title in ("交易", "編輯", "紀錄"):
            nav = QPushButton(title)
            nav.setObjectName("nav" + {"交易":"Trade","編輯":"Edit","紀錄":"Records"}[title])
            nav.setCheckable(True)
            nav.setChecked(title == "交易")
            nav.clicked.connect(lambda _checked=False, name=title: self.switch_workspace(name))
            top_row.addWidget(nav)
            self.page_nav[title] = nav
        top_row.addSpacing(5)
        label_profile = QLabel("目前方案")
        label_profile.setObjectName("moduleKicker")
        label_profile.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        top_row.addWidget(label_profile)
        self.profile_combo = DraggableProfileCombo()
        self.profile_combo.setObjectName("headerProfileCombo")
        self.profile_combo.setMinimumWidth(133)
        self.profile_combo.setMaximumWidth(215)
        self.profile_combo.set_names(self.profiles.names())
        self.profile_combo.setCurrentText(self.profiles.active_name)
        top_row.addWidget(self.profile_combo)

        self.profile_manage_button = ToolbarMenuButton()
        self.profile_manage_button.setObjectName("profile_manage_button")
        self.profile_manage_button.setText("管理")
        self.profile_manage_button.setIcon(themed_icon("settings", "#b8afb9", 16))
        self.profile_manage_button.setIconSize(QSize(16, 16))
        self.profile_manage_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.profile_manage_button.setToolTip("建立、儲存、重新命名或刪除目前方案")
        self.profile_manage_button.setPopupMode(QToolButton.InstantPopup)
        self.profile_manage_menu = QMenu(self.profile_manage_button)
        for label, icon_name, callback in (
            ("建立新方案", "plus", self.create_profile),
            ("儲存目前方案", "save", self.save_current_profile),
            ("重新命名目前方案", "edit", self.rename_profile),
        ):
            action = self.profile_manage_menu.addAction(
                themed_icon(icon_name, "#c4d6e8", 16), label
            )
            action.triggered.connect(callback)
        self.profile_manage_menu.addSeparator()
        delete_action = self.profile_manage_menu.addAction(
            themed_icon("trash", "#e69a9c", 16), "刪除目前方案"
        )
        delete_action.triggered.connect(self.delete_profile)
        self.profile_manage_button.setMenu(self.profile_manage_menu)
        top_row.addWidget(self.profile_manage_button)
        top_row.addStretch(1)

        self.sheet_note_indicator = SheetNoteIndicator()
        top_row.addWidget(self.sheet_note_indicator)
        help_button = QPushButton("Help")
        help_button.setObjectName("headerHelpButton")
        help_button.setIcon(themed_icon("help"))
        help_button.setIconSize(QSize(16, 16))
        help_button.clicked.connect(self.open_help)
        top_row.addWidget(help_button)
        sheet_url_button = QPushButton("打開試算表")
        sheet_url_button.setObjectName("headerSheetButton")
        sheet_url_button.setIcon(themed_icon("link"))
        sheet_url_button.setIconSize(QSize(16, 16))
        sheet_url_button.clicked.connect(self.open_sheet_url)
        top_row.addWidget(sheet_url_button)

        self.auto_entry_on_fill_both = QCheckBox("兩邊自動進場")
        self.auto_entry_on_fill_both.setObjectName("auto_entry_on_fill_both")
        self.auto_entry_on_fill_both.setToolTip(
            "僅在按「填入兩邊」時生效；先核對雙 Demo 帳戶與所有欄位，"
            "確認唯一持倉識別後才允許嘗試送單；可能真的在 Demo 開倉。"
            "任何結果不確定會停止，不會重送或自行平倉。"
        )
        # Restore the user's previously confirmed preference. This only
        # checks a box: starting the GUI never runs fill/order callbacks.
        self.auto_entry_on_fill_both.setChecked(
            bool(self.store.data["ui"].get("auto_entry_on_fill_both",False))
        )
        self.auto_entry_on_fill_both.toggled.connect(self._confirm_auto_entry_toggle)
        # A single-line safety toggle replaces the former full-width row.
        self.auto_entry_on_fill_both.setToolTip(
            self.auto_entry_on_fill_both.toolTip()
            + " 〔送單流程待設定〕"
        )
        # Toggle is placed in the compact trade action row below.

        self.display_settings_button = ToolbarMenuButton()
        self.display_settings_button.setObjectName("display_settings_button")
        self.display_settings_button.setText("顯示設定")
        self.display_settings_button.setIcon(themed_icon("sliders", "#b8afb9", 16))
        self.display_settings_button.setIconSize(QSize(16, 16))
        self.display_settings_button.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
        self.display_settings_button.setToolTip("TradingView 顯示設定及視窗置頂")
        self.display_settings_button.setPopupMode(QToolButton.InstantPopup)
        display_menu = QMenu(self.display_settings_button)
        display_container = QWidget(display_menu)
        display_layout = QVBoxLayout(display_container)
        display_layout.setContentsMargins(14, 10, 14, 10)
        display_layout.setSpacing(10)
        self.tv_draw_internal = QCheckBox("TV 顯示場內", display_container)
        self.tv_draw_internal.setChecked(
            bool(self.store.data["ui"].get("tv_draw_internal", False))
        )
        self.tv_draw_internal.toggled.connect(lambda _: self.save_ui_state())
        display_layout.addWidget(self.tv_draw_internal)
        self.show_calibration_badges = QCheckBox(
            "顯示校準未完成紅點", display_container
        )
        self.show_calibration_badges.setChecked(
            bool(self.store.data["ui"].get("show_calibration_badges", True))
        )
        self.show_calibration_badges.toggled.connect(
            lambda _: self.save_ui_state()
        )
        self.show_calibration_badges.toggled.connect(
            lambda _: self._refresh_calibration_badges()
        )
        display_layout.addWidget(self.show_calibration_badges)
        self.always_on_top = QCheckBox("保持最上層", display_container)
        self.always_on_top.setChecked(False)
        self.always_on_top.toggled.connect(self.set_always_on_top)
        display_layout.addWidget(self.always_on_top)
        display_action = QWidgetAction(display_menu)
        display_action.setDefaultWidget(display_container)
        display_menu.addAction(display_action)
        self.display_settings_button.setMenu(display_menu)
        top_row.addWidget(self.display_settings_button)
        top_row.addSpacing(3)

        self.chrome_minimize = WindowChromeButton("minimize", self.title_bar)
        self.chrome_maximize = WindowChromeButton("maximize", self.title_bar)
        self.chrome_close = WindowChromeButton("close", self.title_bar)
        self.chrome_minimize.clicked.connect(self.showMinimized)
        self.chrome_maximize.clicked.connect(self.toggle_maximized)
        self.chrome_close.clicked.connect(self.close)
        chrome_controls = QHBoxLayout()
        chrome_controls.setContentsMargins(0, 0, 0, 0)
        chrome_controls.setSpacing(1)
        chrome_controls.addWidget(self.chrome_minimize)
        chrome_controls.addWidget(self.chrome_maximize)
        chrome_controls.addWidget(self.chrome_close)
        top_row.addLayout(chrome_controls)

        self.profile_combo.currentTextChanged.connect(self.switch_profile)
        self.profile_combo.orderChanged.connect(self.reorder_profiles)

        # One unified market-information area: platform selectors above the
        # same panel's complete sheet data, instead of two stacked cards.
        platforms = QWidget()
        platforms.setObjectName("platformSelectorRow")
        platform_layout = QHBoxLayout(platforms)
        platform_layout.setContentsMargins(0, 1, 0, 2)
        platform_layout.setSpacing(18)
        self.internal_platform = ChevronCombo()
        self.internal_platform.addItems(PLATFORMS)
        self.internal_platform.setCurrentText(self.store.data["ui"]["internal_platform"])
        self.external_platform = ChevronCombo()
        self.external_platform.addItems(PLATFORMS)
        self.external_platform.setCurrentText(self.store.data["ui"]["external_platform"])
        # Match the exact same two equal-width columns used by the trade data.
        # Unlike the previous four independent widgets, these headers cannot
        # drift out of alignment when the window is resized.
        for title, combo in (("場內", self.internal_platform),
                             ("場外", self.external_platform)):
            header_cell = QWidget(platforms)
            header_cell.setObjectName("tradePlatformCell")
            header_layout = QHBoxLayout(header_cell)
            header_layout.setContentsMargins(0, 0, 0, 0)
            header_layout.setSpacing(7)
            header_label = QLabel(title)
            header_label.setProperty("role", "caption")
            header_layout.addWidget(header_label)
            combo.setMinimumWidth(115)
            combo.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
            header_layout.addWidget(combo, 1)
            platform_layout.addWidget(header_cell, 1)

        # An inline section heading keeps Refresh on the very same baseline.
        # The QGroupBox remains for object identity / regressions, but its
        # painted title is replaced by this explicit, compact toolbar.
        data_box = QGroupBox("")
        data_box.setObjectName("dataCard")
        data_box.setFixedHeight(295)
        data_shell = QVBoxLayout(data_box)
        data_shell.setContentsMargins(6, 3, 6, 5)
        data_shell.setSpacing(4)
        reload_header = QWidget(data_box)
        reload_header.setObjectName("reloadToolbar")
        reload_layout = QHBoxLayout(reload_header)
        reload_layout.setContentsMargins(0, 0, 0, 0)
        reload_layout.setSpacing(4)
        data_heading = QLabel("交易資訊", reload_header)
        data_heading.setObjectName("tradeDataHeading")
        reload_layout.addWidget(data_heading)
        reload_layout.addStretch(1)
        data_shell.addWidget(reload_header)
        sheet_separator = QFrame(data_box)
        sheet_separator.setObjectName("dataSeparator")
        sheet_separator.setFrameShape(QFrame.HLine)
        data_shell.addWidget(sheet_separator)
        sheet_values = QWidget(data_box)
        sheet_values.setObjectName("sheetDataValues")
        data_layout = QVBoxLayout(sheet_values)
        data_layout.setContentsMargins(0, 8, 0, 3)
        data_layout.setSpacing(6)
        data_shell.addWidget(sheet_values, 1)
        self.data_labels: dict[str, QLabel] = {}

        def info_item(text: str, key: str) -> QWidget:
            """Only relocate the 11 existing QLabel values; retain every key."""
            row_widget = QWidget(sheet_values)
            row_widget.setObjectName("tradeDataPair")
            pair = QHBoxLayout(row_widget)
            pair.setContentsMargins(0, 0, 0, 0)
            pair.setSpacing(9)
            name_label = QLabel(text)
            name_label.setProperty("role", "caption")
            value = QLabel("-")
            value.setProperty("role", "value")
            value.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.data_labels[key] = value
            pair.addWidget(name_label)
            pair.addStretch(1)
            pair.addWidget(value)
            return row_widget

        # Platform selectors are the first content row, with wider inputs.
        # Keep exactly two matched columns for the detailed data below.
        data_layout.addWidget(platforms)
        data_layout.addSpacing(5)
        # Three equally spaced, optically centered summary cells. Labels
        # and values share the same center; none are right-pinned anymore.
        summary_layout = QHBoxLayout()
        summary_layout.setSpacing(18)
        for text, key in (
            ("商品", "symbol"),
            ("表格方向", "sheet_direction"),
            ("原始 SL", "original_sl_points"),
        ):
            summary_cell = QWidget(sheet_values)
            summary_cell.setObjectName("centeredSummaryCell")
            summary_cell_layout = QVBoxLayout(summary_cell)
            summary_cell_layout.setContentsMargins(0, 2, 0, 3)
            summary_cell_layout.setSpacing(3)
            summary_name = QLabel(text)
            summary_name.setProperty("role", "caption")
            summary_name.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            summary_value = QLabel("-")
            summary_value.setProperty("role", "value")
            summary_value.setAlignment(Qt.AlignHCenter | Qt.AlignVCenter)
            self.data_labels[key] = summary_value
            summary_cell_layout.addWidget(summary_name)
            summary_cell_layout.addWidget(summary_value)
            summary_layout.addWidget(summary_cell, 1)
        data_layout.addLayout(summary_layout)

        data_divider = QFrame(sheet_values)
        data_divider.setObjectName("infoInnerDivider")
        data_divider.setFrameShape(QFrame.HLine)
        data_layout.addWidget(data_divider)
        # The two detail lists retain matching column stretches beneath
        # the prominent platform-selection row and centered sheet summary.
        side_by_side = QHBoxLayout()
        side_by_side.setSpacing(24)
        for entries in (
            (("方向", "internal_direction"), ("手數", "internal_lot"),
             ("止盈 TP", "internal_tp"), ("止損 SL", "internal_sl")),
            (("方向", "external_direction"), ("手數", "external_lot"),
             ("止盈 TP", "external_tp"), ("止損 SL", "external_sl")),
        ):
            side = QVBoxLayout()
            side.setSpacing(4)
            for text, key in entries:
                side.addWidget(info_item(text, key))
            side_by_side.addLayout(side, 1)
        data_layout.addLayout(side_by_side)
        self.entry_price_input = QLineEdit()
        self.entry_price_input.returnPressed.connect(self.update_manual_entry_price)
        self.entry_price_value = QLabel("")
        # Trading cards are assembled into the final two-column layout below.

        parameter_box = QGroupBox("交易參數")
        parameter_box.setObjectName("parameterCard")
        parameter_box.setMinimumHeight(0)
        parameter_layout = QGridLayout(parameter_box)
        parameter_layout.setContentsMargins(4, 13, 4, 5)
        parameter_layout.setHorizontalSpacing(16)
        parameter_layout.setVerticalSpacing(9)
        self.internal_direction_input = ChevronCombo()
        self.internal_direction_input.addItem("買入", "BUY")
        self.internal_direction_input.addItem("賣出", "SELL")
        self.internal_direction_input.currentIndexChanged.connect(
            self.update_trade_direction
        )
        self.parameter_inputs: dict[str, QLineEdit] = {}
        self.parameter_update_button = QPushButton("更新")
        self.parameter_update_button.setIcon(themed_icon("refresh"))
        self.parameter_update_button.clicked.connect(self._confirm_ruler_inputs)
        self.parameter_update_button.clicked.connect(self.update_all_trade_parameters)
        self.daily_pnl_history_button = QPushButton("盈虧紀錄")
        self.daily_pnl_history_button.setIcon(themed_icon("history"))
        self.daily_pnl_history_button.setToolTip("每日獲利/虧損紀錄")
        self.daily_pnl_history_button.clicked.connect(self.show_daily_pnl_history)
        self.preview_sl_tp_button = QPushButton("查看止盈/損")
        self.preview_sl_tp_button.setIcon(themed_icon("eye"))
        self.preview_sl_tp_button.setToolTip("查看場內外止盈止損")
        self.preview_sl_tp_button.clicked.connect(self.show_internal_external_sl_tp)
        def parameter_cell(label_text: str, widget: QWidget) -> QWidget:
            cell = QWidget()
            layout = QHBoxLayout(cell)
            layout.setContentsMargins(0, 0, 0, 0)
            layout.setSpacing(6)
            label = QLabel(label_text)
            label.setProperty("role", "caption")
            label.setMinimumWidth(91)
            layout.addWidget(label)
            layout.addWidget(widget, 1)
            return cell

        parameter_layout.addWidget(
            parameter_cell("場內多空", self.internal_direction_input),
            0,
            0,
        )
        parameter_fields = [
            ("場內餘額", "internal_balance"),
            ("每日獲利/虧損", "daily_pnl"),
            ("預期止損點/%數", "expected_sl_combined"),
            ("場內進場點位", "internal_entry_price"),
        ]
        positions = [(0, 1), (1, 0), (1, 1), (2, 0)]
        for (label, key), (row, column) in zip(parameter_fields, positions):
            entry = QLineEdit()
            entry.setFixedHeight(34)
            if key == "internal_entry_price":
                entry.setToolTip(
                    "主畫面的唯一手動進場價入口。輸入後按 Enter 或「更新」"
                    "寫回試算表；不會因此自動繪製 TV 或送單。"
                )
            if key in ("internal_balance", "daily_pnl"):
                entry.returnPressed.connect(
                    lambda key=key: self._confirm_ruler_field(key)
                )
            entry.returnPressed.connect(self._confirm_fill_text_inputs)
            entry.returnPressed.connect(self.update_all_trade_parameters)
            self.parameter_inputs[key] = entry
            parameter_layout.addWidget(parameter_cell(label, entry), row, column)
        # Place compact secondary actions DIRECTLY next to the entry-price
        # field, sharing that row's visual baseline. No separate button row.
        param_inline = QWidget(parameter_box)
        param_inline.setObjectName("parameterInlineActions")
        inline_actions_layout = QHBoxLayout(param_inline)
        inline_actions_layout.setContentsMargins(0, 0, 0, 0)
        inline_actions_layout.setSpacing(7)
        self.preview_sl_tp_button.setObjectName("paramPreviewAction")
        self.parameter_update_button.setObjectName("paramUpdateAction")
        inline_actions_layout.addStretch(1)
        for action_button, width in (
            (self.preview_sl_tp_button, 114),
            (self.parameter_update_button, 72),
        ):
            action_button.setMinimumWidth(0)
            action_button.setFixedWidth(width)
            action_button.setFixedHeight(31)
            action_button.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Fixed)
            inline_actions_layout.addWidget(action_button)
        parameter_layout.addWidget(param_inline, 2, 1)
        parameter_layout.setColumnStretch(0, 1)
        parameter_layout.setColumnStretch(1, 1)
        # Parameter controls will live above the fill actions on the right.

        actions = QGroupBox("交易操作")
        actions.setObjectName("actionsCard")
        action_layout = QGridLayout(actions)
        action_layout.setContentsMargins(4, 18, 4, 5)
        action_layout.setHorizontalSpacing(10)
        action_layout.setVerticalSpacing(9)
        self.parameter_locked_buttons: list[QPushButton] = [
            self.daily_pnl_history_button
        ]
        definitions: list[tuple[str, Callable[[], None], int, int]] = [
            ("讀取試算表", self.read_sheet, 0, 0),
            ("試算表設定", self.open_settings, 0, 1),
            ("綁定場內視窗", lambda: self.bind_role_window("internal"), 1, 0),
            ("綁定場外視窗", lambda: self.bind_role_window("external"), 1, 1),
            ("校準 cTrader", lambda: self.open_calibration("cTrader"), 2, 0),
            ("校準 MT5", lambda: self.open_calibration("MT5"), 2, 1),
            (
                "校準 TradingView",
                lambda: self.open_calibration("TradingView"),
                2,
                2,
            ),
            ("填入場內", lambda: self.fill_role("internal"), 3, 0),
            ("填入場外", lambda: self.fill_role("external"), 3, 1),
            ("填入兩邊", self.fill_both, 3, 2),
        ]
        # The ten established actions keep their original callbacks and
        # availability rules. Only their visual hierarchy and grid coordinates
        # change; "fill both" gets a full-width primary action area.
        positions = {
            "讀取試算表": (0, 0, 1, 3),
            "試算表設定": (0, 3, 1, 3),
            "綁定場內視窗": (1, 0, 1, 3),
            "綁定場外視窗": (1, 3, 1, 3),
            "校準 cTrader": (2, 0, 1, 2),
            "校準 MT5": (2, 2, 1, 2),
            "校準 TradingView": (2, 4, 1, 2),
            "填入場內": (0, 0, 1, 3),
            "填入場外": (0, 3, 1, 3),
            "填入兩邊": (1, 0, 1, 6),
        }
        action_icons = {
            "讀取試算表": "database",
            "試算表設定": "tune",
            "綁定場內視窗": "monitor",
            "綁定場外視窗": "monitor",
            "校準 cTrader": "crosshair",
            "校準 MT5": "crosshair",
            "校準 TradingView": "crosshair",
            "填入場內": "arrow-up-right",
            "填入場外": "arrow-up-right",
            "填入兩邊": "arrow-left-right",
        }
        self.action_buttons: dict[str, QPushButton] = {}
        for text, callback, row, column in definitions:
            button = QPushButton(text)
            self.action_buttons[text] = button
            button.clicked.connect(callback)
            if text == "填入兩邊":
                button.setObjectName("fillBothPrimary")
                # Preserve the original button's icon contract, but scale it
                # down to a minor glyph rather than a dashboard centerpiece.
                button.setIcon(themed_icon(action_icons[text], "#f7f5ff", 13))
                button.setIconSize(QSize(13, 13))
                button.setToolTip("填寫場內與場外；自動送單流程目前尚未實作")
            elif text not in {"填入場內", "填入場外"}:
                button.setIcon(themed_icon(action_icons[text]))
                button.setIconSize(QSize(16, 16))
                if text.startswith("校準"):
                    button.setProperty("variant", "accentOutline")
            grid_row, grid_col, row_span, col_span = positions.get(
                text, (row, column, 1, 1)
            )
            action_layout.addWidget(button, grid_row, grid_col, row_span, col_span)
            if text in {"填入場內", "填入場外", "填入兩邊"}:
                self.parameter_locked_buttons.append(button)
        automation_row = QWidget(actions)
        automation_row.setObjectName("automationOptionRow")
        automation_layout = QHBoxLayout(automation_row)
        automation_layout.setContentsMargins(3, 0, 3, 2)
        automation_layout.setSpacing(10)
        automation_caption = QLabel("自動化")
        automation_caption.setObjectName("automationCaption")
        automation_layout.addWidget(automation_caption)
        self.auto_entry_on_fill_both.setText("自動進場")
        automation_layout.addWidget(self.auto_entry_on_fill_both)
        self.auto_fast_pair = QCheckBox("快速雙邊")
        self.auto_fast_pair.setObjectName("auto_fast_pair")
        self.auto_fast_pair.setToolTip(
            "支援 cTrader + MT5 雙 Demo，場內場外可以互換。"
            "先檢查兩邊，再連續送出兩邊，之後核對成交。"
            "MT5 場內須在雙邊成交後依實際成交價修正 SL/TP。"
            "其中一邊未成交可能造成單邊曝險。"
        )
        self.auto_fast_pair.setChecked(
            bool(self.store.data["ui"].get("auto_fast_pair",False))
        )
        self.auto_fast_pair.toggled.connect(self._confirm_fast_pair_toggle)
        automation_layout.addWidget(self.auto_fast_pair)
        self.auto_sync_sl_tp_after_entry = QCheckBox("同步 SL/TP")
        self.auto_sync_sl_tp_after_entry.setObjectName("auto_sync_sl_tp_after_entry")
        self.auto_sync_sl_tp_after_entry.setChecked(
            bool(self.store.data["ui"].get("auto_sync_sl_tp_after_entry",False))
        )
        self.auto_sync_sl_tp_after_entry.toggled.connect(
            lambda enabled: self._confirm_future_auto_option(
                self.auto_sync_sl_tp_after_entry, enabled, "同步 SL/TP"
            )
        )
        automation_layout.addWidget(self.auto_sync_sl_tp_after_entry)
        self.auto_draw_tv_after_entry = QCheckBox("繪製 TV")
        self.auto_draw_tv_after_entry.setObjectName("auto_draw_tv_after_entry")
        self.auto_draw_tv_after_entry.setChecked(
            bool(self.store.data["ui"].get("auto_draw_tv_after_entry",False))
        )
        self.auto_draw_tv_after_entry.toggled.connect(
            lambda enabled: self._confirm_future_auto_option(
                self.auto_draw_tv_after_entry, enabled, "繪製 TV"
            )
        )
        automation_layout.addWidget(self.auto_draw_tv_after_entry)
        # The optional stages form a strict prerequisite chain:
        # entry -> synchronization -> TradingView.
        self._refresh_auto_option_dependencies()
        automation_layout.addStretch(1)
        # Main fill actions come before the optional automation preferences.
        action_layout.setRowMinimumHeight(2, 10)
        action_layout.addWidget(automation_row, 3, 0, 1, 6)
        # Manual follow-up controls will be separate from this grid.

        future = QGroupBox("手動進場後操作")
        future.setObjectName("afterEntryCard")
        future.setMaximumHeight(90)
        future_layout = QHBoxLayout(future)
        future_layout.setContentsMargins(13, 17, 13, 12)
        future_layout.setSpacing(8)
        sync_sl_tp_button = QPushButton("手動同步場外 SL/TP")
        sync_sl_tp_button.setObjectName("manualSyncSlTp")
        sync_sl_tp_button.setIcon(themed_icon("refresh"))
        sync_sl_tp_button.clicked.connect(self.sync_external_sl_tp)
        future_layout.addWidget(sync_sl_tp_button)
        self.parameter_locked_buttons.append(sync_sl_tp_button)
        tradingview_button = QPushButton("手動繪製 TV")
        tradingview_button.setObjectName("manualDrawTv")
        tradingview_button.setIcon(themed_icon("chart"))
        tradingview_button.clicked.connect(self.draw_tradingview)
        future_layout.addWidget(tradingview_button)
        self.parameter_locked_buttons.append(tradingview_button)
        # The manual actions are integrated below the main fill buttons.

        log_box = QGroupBox("操作紀錄")
        log_box.setObjectName("activityCard")
        log_layout = QVBoxLayout(log_box)
        log_layout.setContentsMargins(13, 16, 13, 11)
        self.log_text = QPlainTextEdit()
        self.log_text.setReadOnly(True)
        # ~7 lines at the 11px Consolas font instead of only ~3.
        self.log_text.setMinimumHeight(140)
        self.log_text.setMaximumHeight(166)
        self.log_text.setStyleSheet("font-family: Consolas; font-size: 11px;")
        log_layout.addWidget(self.log_text)
        # Move existing controls, preserving their original clicked handlers,
        # enabled/disabled rules, and all existing config keys.
        self.edit_page = QWidget()
        self.edit_page.setObjectName("editWorkspace")
        edit_layout = QVBoxLayout(self.edit_page)
        edit_layout.setContentsMargins(16, 12, 16, 12)
        edit_layout.setSpacing(11)
        edit_caption = QLabel("試算表、視窗綁定與欄位校準")
        edit_caption.setObjectName("workspaceCaption")
        edit_layout.addWidget(edit_caption)
        sheet_settings = QGroupBox("試算表設定")
        sheet_settings.setObjectName("editSheetGroup")
        sheet_settings_layout = QHBoxLayout(sheet_settings)
        sheet_settings_layout.setContentsMargins(12, 16, 12, 12)
        window_settings = QGroupBox("視窗綁定")
        window_settings.setObjectName("editWindowGroup")
        window_settings_layout = QHBoxLayout(window_settings)
        window_settings_layout.setContentsMargins(12, 16, 12, 12)
        calibration = QGroupBox("欄位校準")
        calibration.setObjectName("editCalibrationGroup")
        calibration_layout = QHBoxLayout(calibration)
        calibration_layout.setContentsMargins(12, 16, 12, 12)

        # "Read sheet" becomes a prominent everyday action on Trade.
        reload_button = self.action_buttons["讀取試算表"]
        action_layout.removeWidget(reload_button)
        reload_button.setText("重新讀取試算表")
        reload_button.setObjectName("reloadSheetButton")
        self.reload_sheet_button = reload_button

        sheet_settings.setFixedWidth(195)
        window_settings.setFixedWidth(308)
        calibration.setFixedWidth(430)
        for label in ("試算表設定",):
            button = self.action_buttons[label]
            action_layout.removeWidget(button)
            button.setFixedWidth(160)
            sheet_settings_layout.addWidget(button)
        for label in ("綁定場內視窗", "綁定場外視窗"):
            button = self.action_buttons[label]
            action_layout.removeWidget(button)
            button.setFixedWidth(132)
            window_settings_layout.addWidget(button)
        for label in ("校準 cTrader", "校準 MT5", "校準 TradingView"):
            button = self.action_buttons[label]
            action_layout.removeWidget(button)
            button.setFixedWidth(127)
            calibration_layout.addWidget(button)
        # Compact desktop tools: three unrelated groups share one toolbar
        # row instead of three full-width dashboard slabs.
        edit_controls_row = QHBoxLayout()
        edit_controls_row.setSpacing(10)
        for panel in (sheet_settings, window_settings, calibration):
            edit_controls_row.addWidget(panel, 0, Qt.AlignTop)
        edit_controls_row.addStretch(1)
        edit_layout.addLayout(edit_controls_row)

        # Previously the manual entry override had a working Return handler,
        # but was never added to any visible layout. Restore access here.
        manual_price_group = QGroupBox("手動場內進場價（選填）")
        manual_price_group.setObjectName("editManualEntryGroup")
        manual_price_group.setMaximumWidth(690)
        manual_price_layout = QHBoxLayout(manual_price_group)
        manual_price_layout.setContentsMargins(12, 16, 12, 11)
        manual_price_layout.setSpacing(8)
        manual_price_layout.addWidget(QLabel("價格"))
        self.entry_price_input.setPlaceholderText("留空使用自動辨識")
        self.entry_price_input.setToolTip(
            "自動辨識不到場內實際成交價時，可用此價格替代。"
            "按「套用進場價」會寫回 Google 試算表，並啟動 TradingView 繪製；"
            "不會送出交易訂單。平常可保持空白。"
        )
        manual_price_layout.addWidget(self.entry_price_input, 1)
        apply_manual_price = QPushButton("套用進場價")
        apply_manual_price.setObjectName("applyManualEntryPrice")
        apply_manual_price.clicked.connect(self.update_manual_entry_price)
        manual_price_layout.addWidget(apply_manual_price)
        manual_price_layout.addWidget(self.entry_price_value)
        edit_layout.addWidget(manual_price_group)
        # Same editable price already exists on the trading page. Keep the
        # legacy widget/handler for migration, but do not show two entrances.
        manual_price_group.hide()
        edit_layout.addStretch(1)
        self.main_pages.addWidget(self.edit_page)

        self.records_page = QWidget()
        self.records_page.setObjectName("recordsWorkspace")
        record_layout = QVBoxLayout(self.records_page)
        record_layout.setContentsMargins(16, 12, 16, 12)
        record_layout.setSpacing(9)
        record_caption = QLabel("紀錄")
        record_caption.setObjectName("workspaceCaption")
        # Keep the history action next to the Records heading, not stretched
        # into a full-width primary-looking operation button.
        record_heading = QHBoxLayout()
        record_heading.setSpacing(14)
        record_heading.addWidget(record_caption, 0, Qt.AlignVCenter)
        self.daily_pnl_history_button.setFixedWidth(138)
        self.daily_pnl_history_button.setFixedHeight(31)
        record_heading.addWidget(self.daily_pnl_history_button, 0, Qt.AlignVCenter)
        # Deferred redesign: keep data/handler, hide obsolete entry point.
        self.daily_pnl_history_button.hide()
        record_heading.addStretch(1)
        record_layout.addLayout(record_heading)
        log_box.setMaximumWidth(860)
        log_box.setMaximumHeight(235)
        record_layout.addWidget(log_box, 0, Qt.AlignTop)
        record_layout.addStretch(1)
        self.main_pages.addWidget(self.records_page)

        # Two-column trading view: references on the left, editable inputs
        # and actions on the right. All original callbacks are preserved.
        self.reload_sheet_button.setText("重新讀取")
        self.reload_sheet_button.setToolTip(
            "重新讀取目前選定方案的試算表交易資料，不會自動下單。"
        )
        reload_layout.addWidget(self.reload_sheet_button)
        future.setMaximumHeight(82)
        future_layout.setContentsMargins(4, 14, 4, 4)

        body = QWidget(central)
        body.setObjectName("tradeThreeZoneBody")
        body_layout = QHBoxLayout(body)
        body_layout.setContentsMargins(0, 0, 0, 0)
        body_layout.setSpacing(26)
        left_zone = QWidget(body)
        left_zone.setObjectName("tradeLeftZone")
        left_layout = QVBoxLayout(left_zone)
        left_layout.setContentsMargins(0, 0, 0, 0)
        left_layout.setSpacing(14)
        left_layout.addWidget(data_box, 0, Qt.AlignTop)
        # Remaining left-side space is used for a single read-only timeline.
        # Firm limits and point-value conversion are never assumed.
        self.ruler_section = QWidget(left_zone)
        self.ruler_section.setObjectName("accountRulerSection")
        ruler_layout = QVBoxLayout(self.ruler_section)
        ruler_layout.setContentsMargins(7, 4, 6, 0)
        ruler_layout.setSpacing(2)
        ruler_heading = QHBoxLayout()
        ruler_heading.setContentsMargins(0, 0, 0, 0)
        self.ruler_title = QLabel("帳號進度", self.ruler_section)
        self.ruler_title.setObjectName("accountRulerTitle")
        ruler_heading.addWidget(self.ruler_title)
        ruler_heading.addStretch(1)
        self.ruler_settings_button = QPushButton("來源", self.ruler_section)
        self.ruler_settings_button.setObjectName("accountRulerSettings")
        self.ruler_settings_button.clicked.connect(self._edit_ruler_settings)
        # Source mapping remains inspectable in code, not on the main UI.
        self.ruler_settings_button.hide()
        ruler_layout.addLayout(ruler_heading)
        self.account_ruler = AccountRuler(self.ruler_section)
        self.account_ruler.setObjectName("accountRulerScale")
        ruler_layout.addWidget(self.account_ruler)
        self.ruler_win_label = QLabel("再止盈幾單結束　—", self.ruler_section)
        self.ruler_loss_label = QLabel("再止損幾單結束　—", self.ruler_section)
        self.ruler_win_label.setObjectName("rulerWinCount")
        self.ruler_loss_label.setObjectName("rulerLossCount")
        self.ruler_win_label.setMinimumHeight(16)
        self.ruler_loss_label.setMinimumHeight(16)
        # Keep both accessible QLabel values for tests and tooltips, but
        # draw the two hints at the corresponding dynamic interval midpoints
        # inside AccountRuler. No duplicate fixed footer rows.
        self.ruler_win_label.hide()
        self.ruler_loss_label.hide()
        left_layout.addWidget(self.ruler_section, 0, Qt.AlignTop)
        left_layout.addStretch(1)
        # Do NOT repaint the ruler on textChanged. Enter commits the one
        # field, while the existing 更新 button commits both draft fields.
        self._refresh_ruler()

        divider = QFrame(body)
        divider.setObjectName("tradeVerticalDivider")
        divider.setFrameShape(QFrame.VLine)

        right_zone = QWidget(body)
        right_zone.setObjectName("tradeRightZone")
        right_layout = QVBoxLayout(right_zone)
        # Optically align the parameter heading with the custom data heading.
        right_layout.setContentsMargins(0, 8, 0, 0)
        right_layout.setSpacing(16)
        right_layout.addWidget(parameter_box, 0, Qt.AlignTop)
        right_layout.addWidget(actions, 0, Qt.AlignTop)
        right_layout.addWidget(future, 0, Qt.AlignTop)
        right_layout.addStretch(1)
        # Controls need slightly more width than read-only reference values.
        body_layout.addWidget(left_zone, 47)
        body_layout.addWidget(divider)
        body_layout.addWidget(right_zone, 53)
        main.addWidget(body, 1)

        self.recent_status = QLabel("就緒")
        self.recent_status.setObjectName("tradeRecentStatus")
        self.recent_status.setMinimumHeight(20)
        self.recent_status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        main.addWidget(self.recent_status, 0)

        # Full descriptions appear after hovering or focusing for 2 seconds.
        # The short labels remain uncluttered without hiding functionality.
        self._hover_help = DelayedHoverHelp(self, delay_ms=2000)
        details = (
            (self.auto_entry_on_fill_both,
             "按「填入兩邊」會依已儲存位置填寫場內、場外欄位。"
             "僅對已驗證的雙 Demo 帳戶執行自動進場，可能真的開啟 Demo 倉位。"
             "任何持倉資料不確定會停止，不會重複送單。"),
            (self.auto_sync_sl_tp_after_entry,
             "在雙 Demo 自動進場核對完成後，先確認場內保護，"
             "再以場內實際成交價同步場外 SL/TP，並再次讀回核對。"),
            (self.auto_draw_tv_after_entry,
             "在雙 Demo 進場且 SL/TP 同步確認後，自動繪製 TradingView 部位；"
             "前置核對失敗就不繪製。"),
            (sync_sl_tp_button,
             "手動執行既有的「同步場外止盈止損」。"
             "此操作可作用於既有持倉，與上面的自動化勾選無關；"
             "不代表同步場內與場外兩邊。"),
            (tradingview_button,
             "立即手動執行既有 TradingView 部位繪圖。"
             "是否同時繪製場內由右上角「顯示設定」決定；"
             "不受「繪製 TV」自動選項影響。"),
            (self.action_buttons["填入兩邊"],
             "根據目前方案與校準位置，依序填寫場內、場外欄位。"
             "自動送單尚未接入；單次點擊不會自動下最後的送單指令。"),
            (self.parameter_update_button,
             "使用目前輸入的交易參數更新試算表相關欄位。"
             "請先檢查所選方案與數值，這不是下單按鈕。"),
            (self.preview_sl_tp_button,
             "顯示場內與場外止盈、止損資訊；原本的查看／複製流程保留。"),
            (self.reload_sheet_button,
             "重新從目前設定的試算表讀取交易資料，不會自動下單。"),
            (apply_manual_price,
             "在「編輯」頁手動套用場內進場價；留空時恢復自動辨識。"
             "亦可在價格輸入框按 Enter 執行。"),
        )
        for widget, description in details:
            self._hover_help.register(widget, description)
        self.profile_combo.setToolTip(self.profile_combo.currentText())
        self.profile_combo.currentTextChanged.connect(self.profile_combo.setToolTip)
        self._setup_calibration_badges()

    def _setup_calibration_badges(self) -> None:
        """Tiny noninteractive dots at top-right of Edit and broker buttons."""
        self._calibration_badge_labels = {}
        targets = [
            self.page_nav["編輯"],
            self.action_buttons["校準 cTrader"],
            self.action_buttons["校準 MT5"],
            self.action_buttons["校準 TradingView"],
        ]
        for button in targets:
            dot = QLabel("●", button)
            dot.setObjectName("calibrationIncompleteDot")
            dot.setFixedSize(10, 10)
            dot.setStyleSheet(
                "color:#fa5362;font-size:12px;background:transparent;"
            )
            dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            dot.move(max(0, button.width()-11), 0)
            dot.hide()
            button.installEventFilter(self)
            self._calibration_badge_labels[button] = dot
        self._refresh_calibration_badges()

    def _refresh_calibration_badges(self) -> None:
        """Only inspect in-memory saved coordinates; never scan a broker."""
        badges = getattr(self, "_calibration_badge_labels", None)
        if not badges:
            return
        enabled = bool(self.show_calibration_badges.isChecked())
        incomplete = {}
        for platform in ("cTrader", "MT5", "TradingView"):
            points = self.store.data["platforms"].get(
                platform, {}
            ).get("points", {})
            keys = [key for key,_ in CALIBRATION_TARGETS[platform]]
            done,total = completion(points, keys)
            incomplete[platform] = done < total
            self.action_buttons["校準 " + platform].setToolTip(
                f"已儲存校準：{done}/{total}；"
                "僅代表位置已儲存，不代表實際交易欄位驗收。"
            )
        states = {
            self.page_nav["編輯"]: any(incomplete.values()),
            self.action_buttons["校準 cTrader"]: incomplete["cTrader"],
            self.action_buttons["校準 MT5"]: incomplete["MT5"],
            self.action_buttons["校準 TradingView"]: incomplete["TradingView"],
        }
        for button, dot in badges.items():
            dot.move(max(0, button.width()-11), 0)
            dot.setVisible(enabled and states[button])
            if dot.isVisible():
                dot.raise_()

    def switch_workspace(self, name: str) -> None:
        """Change only the visible view; keep the current trade state intact."""
        names = {"交易": 0, "編輯": 1, "紀錄": 2}
        if name not in names:
            return
        self.main_pages.setCurrentIndex(names[name])
        for key, button in self.page_nav.items():
            button.blockSignals(True)
            button.setChecked(key == name)
            button.blockSignals(False)

    def toggle_maximized(self) -> None:
        """Native-style titlebar maximize/restore; keep existing window state."""
        if self.isMaximized():
            self.showNormal()
        else:
            self.showMaximized()
        self.chrome_maximize.update()

    def changeEvent(self, event) -> None:
        super().changeEvent(event)
        if event.type() == QEvent.WindowStateChange and hasattr(self, "chrome_maximize"):
            self.chrome_maximize.update()

    def _dock_top(self) -> None:
        screen = QApplication.primaryScreen()
        if screen is None:
            return
        area = screen.availableGeometry()
        if self.isMaximized():
            return
        width = min(1150, max(1020, area.width() - 45))
        # Follow actual content density instead of preserving 150px blank
        # footer on BOTH columns; still respect the minimum readable height.
        height = min(630, max(610, area.height() - 75))
        self.resize(width, height)
        actual_width = self.width()
        self.move(
            area.x() + max(0, (area.width() - actual_width) // 2),
            area.y() + 8,
        )

    def log(self, message: str) -> None:
        self.signals.log.emit(message)

    def _append_log(self, message: str) -> None:
        line = f"[{time.strftime('%H:%M:%S')}] {message}"
        if hasattr(self, "recent_status"):
            self.recent_status.setText(line)
            self.recent_status.setToolTip("完整操作紀錄位於「紀錄」頁面")
        current = self.log_text.toPlainText()
        divider = self._trading_day_divider()
        if divider and current:
            self.log_text.setPlainText(f"{line}\n{divider}\n{current}")
        elif divider:
            self.log_text.setPlainText(f"{divider}\n{line}")
        else:
            self.log_text.setPlainText(f"{line}\n{current}" if current else line)

    def _trading_day_divider(self) -> str:
        settings = self.store.data.get("ui", {}).get("trading_day_separator", {})
        if not settings or not settings.get("enabled", True):
            return ""
        day, season, reset_hour = trading_day_key(
            datetime.now().astimezone(),
            summer_reset_hour=int(settings.get("summer_reset_hour", 6)),
            winter_reset_hour=int(settings.get("winter_reset_hour", 7)),
        )
        if self._last_log_trading_day == day:
            return ""
        previous = self._last_log_trading_day
        self._last_log_trading_day = day
        if previous is None:
            return ""
        return f"──── 交易日 {day} 開始（{season}，{reset_hour:02d}:00）────"

    def _set_status(self, value: str) -> None:
        return

    def _show_error(self, message: str) -> None:
        # A rejected write must never activate an unconfirmed manual price.
        self._primary_entry_price_pending = None
        # Never fill using values after a rejected/rolled-back sheet write.
        if self._fill_waiting_for_sheet is not None:
            self._fill_waiting_for_sheet = None
            self.log("已取消待執行填寫：試算表更新失敗。")
        QMessageBox.critical(self, "對沖小幫手", message)

    def _show_duplicate_entry_decision(self, data: dict) -> None:
        """GUI-thread-only question, never an implicit send/retry."""
        request=data.get("request")
        self.showNormal()
        self._dock_top()
        self.raise_()
        self.activateWindow()
        if not request:
            QMessageBox.warning(
                self,"請人工確認持倉",
                "交易紀錄缺少重試資訊，不能安全自動繼續。"
            )
            return
        manual_needed=not bool(data.get("retryable"))
        if manual_needed and not data.get("manual_review_possible"):
            QMessageBox.warning(
                self, "紀錄狀態不明，禁止重送",
                "無法判定前次執行紀錄的類型。請人工核對後再處理，"
                "本次不會送單。"
            )
            return
        dialog=QMessageBox(self)
        dialog.setWindowTitle("是否調整數值再進場？")
        dialog.setIcon(QMessageBox.Question)
        dialog.setText(
            "這組方案之前已有自動進場紀錄。\n"
            "要回主畫面調整數值，還是維持原有數值重新進場？"
        )
        if manual_needed:
            dialog.setInformativeText(
                "上一次可能已在 cTrader 或 MT5 成交，但程式讀取失敗。"
                "請先在兩個 Demo 平台自行核對「目前持倉、掛單與成交歷史」。"
                "若兩邊都有與本方案完全對應的既有持倉，"
                "只接續成交後的檢查／已勾選的同步，不會送新訂單。"
                "若兩邊確認空倉，才可按既有安全流程重新進場；"
                "只有一邊或讀值不明時會停止，不盲目補單。"
            )
        else:
            dialog.setInformativeText(
                "選擇「仍要繼續進場」後，程式會再次確認雙 Demo "
                "身分、空倉、校準及兩邊表單，通過才會下單。"
            )
        adjust=dialog.addButton("調整數值，返回主畫面",QMessageBox.RejectRole)
        proceed=dialog.addButton(
            "核對現有持倉／繼續" if manual_needed else "仍要繼續進場",
            QMessageBox.AcceptRole
        )
        if manual_needed:
            acknowledgement=QCheckBox(
                "我已核對 cTrader、MT5 的持倉、掛單及成交歷史。"
                "若現有雙邊持倉符合方案，就接續而不新增交易；"
                "若兩邊空倉，才同意再試進場。"
            )
            dialog.setCheckBox(acknowledgement)
            proceed.setEnabled(False)
            acknowledgement.toggled.connect(proceed.setEnabled)
        dialog.setDefaultButton(adjust)
        dialog.exec()
        if dialog.clickedButton() is not proceed:
            self.log("已選擇返回主畫面調整數值，沒有重新送單。")
            return
        if manual_needed and not acknowledgement.isChecked():
            QMessageBox.warning(
                self, "尚未核對先前交易",
                "必須先核對兩邊的持倉、掛單與成交歷史，才能重新進場。"
            )
            return
        current_url=str(self.store.data["sheet"].get("spreadsheet_url","")).strip()
        if (self.profiles.active_name != request["profile_name"]
            or current_url != request["sheet_url"]
            or self.instruction != request["item"]
            or self.internal_platform.currentText() != request["internal_platform"]
            or self.external_platform.currentText() != request["external_platform"]
        ):
            QMessageBox.warning(
                self, "交易參數已改變",
                "方案、平台或交易參數已改變，請重新填入核對後再進場。"
            )
            return
        approved=(
            data["key"], data["entry"]["status"],
            str(data["entry"].get("time","")),
            str(data["entry"].get("details","")),
        )
        options={
            "sync_sl_tp":request["sync_sl_tp"],
            "draw_tv":request["draw_tv"],
            "draw_internal":request["draw_internal"],
            "fast_pair":bool(request.get("fast_pair", False)),
            "duplicate_confirmation":approved,
        }
        if manual_needed:
            options["manual_reconciliation_confirmed"]=True
            self.log(
                "使用者已明確確認自行核對兩邊 Demo 持倉、掛單與歷史紀錄；"
                "仍需重新檢查帳戶與空倉，才能進場。"
            )
        self.log("使用者明確確認繼續；重新檢查兩邊 Demo 與訂單，確認後才進場。")
        self._start(
            "重新確認進場",
            lambda: self._auto_entry_after_fill_both_pending(
                request["internal_platform"],request["external_platform"],
                request["item"],**options,
            ),
        )

    def _show_ctrader_decimal_suggestion(self, data: dict[str, str]) -> None:
        """GUI-thread-only user consent to switch THIS exact scheme."""
        name = data["profile_name"]
        url = data["sheet_url"]
        if (
            self.profiles.active_name != name
            or self.store.data["sheet"].get("spreadsheet_url", "").strip()
                != url
        ):
            self.log(
                "偵測到 cTrader 小數寫入問題，但方案名稱或表格已變更；"
                "未詢問或修改另一方案。"
            )
            return
        answer = QMessageBox.question(
            self,
            "cTrader 止盈止損輸入方式",
            f"目前方案「{name}」的{data['role_text']} cTrader "
            f"{data['label']}，連續兩次填入小數後只保留整數。\n\n"
            f"預期：{data['expected']}\n"
            f"讀回：{data['actual']}\n\n"
            "要將此方案的 cTrader 止盈／止損輸入方式改成"
            "與 Gooey 一樣的「點數換算輸入」嗎？\n\n"
            "只影響目前方案及目前試算表網址。"
            "確認後請重新按「填入」測試，程式不會自行下單。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if answer == QMessageBox.Yes:
            set_ctrader_mode_for_profile(
                self.store.data, self.profiles.active_name, "gooey"
            )
            self.save_config()
            self.log(
                f"方案「{name}」已改用 cTrader 的 Gooey 點數換算輸入；"
                "本次填寫已中止，請重新填入與核對。"
            )
        else:
            self.log(
                f"方案「{name}」保留原本 cTrader 輸入方式；"
                "本次填寫已停止。"
            )

    def _set_parameter_write_busy(self, busy: bool) -> None:
        if not busy and self._fill_waiting_for_sheet is not None:
            # A successful write must have generated an authoritative
            # instruction via _show_instruction before any fill can start.
            QTimer.singleShot(0, self._resume_fill_after_sheet_update)
        for button in self.parameter_locked_buttons:
            button.setEnabled(not busy)
        self.parameter_update_button.setEnabled(True)
        self.preview_sl_tp_button.setEnabled(True)

    def keyPressEvent(self, event) -> None:
        if event.key() in (Qt.Key_Return, Qt.Key_Enter):
            self.update_all_trade_parameters()
            event.accept()
            return
        super().keyPressEvent(event)

    def eventFilter(self, watched, event) -> bool:
        badges = getattr(self, "_calibration_badge_labels", {})
        if watched in badges and event.type() in (
            QEvent.Resize, QEvent.Show,
        ):
            dot = badges[watched]
            dot.move(max(0, watched.width()-13), 0)
            dot.raise_()
        if (
            event.type() == QEvent.KeyPress
            and event.key() in (Qt.Key_Return, Qt.Key_Enter)
            and QApplication.activeModalWidget() is None
            and isinstance(watched, QWidget)
            and (watched is self or self.isAncestorOf(watched))
            and not isinstance(watched, QLineEdit)
        ):
            self.update_all_trade_parameters()
            event.accept()
            return True
        return super().eventFilter(watched, event)

    def _queue_auto_entry_result(self, report: dict) -> None:
        """Qt thread: wait for operation_minimized, then show the receipt."""
        QTimer.singleShot(
            450, lambda payload=dict(report): self._show_auto_entry_result(payload)
        )

    def _show_auto_entry_result(self, report: dict) -> None:
        """Topmost read-only receipt, no new order and no broker focus/click."""
        earlier = getattr(self, "_auto_entry_receipt", None)
        if earlier is not None:
            earlier.close()
        # An independent window remains visible when the main LAB window
        # is automatically minimized after fill-both.
        dialog = QDialog()
        dialog.setObjectName("autoEntryResultDialog")
        dialog.setWindowFlags(Qt.Dialog | Qt.WindowStaysOnTopHint)
        dialog.setWindowTitle(str(report.get("title") or "開倉結果待確認"))
        dialog.resize(520, 345)
        layout = QVBoxLayout(dialog)
        heading = QLabel(str(report.get("title") or "開倉結果待確認"), dialog)
        heading.setObjectName("autoEntryResultHeading")
        heading.setWordWrap(True)
        layout.addWidget(heading)
        details = QTextBrowser(dialog)
        details.setObjectName("autoEntryResultBody")
        details.setReadOnly(True)
        details.setPlainText(str(report.get("message") or "尚無可用的核對結果。"))
        layout.addWidget(details)
        actions = QHBoxLayout()
        button = QPushButton("確認", dialog)
        button.setObjectName("autoEntryResultConfirmButton")
        button.clicked.connect(dialog.accept)
        role = report.get("single_confirmed_role")
        if role in ("internal","external"):
            # These are explicitly HUMAN action paths. No broker clicks,
            # API submission, close-position or fallback automatic order.
            for option,title in (
                ("close","核對後手動平掉已開倉側"),
                ("hedge","核對後手動處理另一側"),
            ):
                choice=QPushButton(title,dialog)
                choice.setObjectName(
                    "autoEntryIncidentCloseButton" if option=="close"
                    else "autoEntryIncidentHedgeButton"
                )
                choice.clicked.connect(
                    lambda checked=False, action=option, info=dict(report):
                        self._explain_manual_incident_action(action,info)
                )
                actions.addWidget(choice)
        actions.addStretch()
        actions.addWidget(button)
        layout.addLayout(actions)
        self._auto_entry_receipt = dialog
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        QApplication.alert(dialog, 5000)

    def _explain_manual_incident_action(
        self, action: str, report: dict
    ) -> None:
        """Explain chosen manual path; NEVER actuate unknown-state trades."""
        role=report.get("single_confirmed_role")
        if role not in ("internal","external") or action not in ("close","hedge"):
            return
        side="場內" if role=="internal" else "場外"
        other="場外" if role=="internal" else "場內"
        platform=str(report.get(
            "internal_platform" if role=="internal" else "external_platform",""
        ))
        opposite=str(report.get(
            "external_platform" if role=="internal" else "internal_platform",""
        ))
        title=("人工平倉前核對" if action=="close" else "人工補倉前核對")
        instruction=(
            f"已確認的 {side}（{platform}）持倉可能仍存在。\\n"
            f"請先在 {platform} 核對最新持倉編號與手數，再到"
            f" {opposite} 核對當前持倉、掛單、交易歷史。\\n\\n"
            + (
                f"若確認必須解除單邊風險，請親自操作 {side} 的"
                "正確持倉平倉，並驗證平倉回報。"
                if action=="close" else
                f"只有證實 {other}（{opposite}）沒有成交、"
                "也沒有待成交訂單時，才親自在該平台重新開倉，"
                "並重新核對方向、商品、手數、SL／TP。"
            )
            + "\\n\\n本按鈕只顯示操作說明，不會自動開倉或平倉。"
            "另一側狀態不明時，這兩種選擇都可能有風險。"
        )
        QMessageBox.warning(
            getattr(self,"_auto_entry_receipt",None) or self,
            title,instruction
        )

    def _show_external_price_result(self, result: dict[str, str]) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("場外止盈止損")
        layout = QGridLayout(dialog)
        lot_text = result.get("detected_lot") or "無法辨識"
        message = (
            f"第一筆場外訂單手數不符合。預期 {result.get('expected_lot', '')}，"
            f"讀到 {lot_text}。\n未開啟訂單，請手動確認後複製下列價格。"
        )
        layout.addWidget(QLabel(message), 0, 0, 1, 3)
        rows = [
            ("場內進場價", result.get("entry", "")),
            ("場外止損價", result.get("sl", "")),
            ("場外止盈價", result.get("tp", "")),
        ]
        for row, (label, value) in enumerate(rows, start=1):
            value_input = QLineEdit(value)
            value_input.setReadOnly(True)
            copy_button = QPushButton("複製")
            copy_button.clicked.connect(
                lambda checked=False, text=value: QApplication.clipboard().setText(text)
            )
            layout.addWidget(QLabel(label), row, 0)
            layout.addWidget(value_input, row, 1)
            layout.addWidget(copy_button, row, 2)
        close_button = QPushButton("關閉")
        close_button.clicked.connect(dialog.accept)
        layout.addWidget(close_button, len(rows) + 1, 2)
        dialog.exec()

    def set_always_on_top(self, enabled: bool) -> None:
        # Qt may recreate a frameless native HWND when this flag changes.
        # Preserve both the user's compact placement and maximized state.
        was_maximized = self.isMaximized()
        previous_geometry = self.geometry()
        self.setWindowFlag(Qt.WindowStaysOnTopHint, enabled)
        if was_maximized:
            self.showMaximized()
        else:
            self.showNormal()
            self.setGeometry(previous_geometry)
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
        is_fill = name in ("填入場內", "填入場外", "填入兩邊", "重新確認進場")
        if is_fill and not self._fill_task_lock.acquire(blocking=False):
            self.log("已有填寫任務執行中，已忽略重複操作。")
            return
        task_profile_name = self.profiles.active_name
        task_sheet_url = str(
            self.store.data["sheet"].get("spreadsheet_url", "")
        ).strip()
        if self.emergency.event.is_set():
            self.emergency.reset()
            self.signals.status.emit("就緒")
            self.log("已解除緊急停止，開始執行新的操作。")

        def worker() -> None:
            suggestion = None
            duplicate_data = None
            if hide_during:
                self.signals.operation_started.emit()
            self.signals.status.emit(name.upper())
            try:
                task()
                if not self.emergency.event.is_set():
                    self.signals.status.emit("就緒")
            except EmergencyStopped:
                self.signals.status.emit("已停止")
            except DuplicateEntryDecisionRequired as exc:
                self.signals.status.emit("待確認")
                duplicate_data={
                    "key":exc.key,
                    "entry":exc.entry,
                    "retryable":exc.retryable,
                    "manual_review_possible":exc.manual_review_possible,
                    "request":exc.request,
                }
                self.log(
                    "發現已存在的自動進場紀錄，等待使用者決定是否調整數值。"
                )
            except CTraderDecimalInputSuggestion as exc:
                self.signals.status.emit("待確認")
                self.log(str(exc))
                suggestion = {
                    "profile_name": task_profile_name,
                    "sheet_url": task_sheet_url,
                    "role_text": exc.role_text,
                    "label": exc.label,
                    "expected": exc.expected,
                    "actual": exc.actual,
                }
            except Exception as exc:
                self.signals.status.emit("錯誤")
                self.log(f"錯誤：{exc}")
                # An entry receipt already contains the uncertainty and
                # next steps; avoid showing two competing error popups.
                if not getattr(exc, "_auto_entry_result_emitted", False):
                    self.signals.error.emit(str(exc))
            finally:
                if is_fill:
                    self._fill_task_lock.release()
                if hide_during:
                    if restore_after:
                        self.signals.operation_finished.emit()
                    else:
                        self.signals.operation_minimized.emit()
                # Emit after the restore signal so the dialog isn't hidden
                # behind the broker platform while Qt shows the question.
                if suggestion is not None and not self.emergency.event.is_set():
                    self.signals.ctrader_decimal_suggestion.emit(suggestion)
                if duplicate_data is not None and not self.emergency.event.is_set():
                    self.signals.duplicate_entry_decision.emit(duplicate_data)

        threading.Thread(target=worker, daemon=True).start()

    def read_sheet(self) -> None:
        self.ruler_sheet_values = None
        self.ruler_sheet_status = "正在讀取兩個試算表分頁"
        self._refresh_ruler()
        self._start("讀取中", self._read_sheet_task, hide_during=False)

    def _read_sheet_task(self, retries: int = 0) -> None:
        self.log("正在讀取 Google 試算表。")
        item = None
        for attempt in range(retries + 1):
            try:
                item = self.reader.read(self.store.data["sheet"])
                break
            except ValidationError:
                if attempt >= retries:
                    raise
                self.log("試算表公式尚未更新完成，稍後重讀。")
                time.sleep(0.7)
        if item is None:
            raise ValidationError("讀取試算表失敗。")
        self.instruction = item
        try:
            note_values = self.reader.read_a1_values(self.store.data["sheet"], ["A12"])
            self.signals.sheet_note.emit(note_values.get("A12", ""))
        except ValidationError as exc:
            self.signals.sheet_note.emit("")
            self.log(f"未讀取 A12 備註：{exc}")
        self.manual_entry_price = None
        self.signals.entry_price_reset.emit()
        self.signals.instruction.emit(item)
        # Read-only supplementary cells from two tabs in the SAME workbook.
        # Failure here never prevents normal trading information from loading.
        ruler_values: dict[str, dict[str, str]] = {}
        ruler_error = ""
        sheet_config = dict(self.store.data["sheet"])
        profile_name = self.profiles.active_name
        try:
            for tab_name, cells in SHEET_RULER_REFERENCES.items():
                separate_tab = {**sheet_config, "worksheet": tab_name}
                ruler_values[tab_name] = self.reader.read_a1_values(
                    separate_tab, list(cells)
                )
        except Exception as exc:
            ruler_error = f"進度尺資料無法讀取：{str(exc)[:180]}"
        self.signals.ruler_sheet.emit((
            ruler_values if not ruler_error else None,
            ruler_error,
            profile_name,
            sheet_config.get("spreadsheet_url", ""),
        ))
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
            "original_sl_points": ""
            if item.original_sl_points is None
            else str(item.original_sl_points),
        }
        for key, value in values.items():
            self.data_labels[key].setText(value)
        self.internal_direction_input.blockSignals(True)
        self.internal_direction_input.setCurrentIndex(
            0 if item.internal_direction == "BUY" else 1
        )
        self.internal_direction_input.blockSignals(False)
        parameter_values = {
            "daily_pnl": item.daily_pnl,
            "internal_balance": item.internal_balance,
            "expected_sl_combined": self._format_expected_sl_placeholder(item),
            "internal_entry_price": item.internal_entry_price,
        }
        for key, value in parameter_values.items():
            self.parameter_inputs[key].setPlaceholderText("" if value is None else str(value))
        pending_price = self._primary_entry_price_pending
        if pending_price is not None and item.internal_entry_price == pending_price:
            self.manual_entry_price = pending_price
            self._primary_entry_price_pending = None
            self.log("場內進場價已寫回並讀回確認，可供手動同步或繪製 TV 使用。")
        # An authoritative sheet refresh replaces old preview overrides.
        self._ruler_confirmed_parameters = {
            "internal_balance": "", "daily_pnl": "",
        }
        self._refresh_ruler()
        if self._fill_waiting_for_sheet is not None:
            self._fill_waiting_for_sheet["sheet_ready"] = True
        self._resume_fill_after_sheet_update()

    def _show_ruler_sheet(self, payload: tuple) -> None:
        """Apply cross-tab values on UI thread only for the matching profile."""
        values, error, profile_name, sheet_url = payload
        if profile_name != self.profiles.active_name or sheet_url != self.store.data["sheet"].get("spreadsheet_url", ""):
            return
        self.ruler_sheet_values = values
        self.ruler_sheet_status = error or ""
        self._refresh_ruler()

    def _confirm_ruler_field(self, key: str, *, repaint: bool = True) -> None:
        """Accept an individual balance/P&L draft only on Enter.

        An invalid partial entry keeps the last valid graph. The existing
        update handler remains responsible for validation and sheet writes.
        """
        if key not in self._ruler_confirmed_parameters:
            return
        raw = self.parameter_inputs[key].text().strip()
        if raw:
            try:
                if key == "internal_balance" and raw.startswith("~"):
                    balance, _ = self._resolve_internal_balance_delta_input(raw)
                    valid = balance.is_finite() and balance >= 0
                elif key == "daily_pnl":
                    valid = self._resolve_daily_pnl_input(raw).is_finite()
                else:
                    balance = decimal_value(raw)
                    valid = balance is not None and balance >= 0
            except (InvalidOperation, ValueError, AutomationError):
                valid = False
            if not valid:
                return
        self._ruler_confirmed_parameters[key] = raw
        if repaint:
            self._refresh_ruler()

    def _confirm_ruler_inputs(self) -> None:
        """The normal 更新 button also commits both cash-field drafts."""
        for key in ("internal_balance", "daily_pnl"):
            self._confirm_ruler_field(key, repaint=False)
        self._refresh_ruler()

    def _refresh_ruler(self) -> None:
        """Read ONLY Enter-confirmed overrides; never trigger sheet IO."""
        if not hasattr(self, "account_ruler"):
            return
        item = self.instruction
        if item is None:
            self.account_ruler.set_state(None, "等待試算表交易資料")
            self.ruler_win_label.setText("再止盈幾單結束　—")
            self.ruler_loss_label.setText("再止損幾單結束　—")
            return
        try:
            balance = item.internal_balance
            pnl = item.daily_pnl
            new_balance = self._ruler_confirmed_parameters["internal_balance"]
            new_pnl = self._ruler_confirmed_parameters["daily_pnl"]
            if new_balance.startswith("~"):
                balance, pnl = self._resolve_internal_balance_delta_input(new_balance)
            elif new_balance:
                balance = decimal_value(new_balance)
            if new_pnl:
                pnl = self._resolve_daily_pnl_input(new_pnl)
            if self.ruler_sheet_values is None:
                state, reason = None, self.ruler_sheet_status or "等待試算表兩個分頁的數值"
            else:
                state, reason = calculate_ruler_from_sheet(
                    self.ruler_sheet_values,
                    balance=balance,
                    daily_pnl=pnl,
                )
        except (ValueError, InvalidOperation, AutomationError):
            state, reason = None, "交易參數正在編輯，請輸入有效數字"
        self.account_ruler.set_state(state, reason)
        if state is None:
            self.ruler_win_label.setText("再止盈幾單結束　—")
            self.ruler_loss_label.setText("再止損幾單結束　—")
        else:
            self.ruler_win_label.setText(
                self.account_ruler._segment_text(state.win_hint, win=True)
            )
            self.ruler_loss_label.setText(
                self.account_ruler._segment_text(state.loss_hint, win=False)
            )
            self.ruler_win_label.setToolTip(
                f"場內本單 TP 預估 +{money(state.tp_cash)}；"
                f"場外反向視為止損；實際累加碰到有效獲利目標需 {state.win_crossing} 單。"
                "近似值只供判斷，未計手續費／滑點。"
            )
            self.ruler_loss_label.setToolTip(
                f"場內本單 SL 預估 -{money(state.sl_cash)}；"
                f"場外反向視為止盈；實際累加觸及有效虧損線需 {state.loss_crossing} 單。"
                "近似值不是可安全交易次數，未計手續費／滑點。"
            )

    def _edit_ruler_settings(self) -> None:
        """Show read-only source references; no extra manual configuration."""
        detail = (
            "帳號進度自動讀取目前方案連結的 Google 試算表：\n\n"
            "運算區：B2 初始餘額、F7 最大虧損餘額線、F6 每日最大虧損額、"
            "B9 帳號目標餘額、C20 今日獲利目標額。\n"
            "主要計算區：E2 場內單筆止損金額、F2 場內單筆止盈金額。\n"
            "場內餘額、今日盈虧仍採原本已讀取的試算表欄位。\n\n"
            "F7 與 B9 都是絕對餘額；F6 與 C20 是當日起始餘額的"
            "損失／獲利金額。按「重新讀取」可更新數值。"
        )
        QMessageBox.information(self, "帳號進度・資料來源", detail)

    def _show_sheet_note(self, value: str) -> None:
        self.sheet_note_indicator.set_note(value)

    def _format_expected_sl_placeholder(
        self, item: TradeInstruction
    ) -> str | None:
        points = item.expected_sl_points
        percent = item.expected_sl_percent
        if points is None and percent is None:
            return None
        return str(points if points is not None else percent)

    def _confirm_fill_text_inputs(self) -> None:
        """An Enter confirms all visible parameter fields for fill previews.

        The existing Enter handler independently writes inputs to Sheets.
        """
        if self.instruction is None:
            return
        try:
            self._instruction_with_parameter_overrides(self.instruction)
        except (AutomationError, InvalidOperation, ValidationError, ValueError):
            return
        for key, entry in self.parameter_inputs.items():
            self._fill_confirmed_text[key] = entry.text().strip()

    def _unconfirmed_fill_fields(self) -> list[str]:
        return [
            key for key, entry in self.parameter_inputs.items()
            if entry.text().strip()
            and self._fill_confirmed_text.get(key, "") != entry.text().strip()
        ]

    def _fill_calibration_missing(
        self, roles: tuple[str, ...],
        platforms: dict[str, str],
        item: TradeInstruction,
    ) -> list[str]:
        """Missing targets for the EXISTING fill phase, never submit."""
        missing = []
        for role in roles:
            platform = platforms[role]
            role_label = "場內" if role == "internal" else "場外"
            config = self.store.data["platforms"].get(platform)
            if not config or platform not in REQUIRED_POINTS:
                missing.append(f"{role_label} {platform}：未設定平台")
                continue
            points = config.get("points", {})
            required = list(REQUIRED_POINTS[platform])
            if platform in ("cTrader", "GooeyTrade"):
                # UIA post-fill verification checks BOTH directions to
                # establish a unique selection, even before order entry.
                required.extend(("buy_button", "sell_button"))
            if platform in ("MT5", "BYBIT MT5", "原版MT5"):
                required.append("new_order_button")
                if item.estimated_price is None:
                    required.append("ask_price")
                # The MT5 order dialog can also be opened manually, so its
                # launcher is not required by the CURRENT fill routine.
            labels = dict(CALIBRATION_TARGETS.get(platform, []))
            for key in dict.fromkeys(required):
                if not isinstance(points.get(key), dict) or not points[key]:
                    missing.append(f"{role_label} {platform}：{labels.get(key, key)}")
        return missing

    def _launch_fill(self, roles: tuple[str, ...]) -> None:
        """Perform UI preflight before starting any broker-window clicks."""
        if self._fill_task_lock.locked():
            self.log("填寫操作仍在執行，已拒絕重複點擊。")
            return
        if self._parameter_write_active or self._fill_waiting_for_sheet:
            QMessageBox.information(
                self, "等待數值確認",
                "交易參數正在寫回／核對試算表，完成後才可以填入。"
            )
            return
        if self.instruction is None:
            QMessageBox.warning(self, "填入前檢查", "請先讀取 Google 試算表。")
            return
        platforms = {
            "internal": self.internal_platform.currentText(),
            "external": self.external_platform.currentText(),
        }
        dirty = self._unconfirmed_fill_fields()
        if dirty:
            labels = {
                "daily_pnl": "每日獲利／虧損", "internal_balance": "場內餘額",
                "expected_sl_combined": "預期止損點／%數",
                "internal_entry_price": "場內進場點位",
            }
            names = "、".join(labels.get(key, key) for key in dirty)
            answer = QMessageBox.question(
                self, "有尚未確認的數值",
                f"以下數值尚未按 Enter 確認：\n{names}\n\n"
                "是否先寫回試算表、重新核對，確認成功後再自動填入？",
                QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
            )
            if answer != QMessageBox.Yes:
                return
            try:
                candidate = self._instruction_with_parameter_overrides(
                    self.instruction
                )
            except (AutomationError, InvalidOperation, ValidationError, ValueError) as exc:
                QMessageBox.warning(self, "數值格式錯誤", str(exc))
                return
            # Always check targets BEFORE triggering a sheet update, so the
            # user knows which button is missing without partial effects.
            missing = self._fill_calibration_missing(roles, platforms, candidate)
            if missing:
                QMessageBox.warning(
                    self, "請先校準必要按鈕",
                    "本次填寫缺少下列校準位置：\n" + "\n".join(missing)
                    + "\n\n請到「編輯 → 欄位校準」完成後再試。"
                )
                return
            self._fill_waiting_for_sheet = {
                "roles": roles, "platforms": platforms,
                "expected": candidate, "fields": tuple(dirty),
                "sheet_ready": False,
            }
            self._confirm_fill_text_inputs()
            self.update_all_trade_parameters()
            # When the writer reports "nothing changed", use the
            # already-loaded authoritative model for the comparison; never
            # leave the deferred fill stuck waiting for a non-existent write.
            if not self._parameter_write_active:
                if self._fill_waiting_for_sheet is not None:
                    self._fill_waiting_for_sheet["sheet_ready"] = True
                QTimer.singleShot(0, self._resume_fill_after_sheet_update)
            return
        try:
            candidate = self._require_instruction()
        except (AutomationError, InvalidOperation, ValidationError, ValueError) as exc:
            QMessageBox.warning(self, "填入前檢查", str(exc))
            return
        missing = self._fill_calibration_missing(roles, platforms, candidate)
        if missing:
            QMessageBox.warning(
                self, "請先校準必要按鈕",
                "本次填寫缺少下列校準位置：\n" + "\n".join(missing)
                + "\n\n請到「編輯 → 欄位校準」完成後再試。"
            )
            return
        self._start_fill_worker(roles, platforms)

    def _resume_fill_after_sheet_update(self) -> None:
        pending = self._fill_waiting_for_sheet
        if not pending or self._parameter_write_active:
            return
        # Signal order is not guaranteed relative to worker completion.
        # Never execute without an actual read-back of the new Sheet state.
        if not pending["sheet_ready"]:
            return
        expected = pending["expected"]
        item = self.instruction
        fields = pending["fields"]
        if item is None or any(
            getattr(item, field if field != "expected_sl_combined"
                    else "expected_sl_points")
            != getattr(expected, field if field != "expected_sl_combined"
                       else "expected_sl_points")
            for field in fields
        ):
            self._fill_waiting_for_sheet = None
            QMessageBox.warning(
                self, "已取消自動填寫",
                "寫回試算表後，讀回值與輸入值不一致。"
                "請確認公式更新後，再按一次「填入」。"
            )
            return
        self._fill_waiting_for_sheet = None
        self._start_fill_worker(pending["roles"], pending["platforms"])

    def _start_fill_worker(self, roles: tuple[str, ...],
                           platforms: dict[str, str]) -> None:
        auto_entry = self.auto_entry_on_fill_both.isChecked()
        fast_control = getattr(self,"auto_fast_pair",None)
        fast_pair = bool(fast_control is not None and fast_control.isChecked() and auto_entry)
        auto_sync = bool(
            getattr(self, "auto_sync_sl_tp_after_entry", None)
            and self.auto_sync_sl_tp_after_entry.isChecked()
        )
        auto_draw = bool(
            getattr(self, "auto_draw_tv_after_entry", None)
            and self.auto_draw_tv_after_entry.isChecked()
        )
        draw_internal = bool(
            getattr(self, "tv_draw_internal", None)
            and self.tv_draw_internal.isChecked()
        )
        # Read Qt options on GUI thread, not inside the worker.
        if roles == ("internal", "external"):
            self._start(
                "填入兩邊",
                lambda: self._fill_both_task(
                    platforms["internal"], platforms["external"], auto_entry,
                    **(
                        dict(
                            sync_sl_tp=auto_sync, draw_tv=auto_draw,
                            draw_internal=draw_internal, fast_pair=fast_pair,
                        ) if auto_sync or auto_draw or draw_internal or fast_pair else {}
                    ),
                ),
                restore_after=False,
            )
        else:
            role = roles[0]
            def task() -> None:
                item = self._require_instruction()
                self.automation.fill(platforms[role], role, item)
            self._start("填入場內" if role == "internal" else "填入場外",
                        task, restore_after=False)

    def fill_role(self, role: str) -> None:
        self._launch_fill((role,))

    def fill_both(self) -> None:
        self._launch_fill(("internal", "external"))

    def _fill_both_task(
        self, internal_platform: str, external_platform: str,
        auto_entry_requested: bool = False,
        *, sync_sl_tp: bool = False, draw_tv: bool = False,
        draw_internal: bool = False, fast_pair: bool = False,
    ) -> None:
        """Fill both sides first; start guarded demo entry ONLY after readback."""
        item = self._require_instruction()
        fill_started=time.perf_counter()
        self.automation.fill(internal_platform, "internal", item)
        after_internal=time.perf_counter()
        self.automation.fill(external_platform, "external", item)
        after_external=time.perf_counter()
        emit_log=getattr(self,"log",None)
        if callable(emit_log):
            emit_log(
                "填入兩邊診斷：場內 "
                f"{(after_internal-fill_started)*1000:.0f}ms，"
                "場外 "
                f"{(after_external-after_internal)*1000:.0f}ms。"
                "若勾選自動進場，接著執行交易前核對。"
            )
        if auto_entry_requested:
            if sync_sl_tp or draw_tv or draw_internal or fast_pair:
                self._auto_entry_after_fill_both_pending(
                    internal_platform, external_platform, item,
                    sync_sl_tp=sync_sl_tp, draw_tv=draw_tv,
                    draw_internal=draw_internal, fast_pair=fast_pair,
                )
            else:
                self._auto_entry_after_fill_both_pending(
                    internal_platform, external_platform, item
                )

    def _auto_entry_after_fill_both_pending(
        self, internal_platform: str, external_platform: str,
        item: TradeInstruction, *, sync_sl_tp: bool = False,
        draw_tv: bool = False, draw_internal: bool = False,
        duplicate_confirmation: tuple[str,str,str,str] | None = None,
        manual_reconciliation_confirmed: bool = False,
        fast_pair: bool = False,
    ) -> None:
        """State machine is implemented; unverified broker UI fails closed.

        Native broker demo identity, unique ticket readback and verified
        modification controls are required before *any* order click.
        """
        self.emergency.guard()
        journal=AutoEntryJournal(APP_DIR / "demo_auto_entry_journal.json")
        port=DemoUiBrokerPort(self.automation,self.log,
                              draw_internal=draw_internal)
        flow=AutoEntryWorkflow(
            port,journal,self.emergency.guard,self.log
        )
        profile_name=self.profiles.active_name
        sheet_url=str(self.store.data["sheet"].get("spreadsheet_url","")).strip()
        def emit_receipt(*, success: bool, reason: str = "") -> bool:
            signal = getattr(
                getattr(self, "signals", None), "auto_entry_result", None
            )
            if signal is None:
                return False
            # A past journal entry is only historical evidence; this popup
            # never claims that a position is still open right now.
            key = getattr(flow, "last_key", None)
            entry = (
                journal.entry(key)
                if key and getattr(flow, "journal_current_attempt", False)
                else None
            )
            report = build_entry_status_report(
                entry, success=success, sync_requested=sync_sl_tp,
                tv_requested=draw_tv, reason=reason,
                internal_platform=internal_platform,
                external_platform=external_platform,
            )
            signal.emit(report)
            return True
        extra=(
            {
                "duplicate_confirmation":duplicate_confirmation,
                "manual_reconciliation_confirmed":manual_reconciliation_confirmed,
            }
            if duplicate_confirmation is not None else {}
        )
        try:
            result=flow.run(
                item,internal_platform,external_platform,
                profile_name,sheet_url,
                sync_sl_tp=sync_sl_tp,draw_tv=draw_tv,
                draw_internal=draw_internal,fast_pair=fast_pair,**extra,
            )
        except DuplicateEntryDecisionRequired as exc:
            exc.request={
                "item":item, "profile_name":profile_name,
                "sheet_url":sheet_url,
                "internal_platform":internal_platform,
                "external_platform":external_platform,
                "sync_sl_tp":sync_sl_tp,
                "draw_tv":draw_tv,
                "draw_internal":draw_internal,
                "fast_pair":fast_pair,
            }
            raise
        except Exception as exc:
            if emit_receipt(success=False, reason=str(exc)):
                setattr(exc, "_auto_entry_result_emitted", True)
            raise
        emit_receipt(success=True)
        self.log(
            f"Demo 兩邊成交並核對成功："
            f"{result[0].ticket} / {result[1].ticket}"
        )

    def draw_tradingview(self) -> None:
        internal_platform = self.internal_platform.currentText()
        draw_internal = self.tv_draw_internal.isChecked()

        def task() -> None:
            item = self._require_instruction()
            self.automation.draw_tradingview(
                item,
                internal_platform=internal_platform,
                entry_price_override=self.manual_entry_price,
                draw_internal=draw_internal,
            )

        self._start("繪製 TradingView", task, restore_after=False)

    def draw_tradingview_with_entry_price(self, entry_price: Decimal) -> None:
        internal_platform = self.internal_platform.currentText()
        draw_internal = self.tv_draw_internal.isChecked()

        def task() -> None:
            item = self._require_instruction()
            self.automation.draw_tradingview(
                item,
                internal_platform=internal_platform,
                entry_price_override=entry_price,
                draw_internal=draw_internal,
            )

        self._start("繪製 TradingView", task, restore_after=False)

    def sync_external_sl_tp(self) -> None:
        internal_platform = self.internal_platform.currentText()
        external_platform = self.external_platform.currentText()

        def task() -> None:
            item = self._require_instruction()
            result = self.automation.sync_external_sl_tp(
                item,
                internal_platform=internal_platform,
                external_platform=external_platform,
                entry_price_override=self.manual_entry_price,
            )
            if result:
                self.signals.external_price_result.emit(result)

        self._start("同步場外止盈止損", task, restore_after=False)

    def sync_external_sl_tp_with_entry_price(self, entry_price: Decimal) -> None:
        internal_platform = self.internal_platform.currentText()
        external_platform = self.external_platform.currentText()

        def task() -> None:
            item = self._require_instruction()
            result = self.automation.sync_external_sl_tp(
                item,
                internal_platform=internal_platform,
                external_platform=external_platform,
                entry_price_override=entry_price,
            )
            if result:
                self.signals.external_price_result.emit(result)

        self._start("同步到場外", task, restore_after=False)

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
        self._write_internal_entry_price(value)
        self.draw_tradingview()

    def update_trade_direction(self) -> None:
        value = "多" if self.internal_direction_input.currentData() == "BUY" else "空"
        self._write_trade_parameter_values({"direction": value}, "場內多空")

    def update_trade_parameter(self, key: str | None = None) -> None:
        self.update_all_trade_parameters()

    def update_all_trade_parameters(self) -> None:
        values: dict[str, object] = {}
        labels: list[str] = []
        current_direction = str(self.internal_direction_input.currentData())
        if self.instruction is not None and current_direction != self.instruction.sheet_direction:
            values["direction"] = "多" if current_direction == "BUY" else "空"
            labels.append("場內多空")
        for key, entry in self.parameter_inputs.items():
            raw = entry.text().replace(",", "").strip()
            if not raw:
                continue
            try:
                if key == "expected_sl_combined":
                    points, _ = self._parse_expected_sl_combined(raw)
                    values["expected_sl_points"] = "" if points is None else format(points, "f")
                    labels.append("預期止損點/%數")
                    continue
                if key == "daily_pnl":
                    value = self._resolve_daily_pnl_input(raw)
                    values[key] = format(value, "f")
                    labels.append("每日獲利/虧損")
                    continue
                if key == "internal_balance" and raw.startswith("~"):
                    value, daily_pnl = self._resolve_internal_balance_delta_input(raw)
                    values["internal_balance"] = format(value, "f")
                    values["daily_pnl"] = format(daily_pnl, "f")
                    labels.append("場內餘額")
                    continue
                value = Decimal(raw)
            except InvalidOperation:
                label = {
                    "daily_pnl": "每日獲利/虧損",
                    "internal_balance": "場內餘額",
                    "internal_entry_price": "場內進場點位",
                }.get(key, key)
                QMessageBox.warning(self, "交易參數", f"{label} 必須是數字。")
                return
            except AutomationError as exc:
                QMessageBox.warning(self, "交易參數", str(exc))
                return
            if key == "internal_entry_price" and value <= 0:
                QMessageBox.warning(self, "交易參數", "場內進場點位必須大於 0。")
                return
            values[key] = format(value, "f")
            labels.append(
                {
                    "daily_pnl": "每日獲利/虧損",
                    "internal_balance": "場內餘額",
                    "internal_entry_price": "場內進場點位",
                }.get(key, key)
            )
        if not values:
            self.log("沒有交易參數需要寫回。")
            return
        if "internal_entry_price" in values:
            # Unlike the retired edit-page field, this does NOT trigger TV.
            self._primary_entry_price_pending = Decimal(
                str(values["internal_entry_price"])
            )
            if (self.instruction is not None
                    and self.instruction.internal_entry_price
                    == self._primary_entry_price_pending):
                self.manual_entry_price = self._primary_entry_price_pending
                self._primary_entry_price_pending = None
        signature = self._parameter_write_signature(values)
        if self._parameter_write_active:
            if signature in {
                self._parameter_write_active_signature,
                self._parameter_write_pending_signature,
            }:
                self._notify_no_parameter_changes()
                return
            self._parameter_write_pending = True
            self._parameter_write_pending_signature = signature
            self.log("交易參數正在更新中，已排入下一次更新。")
            return
        if signature == self._parameter_write_last_signature:
            self.signals.parameter_inputs_reset.emit(list(values))
            self._notify_no_parameter_changes()
            return
        self._write_trade_parameter_values(values, "、".join(labels))

    def _parameter_write_signature(
        self, values: dict[str, object]
    ) -> tuple[tuple[str, str], ...]:
        return tuple(sorted((field, str(value)) for field, value in values.items()))

    def _notify_no_parameter_changes(self) -> None:
        self.log("交易參數沒有新的修改，略過更新。")
        self.statusBar().showMessage("交易參數沒有新的修改，略過更新。", 3500)

    def _write_trade_parameter_values(
        self,
        values: dict[str, object],
        label: str,
        *,
        busy: bool = True,
        reset_inputs: bool = True,
    ) -> None:
        source_row = self.instruction.source_row if self.instruction else None
        values = self._dedupe_same_sheet_targets(values)
        signature = self._parameter_write_signature(values)

        def task() -> None:
            previous_values = self.reader.read_field_values(
                self.store.data["sheet"],
                list(values),
                source_row=source_row,
            )
            field_targets = self.reader.write_field_values(
                self.store.data["sheet"],
                values,
                source_row=source_row,
            )
            targets = [field_targets[field] for field in values]
            self.log(f"已寫回{label}到試算表：{', '.join(targets)}。")
            warning_values = self.reader.read_a1_values(
                self.store.data["sheet"],
                ["A20", "E12"],
            )
            warnings = {
                cell: str(value).strip()
                for cell, value in warning_values.items()
                if str(value).strip()
            }
            if warnings:
                self.reader.write_a1_values(self.store.data["sheet"], previous_values)
                self.log("A20/E12 出現警示文字，已取消剛剛的調整並還原原值。")
                details = "\n".join(
                    f"{cell}: {message}" for cell, message in warnings.items()
                )
                self.signals.error.emit(
                    f"表格警示，已取消剛剛的調整：\n{details}"
                )
                self._read_sheet_task(retries=0)
                return
            if "daily_pnl" in values:
                target = field_targets.get("daily_pnl", "")
                old_value = previous_values.get(target, "")
                self._record_daily_pnl_history(old_value, values["daily_pnl"])
            if not self._parameter_write_pending:
                self._read_sheet_task(retries=0)
            if reset_inputs and not self._parameter_write_pending:
                self.signals.parameter_inputs_reset.emit(list(values))
            if busy:
                self._parameter_write_last_signature = signature

        if busy:
            self._parameter_write_active = True
            self._parameter_write_pending = False
            self._parameter_write_active_signature = signature
            self._parameter_write_pending_signature = None
            self.signals.parameter_write_busy.emit(True)

        def wrapped_task() -> None:
            try:
                task()
            finally:
                if busy:
                    should_retry = self._parameter_write_pending
                    self._parameter_write_active = False
                    self._parameter_write_pending = False
                    self._parameter_write_active_signature = None
                    self._parameter_write_pending_signature = None
                    self.signals.parameter_write_busy.emit(False)
                    if should_retry:
                        self.signals.parameter_write_retry.emit()

        self._start(f"寫回{label}", wrapped_task, hide_during=False)

    def _dedupe_same_sheet_targets(
        self, values: dict[str, object]
    ) -> dict[str, object]:
        result: dict[str, object] = {}
        seen: dict[str, str] = {}
        columns = self.store.data.get("sheet", {}).get("columns", {})
        for field, value in values.items():
            reference = str(columns.get(field, "")).strip().upper()
            key = reference or field
            if key in seen:
                self.log(
                    f"{FIELD_LABELS.get(field, field)} 和 "
                    f"{FIELD_LABELS.get(seen[key], seen[key])} 共用 {reference}，"
                    "只寫入一次。"
                )
                continue
            seen[key] = field
            result[field] = value
        return result

    def _record_daily_pnl_history(self, old_value: object, new_value: object) -> None:
        history = self.store.data.setdefault("ui", {}).setdefault(
            "daily_pnl_history", []
        )
        if not isinstance(history, list):
            history = []
            self.store.data["ui"]["daily_pnl_history"] = history
        record = {
            "time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "old": str(old_value),
            "new": str(new_value),
        }
        history.insert(0, record)
        del history[80:]
        self.store.save()
        self.profiles.save_profile(self.profiles.active_name, self.store.data)
        self.log(
            f"已記錄每日獲利/虧損：{record['old'] or '空白'} -> {record['new']}"
        )

    def show_daily_pnl_history(self) -> None:
        history = self.store.data.get("ui", {}).get("daily_pnl_history", [])
        dialog = QDialog(self)
        dialog.setWindowTitle("每日獲利/虧損紀錄")
        dialog.resize(520, 360)
        layout = QVBoxLayout(dialog)
        text = QPlainTextEdit()
        text.setReadOnly(True)
        text.setStyleSheet("font-family: Consolas; font-size: 12px;")
        if isinstance(history, list) and history:
            lines = []
            for item in history:
                if not isinstance(item, dict):
                    continue
                lines.append(
                    f"{item.get('time', '')}    "
                    f"{item.get('old', '') or '空白'} -> {item.get('new', '')}"
                )
            text.setPlainText("\n".join(lines))
        else:
            text.setPlainText("目前沒有紀錄。")
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _clear_parameter_inputs(self, fields: object) -> None:
        field_list = fields if isinstance(fields, list) else []
        for key in field_list:
            self._fill_confirmed_text.pop(key, None)
        cash_was_cleared = False
        for field in field_list:
            if field == "direction":
                continue
            if field in self.parameter_inputs:
                self.parameter_inputs[field].clear()
            if field in self._ruler_confirmed_parameters:
                self._ruler_confirmed_parameters[field] = ""
                cash_was_cleared = True
        if {"expected_sl_points", "expected_sl_percent"} & set(field_list):
            self.parameter_inputs["expected_sl_combined"].clear()
        if cash_was_cleared:
            self._refresh_ruler()

    def show_internal_external_sl_tp(self) -> None:
        try:
            item = self._require_instruction()
            raw_entry = self.parameter_inputs["internal_entry_price"].text().replace(",", "").strip()
            if raw_entry:
                entry_price = Decimal(raw_entry)
                self._queue_internal_entry_price_write(entry_price)
            else:
                entry_price = item.internal_entry_price
            if entry_price is None:
                QMessageBox.warning(
                    self,
                    "查看場內外止盈止損",
                    "請先輸入或讀取場內進場點位。",
                )
                return
            internal_sl, internal_tp = item.estimated_prices(
                item.internal_direction,
                item.internal,
                entry_price,
            )
            external_sl, external_tp = item.estimated_prices(
                item.external_direction,
                item.external,
                entry_price,
            )
        except (AutomationError, ValidationError, InvalidOperation) as exc:
            QMessageBox.warning(self, "查看場內外止盈止損", str(exc))
            return

        dialog = QDialog(self)
        dialog.setWindowTitle("場內外止盈止損")
        dialog.resize(560, 220)
        layout = QGridLayout(dialog)
        layout.setHorizontalSpacing(14)
        layout.setVerticalSpacing(10)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.addWidget(QLabel(""), 0, 0)
        layout.addWidget(QLabel("場內"), 0, 1, alignment=Qt.AlignCenter)
        layout.addWidget(QLabel("場外"), 0, 2, alignment=Qt.AlignCenter)
        rows = [
            ("止盈", internal_tp, external_tp),
            ("止損", internal_sl, external_sl),
        ]
        for row, (label, internal_value, external_value) in enumerate(rows, start=1):
            internal_text = item.format_price(internal_value)
            external_text = item.format_price(external_value)
            layout.addWidget(QLabel(label), row, 0)
            layout.addWidget(self._copyable_value_widget(internal_text), row, 1)
            layout.addWidget(self._copyable_value_widget(external_text), row, 2)
        sync_button = QPushButton("同步到場外")
        draw_button = QPushButton("繪製 TradingView 部位")
        draw_button.clicked.connect(
            lambda checked=False, value=entry_price: (
                dialog.accept(),
                self.draw_tradingview_with_entry_price(value),
            )
        )
        sync_button.clicked.connect(
            lambda checked=False, value=entry_price: (
                dialog.accept(),
                self.sync_external_sl_tp_with_entry_price(value),
            )
        )
        layout.addWidget(draw_button, len(rows) + 1, 1)
        layout.addWidget(sync_button, len(rows) + 1, 2)
        dialog.exec()

    def _queue_internal_entry_price_write(self, entry_price: Decimal) -> None:
        value = format(entry_price, "f")
        signature = self._parameter_write_signature({"internal_entry_price": value})
        self.manual_entry_price = entry_price
        self.entry_price_value.setText(value)
        self.parameter_inputs["internal_entry_price"].setText(value)
        if self._parameter_write_active:
            if signature in {
                self._parameter_write_active_signature,
                self._parameter_write_pending_signature,
            }:
                return
            self._parameter_write_pending = True
            self._parameter_write_pending_signature = signature
            self.log("場內進場點位正在等待目前更新完成後寫回。")
            return
        if signature == self._parameter_write_last_signature:
            self.parameter_inputs["internal_entry_price"].clear()
            return
        self._write_trade_parameter_values(
            {"internal_entry_price": value},
            "場內進場點位",
        )

    def _copyable_value_widget(self, value: str) -> QWidget:
        widget = QWidget()
        layout = QHBoxLayout(widget)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(6)
        value_input = QLineEdit(value)
        value_input.setReadOnly(True)
        value_input.setMinimumWidth(120)
        copy_button = QPushButton("複製")
        copy_button.setFixedWidth(58)
        copy_button.clicked.connect(
            lambda checked=False, text=value: QApplication.clipboard().setText(text)
        )
        layout.addWidget(value_input)
        layout.addWidget(copy_button)
        return widget

    def _write_internal_entry_price(self, value: Decimal) -> None:
        if self.instruction is None:
            return
        try:
            target = self.reader.write_value(
                self.store.data["sheet"],
                "internal_entry_price",
                format(value, "f"),
                source_row=self.instruction.source_row,
            )
        except ValidationError as exc:
            self.log(f"未寫回試算表：{exc}")
            return
        self.log(f"已寫回場內實際進場價到試算表 {target}。")

    def _require_instruction(self) -> TradeInstruction:
        if self.instruction is None:
            raise AutomationError("請先讀取 Google 試算表，再執行這項操作。")
        return self._instruction_with_parameter_overrides(self.instruction)

    def _instruction_with_parameter_overrides(
        self, instruction: TradeInstruction
    ) -> TradeInstruction:
        values: dict[str, Decimal | None] = {}
        labels = {
            "daily_pnl": "每日獲利/虧損",
            "internal_balance": "場內餘額",
            "expected_sl_combined": "預期止損點/%數",
            "internal_entry_price": "場內進場點位",
        }
        for key, entry in self.parameter_inputs.items():
            raw = entry.text().replace(",", "").strip()
            if not raw:
                continue
            if key == "expected_sl_combined":
                points, _ = self._parse_expected_sl_combined(raw)
                values["expected_sl_points"] = points
                continue
            try:
                if key == "daily_pnl":
                    values[key] = self._resolve_daily_pnl_input(raw)
                elif key == "internal_balance" and raw.startswith("~"):
                    balance, daily_pnl = self._resolve_internal_balance_delta_input(raw)
                    values["internal_balance"] = balance
                    values["daily_pnl"] = daily_pnl
                else:
                    values[key] = Decimal(raw)
            except InvalidOperation:
                raise AutomationError(f"{labels[key]} 必須是數字。") from None
            if key == "internal_entry_price" and values[key] <= 0:
                raise AutomationError("場內進場點位必須大於 0。")
        expected_points = values.get(
            "expected_sl_points", instruction.expected_sl_points
        )
        return replace(
            instruction,
            sheet_direction=str(self.internal_direction_input.currentData()),
            daily_pnl=values.get("daily_pnl", instruction.daily_pnl),
            internal_balance=values.get("internal_balance", instruction.internal_balance),
            internal_entry_price=values.get(
                "internal_entry_price", instruction.internal_entry_price
            ),
            expected_sl_points=expected_points,
        )

    def _parse_expected_sl_combined(
        self, raw: str
    ) -> tuple[Decimal | None, Decimal | None]:
        separators = ["/", "／", "|", "｜"]
        parts = [raw]
        for separator in separators:
            if separator in raw:
                parts = raw.split(separator, 1)
                break
        try:
            points = Decimal(parts[0].replace("%", "").strip()) if parts[0].strip() else None
            percent = (
                Decimal(parts[1].replace("%", "").strip())
                if len(parts) > 1 and parts[1].strip()
                else None
            )
        except InvalidOperation:
            raise AutomationError("預期止損點/%數 必須是數字，例如 -6.81 / -1.2。") from None
        return points, percent

    def _resolve_daily_pnl_input(self, raw: str) -> Decimal:
        text = raw.replace(",", "").strip()
        if text.startswith(("=+", "=-")):
            if self.instruction is None or self.instruction.daily_pnl is None:
                base = Decimal("0")
            else:
                base = self.instruction.daily_pnl
            return _resolve_relative_decimal(text, base)
        return _resolve_relative_decimal(text, None)

    def _resolve_internal_balance_delta_input(
        self, raw: str
    ) -> tuple[Decimal, Decimal]:
        if self.instruction is None:
            raise AutomationError("請先讀取試算表。")
        text = raw.replace(",", "").strip()
        if not text.startswith("~"):
            value = Decimal(text)
            return value, self.instruction.daily_pnl or Decimal("0")
        new_balance = Decimal(text[1:].strip())
        old_balance = self.instruction.internal_balance or Decimal("0")
        current_pnl = self.instruction.daily_pnl or Decimal("0")
        return new_balance, current_pnl + (new_balance - old_balance)

    def open_calibration(self, platform: str) -> None:
        was_minimized = self.isMinimized()
        self.showMinimized()
        try:
            CalibrationDialog(self, platform).exec()
        finally:
            self._refresh_calibration_badges()
            if not was_minimized:
                self.showNormal()
                self.raise_()
                self.activateWindow()

    def bind_role_window(self, role: str) -> bool:
        """Single small nonmodal panel: current binding, rebind, final receipt."""
        platform = (
            self.internal_platform.currentText() if role == "internal"
            else self.external_platform.currentText()
        )
        role_text = "場內" if role == "internal" else "場外"
        current = str(
            self.store.data["platforms"].get(platform, {})
            .get("window_title", {}).get(role, "")
        )
        previous = getattr(self, "_window_binding_dialog", None)
        if previous is not None:
            previous.close()
        dialog = QDialog(self)
        dialog.setObjectName("singleWindowBindingDialog")
        dialog.setWindowTitle(f"{role_text}視窗綁定｜{platform}")
        dialog.setMinimumWidth(450)
        layout = QVBoxLayout(dialog)
        current_label = QLabel(
            f"平台：{platform}｜{role_text}\n"
            f"目前綁定：{current or '尚未綁定'}", dialog
        )
        current_label.setWordWrap(True)
        current_label.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(current_label)
        outcome = QLabel(
            "確認目前綁定後，可在此更改。"
            "按下更改後，3 秒內切換到要綁定的交易平台視窗（不用移動滑鼠）。",dialog
        )
        outcome.setWordWrap(True)
        outcome.setTextInteractionFlags(Qt.TextSelectableByMouse)
        outcome.setObjectName("windowBindingResultLabel")
        layout.addWidget(outcome)
        buttons = QHBoxLayout()
        change = QPushButton("更改綁定" if current else "建立綁定",dialog)
        change.setObjectName("windowBindingChangeButton")
        close = QPushButton("關閉",dialog)
        close.setObjectName("windowBindingConfirmButton")
        close.clicked.connect(dialog.close)
        buttons.addStretch()
        buttons.addWidget(change)
        buttons.addWidget(close)
        layout.addLayout(buttons)
        dialog.setProperty("boundRole",role)
        dialog.setProperty("boundPlatform",platform)
        dialog.setProperty("boundPattern",current)
        self._window_binding_dialog = dialog

        def begin() -> None:
            # On repeat capture, report the most recently saved binding
            # rather than the binding at first opening of this panel.
            before_pattern = str(dialog.property("boundPattern") or "")
            # The receipt is temporarily topmost *after* capture. Turn that
            # flag off for a subsequent capture so the dialog will not cover
            # the broker window under the cursor during the countdown.
            if dialog.windowFlags() & Qt.WindowStaysOnTopHint:
                dialog.setWindowFlag(Qt.WindowStaysOnTopHint, False)
                dialog.show()
            change.setEnabled(False)
            outcome.setText(
                "等待擷取：請在 3 秒內將目標交易平台切到最前景。"
                "擷取期間不會下單。"
            )
            origin_profile = self.profiles.active_name
            def task() -> None:
                try:
                    self.log(f"準備綁定{role_text} {platform}：3 秒後擷取最前景視窗，無須移動滑鼠。")
                    for count in (3,2,1):
                        self.log(f"綁定{role_text} {platform}：{count}")
                        time.sleep(1)
                        self.emergency.guard()
                    if self.profiles.active_name != origin_profile:
                        raise AutomationError("方案已切換，請重新開啟綁定。")
                    selected = (
                        self.internal_platform.currentText()
                        if role == "internal" else self.external_platform.currentText()
                    )
                    if selected != platform:
                        raise AutomationError("平台已變更，請重新開啟綁定。")
                    target = self.windows.foreground_top_level_window()
                    # Qt/dialog itself or an unrelated program is NOT an
                    # eligible target. Do not silently bind the wrong HWND.
                    target_pid = process_id_for_window(
                        getattr(target, "handle", 0)
                    )
                    # GUI HWND methods are not thread-safe. The worker
                    # can compare against our process ID without touching Qt.
                    own_pid = os.getpid()
                    if target_pid and own_pid and target_pid == own_pid:
                        raise AutomationError(
                            "最前景仍是對沖小幫手。請切換到目標交易平台後重新綁定。"
                        )
                    title = str(target.title)
                    if platform == "cTrader" and not (
                        "ctrader" in title.lower()
                        or "gooeytrade" in title.lower()
                    ):
                        raise AutomationError(
                            "最前景視窗不像 cTrader，未修改綁定。"
                            "請先將 cTrader 切到最上層。"
                        )
                    pattern = _window_title_pattern(platform,title)
                    # Capture optional account info before writing binding.
                    account_message = ""
                    point = self.store.data["platforms"].get(
                        platform, {}
                    ).get("points",{}).get("account_number")
                    account_number = None
                    if platform == "cTrader" and point:
                        account_number = self.windows.read_account_number(target,point)
                        account_message = f"；Demo 帳號已核對：{account_number}"
                    elif platform == "cTrader":
                        account_message = "；帳號位置未校準"
                    self._save_bound_window(platform,role,pattern)
                    if account_number is not None:
                        self._save_bound_account(platform,role,account_number)
                    self.signals.window_binding_result.emit({
                        "role":role,"platform":platform,
                        "ok":True,"old":before_pattern,
                        "new":pattern,"title":target.title,
                        "note":account_message,
                    })
                    self.log(
                        f"已更改{role_text} {platform} 視窗："
                        f"{before_pattern or '未綁定'} → {pattern}"
                    )
                except Exception as exc:
                    self.signals.window_binding_result.emit({
                        "role":role,"platform":platform,
                        "ok":False,"old":before_pattern,"message":str(exc),
                    })
                    self.log(f"{role_text} {platform} 綁定未完成：{exc}")
            self._start(f"綁定{role_text}視窗",task,hide_during=False)
        change.clicked.connect(begin)
        dialog.show()
        dialog.raise_()
        return True

    def _on_window_binding_result(self, result: dict) -> None:
        """UI-thread receipt in the SAME panel; no separate success popup."""
        dialog = getattr(self,"_window_binding_dialog",None)
        if dialog is None:
            return
        if (dialog.property("boundRole")!=result.get("role") or
            dialog.property("boundPlatform")!=result.get("platform")):
            return
        outcome = dialog.findChild(QLabel,"windowBindingResultLabel")
        button = dialog.findChild(QPushButton,"windowBindingChangeButton")
        if button is not None:
            button.setEnabled(True)
        # Both internal and external bindings share the same receipt UI.
        # Once a capture ends, the next action must be unambiguous:
        # either retry selection or accept the shown binding and dismiss it.
        confirm = dialog.findChild(QPushButton,"windowBindingConfirmButton")
        if button is not None:
            button.setText("重新綁定")
        if confirm is not None:
            confirm.setText("確認")
            confirm.setDefault(True)
        if result.get("ok"):
            dialog.setProperty("boundPattern",result["new"])
            platform=result["platform"]
            role=result["role"]
            current_label = dialog.layout().itemAt(0).widget()
            current_label.setText(
                f"平台：{platform}｜{'場內' if role=='internal' else '場外'}\n"
                f"目前綁定：{result['new']}"
            )
            outcome.setText(
                f"✓ 已更改完成\n"
                f"原本：{result['old'] or '未綁定'}\n"
                f"現在：{result['new']}\n"
                f"擷取視窗：{result['title']}{result.get('note','')}"
            )
        else:
            outcome.setText(
                f"未更改原本的綁定。原因：{result.get('message','未知錯誤')}"
            )
        # Give the user an immediate visible receipt even when the broker
        # window has foreground focus. Raising a normal QDialog is not
        # sufficient on Windows: make only this finished receipt topmost,
        # without bringing cTrader/MT5 to the foreground or sending keys.
        dialog.setWindowTitle(
            "✓ 視窗綁定完成" if result.get("ok") else "視窗綁定未完成"
        )
        if not (dialog.windowFlags() & Qt.WindowStaysOnTopHint):
            dialog.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        dialog.show()
        dialog.raise_()
        dialog.activateWindow()
        QApplication.alert(dialog, 4000)

    def open_settings(self) -> None:
        dialog = SettingsDialog(self)
        if dialog.exec() == QDialog.Accepted:
            self.automation.config = self.store.data
            self.log("設定已儲存。")

    def open_sheet_url(self) -> None:
        url = str(self.store.data["sheet"].get("spreadsheet_url", "")).strip()
        if not url:
            QMessageBox.warning(self, "表格網址", "目前方案沒有設定試算表網址。")
            return
        webbrowser.open(url)
        self.log("已開啟表格網址。")

    def open_help(self) -> None:
        dialog = QDialog(self)
        dialog.setWindowTitle("Help")
        dialog.resize(690, 490)
        layout = QVBoxLayout(dialog)
        text = QTextBrowser()
        text.setReadOnly(True)
        text.setOpenLinks(False)
        text.setHtml(
            """
            <style>
              body { font-size: 13px; line-height: 1.5; }
              h2 { margin: 12px 0 5px; }
              li { margin-bottom: 3px; }
              a { color: #af9aff; text-decoration: none; }
            </style>
            <h2>快速開始</h2>
            <ol>
              <li>選擇方案與場內／場外平台，先<a href="action:settings">設定試算表</a>。</li>
              <li><a href="action:bind_internal">綁定場內</a>、<a href="action:bind_external">綁定場外</a>視窗；將交易平台視窗最大化。</li>
              <li>從左到右依序<a href="action:calibrate_ctrader">校準 cTrader</a>、
              <a href="action:calibrate_mt5">校準 MT5</a> 或
              <a href="action:calibrate_tv">校準 TradingView</a>。
              MT5 第二階段請先自行開啟新訂單視窗。</li>
              <li>「讀取試算表」核對方向、手數及止盈止損，再按「填入場內／場外／兩邊」。</li>
            </ol>
            <h2>校準前建立模擬帳戶</h2>
            <p>若還沒有方便測試的持倉，可前往
            <b>IC Markets 官方網站</b>申請模擬帳戶，分別選擇
            <b>cTrader</b> 與 <b>MetaTrader 5 (MT5)</b>，
            在對應桌面平台登入後，再逐階段校準。
            校準持倉列表與修改視窗時，請先自行開啟已有的
            <b>Demo 持倉</b>與修改視窗。無持倉時可先校準進場前欄位；
            不需要為了校準使用 Live 帳戶。校準掃描本身不會下單。</p>
            <p>校準頁標籤的 (6/7) 是已儲存位置數/總數，
            不是交易安全驗收。紅點可在「顯示設定」關閉。</p>
            <h2>填入與進場</h2>
            <p>未勾選「自動進場」時，填入只會寫入交易欄位；
            勾選後雙 Demo 自動進場功能可能真的送出模擬訂單。
            缺校準點會列出清單；數值未按 Enter 則會先詢問確認。
            按 ESC 可中止後續動作。</p>
            <h2>交易參數與工具</h2>
            <p>餘額及每日盈虧：輸入後按 Enter 或「更新」才更新進度尺。
            每日盈虧可用 <code>=+30</code> 或 <code>=-30</code> 調整。
            「場內進場點位」是寫回表格的參數；
            成功寫回並讀回確認後可作為手動價格；不會自動繪製 TV。</p>
            <p>同步場外 SL／TP、繪製 TradingView 目前仍為可單獨執行的功能；
            進場後全自動工作流仍待實測。各平台視窗位置或縮放變動後請重新校準。</p>
            <p><a href="action:sheet_url">開啟試算表</a></p>
            """
        )
        text.anchorClicked.connect(
            lambda url: self._handle_help_link(dialog, text, url.toString())
        )
        layout.addWidget(text)
        buttons = QDialogButtonBox(QDialogButtonBox.Close)
        buttons.rejected.connect(dialog.reject)
        layout.addWidget(buttons)
        dialog.exec()

    def _handle_help_link(
        self, dialog: QDialog, browser: QTextBrowser, link: str
    ) -> None:
        if link.startswith("#"):
            browser.scrollToAnchor(link[1:])
            return
        if not link.startswith("action:"):
            return
        action = link.removeprefix("action:")
        dialog.accept()
        QTimer.singleShot(0, lambda: self._run_help_action(action))

    def _run_help_action(self, action: str) -> None:
        reopen_delay: int | None = None
        if action == "settings":
            self.open_settings()
            reopen_delay = 150
        elif action == "bind_internal":
            started = self.bind_role_window("internal")
            reopen_delay = None if started else 150
        elif action == "bind_external":
            started = self.bind_role_window("external")
            reopen_delay = None if started else 150
        elif action == "calibrate_ctrader":
            self.open_calibration("cTrader")
            reopen_delay = 150
        elif action == "calibrate_mt5":
            self.open_calibration("MT5")
            reopen_delay = 150
        elif action == "calibrate_tv":
            self.open_calibration("TradingView")
            reopen_delay = 150
        elif action == "sheet_url":
            self.open_sheet_url()
            reopen_delay = 150
        if reopen_delay is not None:
            QTimer.singleShot(reopen_delay, self.open_help)

    def save_config(self) -> None:
        self.store.save()
        self.profiles.save_profile(self.profiles.active_name, self.store.data)

    def _save_bound_window(self, platform: str, role: str, pattern: str) -> None:
        self.store.data["platforms"][platform]["window_title"][role] = pattern
        self.store.save()
        self.profiles.save_profile(self.profiles.active_name, self.store.data)
        persisted = self.profiles.load_profile(self.profiles.active_name)
        saved_pattern = persisted["platforms"][platform]["window_title"][role]
        if saved_pattern != pattern:
            raise RuntimeError(
                "Window binding was not saved to the active profile."
            )
        self.store.data = persisted
        self.store.save()
        self.automation.config = self.store.data

    def save_ui_state(self) -> None:
        self.store.data["ui"].update(
            {
                "internal_platform": self.internal_platform.currentText(),
                "external_platform": self.external_platform.currentText(),
                "tv_draw_internal": self.tv_draw_internal.isChecked(),
                "show_calibration_badges": (
                    self.show_calibration_badges.isChecked()
                    if hasattr(self, "show_calibration_badges")
                    else bool(self.store.data["ui"].get(
                        "show_calibration_badges", True))
                ),
                "auto_entry_on_fill_both": self.auto_entry_on_fill_both.isChecked(),
                "auto_fast_pair": (
                    self.auto_fast_pair.isChecked()
                    if hasattr(self,"auto_fast_pair") else False
                ),
                "auto_sync_sl_tp_after_entry": self.auto_sync_sl_tp_after_entry.isChecked(),
                "auto_draw_tv_after_entry": self.auto_draw_tv_after_entry.isChecked(),
            }
        )
        self.save_config()

    def _refresh_auto_option_dependencies(self) -> None:
        """Update the visual hierarchy without triggering workflow actions.

        Checkboxes are unselected with blocked Qt signals, not by calling
        the confirmation handlers recursively.
        """
        first = getattr(self, "auto_entry_on_fill_both", None)
        second = getattr(self, "auto_sync_sl_tp_after_entry", None)
        third = getattr(self, "auto_draw_tv_after_entry", None)
        fast = getattr(self, "auto_fast_pair", None)
        if first is None or second is None or third is None:
            return
        first_checked = first.isChecked()
        if fast is not None:
            if not first_checked and fast.isChecked():
                prev=fast.blockSignals(True)
                fast.setChecked(False)
                fast.blockSignals(prev)
            fast.setEnabled(first_checked)
        if not first_checked and second.isChecked():
            was_blocked = second.blockSignals(True)
            second.setChecked(False)
            second.blockSignals(was_blocked)
        second.setEnabled(first_checked)
        second.setToolTip(
            "必須先勾選「自動進場」。目前此功能只儲存偏好，尚不自動同步。"
            if not first_checked else
            "進場確認後預留同步 SL/TP；目前尚未接入自動執行。"
        )
        second_checked = first_checked and second.isChecked()
        if not second_checked and third.isChecked():
            was_blocked = third.blockSignals(True)
            third.setChecked(False)
            third.blockSignals(was_blocked)
        third.setEnabled(second_checked)
        third.setToolTip(
            "必須先勾選「同步 SL/TP」。目前此功能只儲存偏好，尚不自動繪製。"
            if not second_checked else
            "同步 SL/TP 後預留繪製 TV；目前尚未接入自動執行。"
        )

    def _confirm_fast_pair_toggle(self, enabled: bool) -> None:
        if not enabled:
            if hasattr(self, "save_ui_state"):
                self.save_ui_state()
            self.log("已關閉快速雙邊進場，恢復先確認場內再進場場外。")
            return
        if not self.auto_entry_on_fill_both.isChecked():
            accepted=QMessageBox.No
        else:
            accepted=QMessageBox.question(
                self,"確認快速雙邊進場（僅 Demo）",
                "快速雙邊：兩邊表單先通過完整核對，之後"
                "連續點擊 cTrader 與 MT5 各一次，才讀取兩邊實際成交。\n\n"
                "危險：如果第一邊被拒單，第二邊仍可能成交，"
                "也可能短暫沒有確認任何一邊的止損。"
                "本模式不保證同時成交，不會自動重試、平倉或補單。\n"
                "支援 cTrader / MT5 場內場外互換、雙 Demo。\n"
                "MT5 當場內時，會在兩邊送單後依實際成交價修正"
                "場內 SL/TP；修正完成前仍可能有單邊／"
                "保護價格偏差風險。\n\n"
                "確認仍要為本次測試啟用快速進場？",
                QMessageBox.Yes | QMessageBox.No,QMessageBox.No,
            )
        if accepted!=QMessageBox.Yes:
            was=self.auto_fast_pair.blockSignals(True)
            self.auto_fast_pair.setChecked(False)
            self.auto_fast_pair.blockSignals(was)
            return
        if hasattr(self,"save_ui_state"):
            self.save_ui_state()
        self.log("已明確啟用快速雙邊 Demo 偏好；送單仍須按填入兩邊並通過核對。")

    def _confirm_auto_entry_toggle(self, enabled: bool) -> None:
        """Explicit opt-in; switching off takes effect immediately."""
        if not enabled:
            TradingHelperApp._refresh_auto_option_dependencies(self)
            self.save_ui_state()
            self.log("已關閉「填入兩邊時自動進場」；維持原本只填欄位流程。")
            return
        accepted = QMessageBox.question(
            self,
            "確認啟用自動進場選項",
            "要開啟「填入兩邊時自動進場」嗎？\n"
            "此選項只會作用於「填入兩邊」，不影響單獨填入場內／場外。\n\n"
            "注意：此選項僅允許經過確認的兩個 Demo 帳戶進場。\n"
            "兩邊填寫、方向、手數和 SL/TP 核對成功後才會嘗試送單；"
            "成交與修改持倉都必須再次讀回確認。\n"
            "如果任何資料不明，會停止而不會重複送單或自行平倉。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if accepted != QMessageBox.Yes:
            self.auto_entry_on_fill_both.blockSignals(True)
            self.auto_entry_on_fill_both.setChecked(False)
            self.auto_entry_on_fill_both.blockSignals(False)
            TradingHelperApp._refresh_auto_option_dependencies(self)
            return
        TradingHelperApp._refresh_auto_option_dependencies(self)
        self.save_ui_state()
        self.log("已開啟 Demo 自動進場；只有雙 Demo、持倉辨識與表單均可靠確認後才允許送單。")

    def _confirm_future_auto_option(
        self, checkbox: QCheckBox, enabled: bool, label: str
    ) -> None:
        """Store future opt-in only; never run broker/TV workflows."""
        if enabled:
            if (checkbox is self.auto_sync_sl_tp_after_entry
                    and not self.auto_entry_on_fill_both.isChecked()):
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                TradingHelperApp._refresh_auto_option_dependencies(self)
                return
            if (checkbox is self.auto_draw_tv_after_entry
                    and not self.auto_sync_sl_tp_after_entry.isChecked()):
                checkbox.blockSignals(True)
                checkbox.setChecked(False)
                checkbox.blockSignals(False)
                TradingHelperApp._refresh_auto_option_dependencies(self)
                return
        if not enabled:
            TradingHelperApp._refresh_auto_option_dependencies(self)
            self.save_ui_state()
            return
        accepted = QMessageBox.question(
            self,
            "確認預留自動化選項",
            f"要記住「{label}」為勾選狀態嗎？\n\n"
            "此選項會在雙 Demo 自動進場並核對持倉後依順序執行。\n"
            "必須唯一辨識正確持倉、再次確認修改結果；"
            "若失敗將立即停止，不會補送單。",
            QMessageBox.Yes | QMessageBox.No,
            QMessageBox.No,
        )
        if accepted != QMessageBox.Yes:
            checkbox.blockSignals(True)
            checkbox.setChecked(False)
            checkbox.blockSignals(False)
            TradingHelperApp._refresh_auto_option_dependencies(self)
            return
        TradingHelperApp._refresh_auto_option_dependencies(self)
        self.save_ui_state()
        self.log(f"已啟用 Demo 自動化後續步驟：「{label}」；未通過安全核對會停止。")

    def _save_bound_account(self, platform: str, role: str, account_number: str) -> None:
        platform_config = self.store.data["platforms"][platform]
        platform_config.setdefault("account_number", {})[role] = account_number
        self.store.save()
        self.profiles.save_profile(self.profiles.active_name, self.store.data)
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
            self.automation.profile_name = name
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
            self.store.data = self.profiles.load_profile(name)
            self.store.save()
            self.automation.config = self.store.data
            self.automation.profile_name = name
            self._refresh_profile_combo(name)
            # Reflect the new scheme's disarmed automation without any broker I/O.
            self._apply_profile_ui()
            self.log(f"已建立方案：{name}（自動化預設關閉；cTrader 輸入方式為預設）")
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
            self.store.data = self.profiles.load_profile(name)
            self.store.save()
            self.automation.config = self.store.data
            self.automation.profile_name = name
            self._refresh_profile_combo(name)
            self.log(
                f"方案已重新命名：{old_name} → {name}；"
                "cTrader SL/TP 輸入方式視為新方案，恢復預設。"
            )
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
            self.automation.profile_name = active
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
        self.tv_draw_internal.blockSignals(True)
        badge_toggle=getattr(self,"show_calibration_badges",None)
        if badge_toggle is not None:
            badge_toggle.blockSignals(True)
        self.auto_entry_on_fill_both.blockSignals(True)
        self.auto_sync_sl_tp_after_entry.blockSignals(True)
        self.auto_draw_tv_after_entry.blockSignals(True)
        fast_control=getattr(self,"auto_fast_pair",None)
        if fast_control is not None:
            fast_control.blockSignals(True)
        self.internal_platform.setCurrentText(ui["internal_platform"])
        self.external_platform.setCurrentText(ui["external_platform"])
        self.tv_draw_internal.setChecked(bool(ui.get("tv_draw_internal", False)))
        if badge_toggle is not None:
            badge_toggle.setChecked(
                bool(ui.get("show_calibration_badges", True))
            )
        self.auto_entry_on_fill_both.setChecked(
            bool(ui.get("auto_entry_on_fill_both",False))
        )
        self.auto_sync_sl_tp_after_entry.setChecked(
            bool(ui.get("auto_sync_sl_tp_after_entry",False))
        )
        self.auto_draw_tv_after_entry.setChecked(
            bool(ui.get("auto_draw_tv_after_entry",False))
        )
        if fast_control is not None:
            fast_control.setChecked(bool(ui.get("auto_fast_pair",False)))
        self.internal_platform.blockSignals(False)
        self.external_platform.blockSignals(False)
        self.tv_draw_internal.blockSignals(False)
        if badge_toggle is not None:
            badge_toggle.blockSignals(False)
        self.auto_entry_on_fill_both.blockSignals(False)
        self.auto_sync_sl_tp_after_entry.blockSignals(False)
        self.auto_draw_tv_after_entry.blockSignals(False)
        if fast_control is not None:
            fast_control.blockSignals(False)
        TradingHelperApp._refresh_auto_option_dependencies(self)
        # Dependencies are checked without emitting clicked/toggled events;
        # a restored preference never triggers broker I/O by itself.
        ui["auto_entry_on_fill_both"] = self.auto_entry_on_fill_both.isChecked()
        ui["auto_fast_pair"] = (
            fast_control.isChecked() if fast_control is not None else False
        )
        ui["auto_sync_sl_tp_after_entry"] = (
            self.auto_sync_sl_tp_after_entry.isChecked()
        )
        ui["auto_draw_tv_after_entry"] = (
            self.auto_draw_tv_after_entry.isChecked()
        )
        self.instruction = None
        self._fill_waiting_for_sheet = None
        self._fill_confirmed_text.clear()
        self.ruler_sheet_values = None
        self.ruler_sheet_status = "切換方案後，請等待試算表載入"
        self._ruler_confirmed_parameters = {
            "internal_balance": "", "daily_pnl": "",
        }
        self.manual_entry_price = None
        self._primary_entry_price_pending = None
        self.entry_price_input.clear()
        self.entry_price_value.clear()
        self.internal_direction_input.setCurrentIndex(0)
        for entry in self.parameter_inputs.values():
            entry.clear()
            entry.setPlaceholderText("")
        for label in self.data_labels.values():
            label.setText("-")
        if hasattr(self, "_refresh_ruler"):
            self._refresh_ruler()
        if hasattr(self,"_refresh_calibration_badges"):
            self._refresh_calibration_badges()

    def _refresh_profile_combo(self, selected: str) -> None:
        self._profile_switching = True
        self.profile_combo.set_names(self.profiles.names())
        self.profile_combo.setCurrentText(selected)
        self._profile_switching = False

    def _set_profile_combo(self, selected: str) -> None:
        self._profile_switching = True
        self.profile_combo.setCurrentText(selected)
        self._profile_switching = False

    def reorder_profiles(self, names: list[str]) -> None:
        if self._profile_switching:
            return
        self.profiles.reorder(names)
        self.log("已更新方案順序。")

    def closeEvent(self, event: QCloseEvent) -> None:
        self.save_ui_state()
        self.emergency.close()
        event.accept()


class CalibrationDialog(QDialog):
    capture_finished = Signal(str)
    inspection_finished = Signal(object)
    hover_finished = Signal(object)
    inventory_finished = Signal(object)

    def __init__(self, app: TradingHelperApp, platform: str):
        super().__init__(app)
        self.app = app
        self.platform = platform
        self.setWindowTitle(f"校準 {platform}")
        self.resize(850, 550)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        layout = QVBoxLayout(self)
        descriptions = {
            "cTrader": "請將交易平台視窗最大化，從左到右依順序自動校準欄位。",
            "MT5": "請將交易平台視窗最大化，從左到右依順序自動校準欄位。",
            "TradingView": "此平台目前使用手動位置校準；選擇繪圖控制項後按「擷取所選位置」。",
        }
        layout.addWidget(QLabel(descriptions.get(platform, "選擇項目後校準；舊設定會保留到你主動變更。")))
        self.radios: dict[str, QRadioButton] = {}
        self._calibration_radio_group = QButtonGroup(self)
        self._calibration_tabs = QTabWidget(self)
        # Long tab captions produce tiny arrow controls at the right edge.
        # Use short descriptive titles; instructions remain inside each page.
        self._calibration_tabs.tabBar().setUsesScrollButtons(False)
        self._stage_keys: list[tuple[str, ...]] = []
        self._stage_titles: list[str] = []
        self._stage_dots: list[QLabel] = []
        keys_all = tuple(key for key, _ in CALIBRATION_TARGETS[platform])
        if platform == "cTrader":
            after_keys = set(POSITION_GRID_KEYS+POSITION_EDIT_KEYS)
            before = tuple(key for key in keys_all if key not in after_keys)
            grid = tuple(key for key in keys_all if key in POSITION_GRID_KEYS)
            modify = tuple(key for key in keys_all if key in POSITION_EDIT_KEYS)
            stages = (
                ("① 進場前", before),
                ("② 持倉列表", grid),
                ("③ 修改視窗", modify),
            )
        elif platform in {"MT5", "BYBIT MT5", "原版MT5"}:
            # In MT5 the toolbar launcher is in the MAIN window, while
            # order fields are in a distinct popup. Mixing both in one
            # inventory makes one of them appear "not found" every time.
            launcher = ("new_order_button", "trade_tab")
            order_fields = (
                "lot_input", "ask_price", "sl_input", "tp_input",
                "order_submit_buy", "order_submit_sell",
            )
            grid = tuple(key for key in keys_all if key in POSITION_GRID_KEYS)
            modify = tuple(key for key in keys_all if key in POSITION_EDIT_KEYS)
            stages = (
                ("① 主視窗", launcher),
                ("② 新訂單", order_fields),
                ("③ 持倉列表", grid),
                ("④ 修改視窗", modify),
            )
        else:
            stages = (("繪圖工具與價格欄位", keys_all),)
        for stage_index, (title, stage_keys) in enumerate(stages):
            page = QWidget(self._calibration_tabs)
            page_layout = QVBoxLayout(page)
            selected_keys = set(stage_keys)
            for key, label in CALIBRATION_TARGETS[platform]:
                if key not in selected_keys:
                    continue
                radio = QRadioButton(label, page)
                if stage_index == 0 and key == stage_keys[0]:
                    radio.setChecked(True)
                self.radios[key] = radio
                self._calibration_radio_group.addButton(radio)
                page_layout.addWidget(radio)
            if platform in {"MT5", "BYBIT MT5", "原版MT5"} and stage_index == 0:
                page_layout.addWidget(QLabel("第 1 步：校準主視窗的「新訂單」按鈕。"))
            if platform in {"MT5", "BYBIT MT5", "原版MT5"} and stage_index == 1:
                page_layout.addWidget(QLabel(
                    "請先開啟 MT5「新訂單」視窗，再按自動尋找。"
                ))
            if set(stage_keys)==set(POSITION_GRID_KEYS):
                row_name="TP" if platform=="cTrader" else "SL"
                page_layout.addWidget(QLabel(
                    "先在平台顯示 Positions／交易列表，先校準進場價、手數及訂單列；"
                    f"訂單列以 {row_name} 欄為雙擊候選，這裡不會實際雙擊。"
                ))
            elif set(stage_keys)==set(POSITION_EDIT_KEYS):
                page_layout.addWidget(QLabel(
                    "你必須先自行雙擊持倉列開啟修改視窗，再掃止損、止盈、確認按鈕。"
                    "本功能不會點擊 Protect／Modify。"
                ))
            if platform != "TradingView":
                scan = QPushButton("自動尋找此階段欄位（唯讀）", page)
                scan.setToolTip("只找目前開啟畫面的候選位置；不儲存、不填值、不操作交易平台")
                scan.clicked.connect(self.scan_all_calibration)
                page_layout.addWidget(scan)
            else:
                page_layout.addWidget(QLabel(
                    "TradingView 尚無可靠的一鍵 UIA 掃描。"
                    "先以手動校準，不會假裝已自動找到位置。"
                ))
            page_layout.addStretch()
            self._stage_keys.append(tuple(stage_keys))
            self._stage_titles.append(title)
            tab_idx = self._calibration_tabs.addTab(page, title)
            dot = QLabel("●")
            dot.setObjectName("stageCalibrationIncompleteDot")
            dot.setFixedSize(10, 13)
            dot.setStyleSheet(
                "color:#fa5362;font-size:12px;background:transparent;"
            )
            dot.setAttribute(Qt.WA_TransparentForMouseEvents, True)
            self._calibration_tabs.tabBar().setTabButton(
                tab_idx, QTabBar.RightSide, dot
            )
            self._stage_dots.append(dot)
        self._refresh_stage_progress()
        self._calibration_tabs.currentChanged.connect(self._select_stage_radio)
        layout.addWidget(self._calibration_tabs)
        # Detailed calibration precautions live in Help and tooltips.
        # The top instruction is the only permanent explanatory sentence.
        self.result = QLabel("")
        self.result.setStyleSheet("color: #176b35;")
        layout.addWidget(self.result)
        layout.addStretch()
        buttons = QHBoxLayout()
        # Keep diagnostic hover/UIA methods in source for developers, but
        # do not expose two redundant test buttons to everyday users.
        capture = QPushButton("手動擷取所選欄位")
        capture.setToolTip("需要由你把滑鼠移到欄位上；此操作會覆寫該項已儲存的位置")
        capture.clicked.connect(self.capture)
        show_position = QPushButton("查看已校準位置")
        show_position.clicked.connect(self.show_position)
        close = QPushButton("關閉")
        close.clicked.connect(self.accept)
        # Manual capture is still available, but hidden by default while
        # auto UIA inventory is the main path. TradingView has no safe auto
        # inventory yet, so manual tools remain visible there.
        self.manual_capture_button = capture
        self.manual_position_button = show_position
        self.manual_tools_toggle = QPushButton("顯示手動校準 ▾")
        self.manual_tools_toggle.setCheckable(True)
        show_by_default = platform == "TradingView"
        self.manual_tools_toggle.setChecked(show_by_default)
        def set_manual_visible(show: bool) -> None:
            capture.setVisible(show)
            show_position.setVisible(show)
            self.manual_tools_toggle.setText(
                "收起手動校準 ▴" if show else "顯示手動校準 ▾"
            )
        self.manual_tools_toggle.toggled.connect(set_manual_visible)
        buttons.addWidget(self.manual_tools_toggle)
        buttons.addWidget(capture)
        buttons.addWidget(show_position)
        buttons.addStretch()
        buttons.addWidget(close)
        set_manual_visible(show_by_default)
        layout.addLayout(buttons)
        self.capture_finished.connect(self._finish_capture)
        self.inspection_finished.connect(self._finish_inspection)
        self._inspection_running = False
        self._hover_running = False
        self._inventory_running = False
        self._candidate_preview_running = False
        self._inventory_overlays: list[CandidateOutline] = []
        self._inventory_scan_context: dict[str, Any] | None = None
        self._inventory_save_preview: dict[str, Any] | None = None
        self._hover_outline = CandidateOutline()
        self.hover_finished.connect(self._finish_hover)
        self.inventory_finished.connect(self._finish_inventory)

    def _refresh_stage_progress(self) -> None:
        # Also support lightweight, read-only calibration previews whose
        # parent has not yet loaded a full ConfigStore (including unit tests).
        store=getattr(self.app, "store", None)
        data=getattr(store, "data", {}) or {}
        platforms=data.get("platforms", {}) if isinstance(data,dict) else {}
        points=platforms.get(self.platform, {}).get("points", {})
        ui=data.get("ui", {}) if isinstance(data,dict) else {}
        show_dots=bool(ui.get("show_calibration_badges", True))
        for idx, keys in enumerate(self._stage_keys):
            done,total=completion(points,keys)
            self._calibration_tabs.setTabText(
                idx, f"{self._stage_titles[idx]} ({done}/{total})"
            )
            self._stage_dots[idx].setVisible(
                show_dots and done < total
            )
        if hasattr(self.app, "_refresh_calibration_badges"):
            self.app._refresh_calibration_badges()

    def _select_stage_radio(self, index: int) -> None:
        """A field selected in another tab must not be captured by mistake."""
        if index < 0 or index >= len(self._stage_keys):
            return
        keys = self._stage_keys[index]
        if keys and not any(self.radios[key].isChecked() for key in keys):
            self.radios[keys[0]].setChecked(True)
        self.result.setText("")

    def open_post_entry_wizard(self) -> None:
        """Open a separate read-only stage-two calibration session."""
        if self.platform != "cTrader":
            return
        PostEntryCalibrationDialog(self).exec()

    def scan_all_calibration(self) -> None:
        """User-initiated, read-only inventory of existing calibration targets."""
        if self._inventory_running or self._inspection_running or self._hover_running:
            return
        if self.platform not in {"cTrader", "MT5", "BYBIT MT5", "原版MT5"}:
            QMessageBox.information(self, "完整校準掃描", "目前只支援 cTrader 與 MT5 系列。")
            return
        profile = self.app.store.data["platforms"][self.platform]
        pattern = profile.get("window_title", {}).get(self._display_role("lot_input"), "")
        try:
            if not str(pattern or "").strip():
                raise ValueError("尚未綁定此交易平台視窗，請先設定視窗標題")
            matched = self.app.windows.find(pattern)
            # The configured title regex (e.g. "cTrader") may also match
            # "Modify order or position - cTrader". Scan must bind to the
            # unique *main terminal* first, then select modal by same PID.
            target = select_broker_main_window(
                matched,self.app.windows.list_windows(),self.platform,
                process_id_for_window, binding_pattern=pattern,
            )
            if target is None:
                raise ValueError(
                    "找不到唯一的平台主視窗；不要把修改視窗當成 Positions 列表"
                )
            handle = int(target.handle)
            if not process_id_for_window(handle):
                raise ValueError("無法確認交易平台主視窗")
        except Exception as exc:
            QMessageBox.warning(self, "完整校準掃描", f"找不到已綁定的平台視窗：{exc}")
            return
        stage = set(self._stage_keys[self._calibration_tabs.currentIndex()])
        is_position_grid = stage == set(POSITION_GRID_KEYS)
        is_position_modify = stage == set(POSITION_EDIT_KEYS)
        if is_position_modify:
            other=select_modify_dialog(
                target, self.app.windows.list_windows(), self.platform,
                process_id_for_window,
            )
            if other is None:
                QMessageBox.warning(
                    self, "尚未辨識已開啟的持倉修改視窗",
                    "請先在平台持倉列表自行雙擊目標的 "
                    + ("TP" if self.platform=="cTrader" else "SL")
                    + " 欄，確認修改視窗已開啟後，再重新掃描。"
                    "不會用主畫面或新訂單視窗冒充修改視窗。"
                )
                return
            target=other
            handle=int(other.handle)
        if self.platform in {"MT5", "BYBIT MT5", "原版MT5"} and "lot_input" in stage:
            # The already-open ORDER DIALOG must belong to the same MT5
            # process. Don't scan the main chart window for order inputs.
            parent_pid = process_id_for_window(target.handle)
            order_dialogs = [
                win for win in self.app.windows.list_windows()
                if win.handle != target.handle
                and process_id_for_window(win.handle) == parent_pid
                and re.search(r"\border\b|新訂單|訂單|订单|下單",
                              win.title, re.I)
            ]
            if len(order_dialogs) != 1:
                QMessageBox.warning(
                    self, "MT5 新訂單視窗尚未找到",
                    "請先在 MT5 主視窗點「新訂單」，保持下單視窗開啟，"
                    "再回到第二階段掃描。\n"
                    "若已開啟但仍找不到，請改用「顯示手動校準」或告訴我該視窗的標題。"
                )
                return
            target = order_dialogs[0]
            handle = int(target.handle)
        self._inventory_running = True
        self._inventory_scan_context = {
            "platform": self.platform,
            "window": target,
            "pid": process_id_for_window(target.handle),
            "role": self._display_role("lot_input"),
        }
        self.result.setText("正在唯讀掃描校準項目；候選不會自行儲存或操作交易視窗……")
        # Only inspect the tab the user opened; MT5 post-entry controls may
        # require its manual modification window. No invented detection.
        targets = tuple(
            (key, label) for key, label in CALIBRATION_TARGETS[self.platform]
            if key in stage
        )

        def task() -> None:
            try:
                if is_position_grid:
                    report=scan_position_grid(handle,self.platform,targets)
                elif is_position_modify:
                    report=scan_open_modify_dialog(handle,self.platform,targets)
                else:
                    report=inspect_all_targets(handle,self.platform,targets)
            except Exception as exc:
                report = ScanReport(self.platform, targets, warnings=(f"掃描失敗：{exc}",))
            self.inventory_finished.emit(report)

        threading.Thread(target=task, daemon=True).start()

    def _finish_inventory(self, report: ScanReport) -> None:
        self._inventory_running = False
        self.result.setText(
            f"掃描完成：{len(report.candidates)}/{len(report.targets)} 個單一候選，均未套用或儲存"
        )
        details = QDialog(self)
        details.setWindowTitle(f"{self.platform}｜校準結果：預覽後人工確認儲存")
        details.resize(760, 580)
        panel = QVBoxLayout(details)
        heading = QLabel("先預覽黃色框，再勾選正確項目並儲存。")
        panel.addWidget(heading)
        output = QPlainTextEdit(details)
        output.setReadOnly(True)
        output.setPlainText(report.as_text())
        panel.addWidget(output)
        details.resize(780, 700)
        # Explicitly checked suggestions are the ONLY values eligible for saving.
        # Everything begins unchecked and cannot be selected until a successful
        # full yellow-outline preview of this same report has finished.
        status = QLabel(
            "預覽 → 勾選 → 儲存。未勾選項目保持原樣。"
        )
        panel.addWidget(status)
        checkboxes: dict[str, QCheckBox] = {}
        if report.candidates:
            preview_all_button = QPushButton("① 一次預覽全部黃色框（1.5 秒）", details)
            preview_all_button.setToolTip("僅顯示外框，不點擊、不儲存交易平台任何資料")
            preview_all_button.clicked.connect(
                lambda: self.preview_all_inventory_candidates(details, report)
            )
            panel.addWidget(preview_all_button)
            panel.addWidget(QLabel("② 勾選正確位置"))
            checklist_area = QScrollArea(details)
            checklist_area.setWidgetResizable(True)
            checklist_area.setMaximumHeight(210)
            checklist = QWidget(checklist_area)
            checklist_layout = QVBoxLayout(checklist)
            for key,label in report.targets:
                candidate = report.candidates.get(key)
                if candidate is None:
                    continue
                low = "低信度／請特別核對" if "低信度" in candidate.evidence else "候選／尚待確認"
                cb = QCheckBox(f"{label}（{low}）", checklist)
                cb.setObjectName("confirm_" + key)
                cb.setChecked(False)
                cb.setEnabled(False)
                cb.setToolTip(candidate.evidence)
                checkboxes[key] = cb
                checklist_layout.addWidget(cb)
            checklist_area.setWidget(checklist)
            panel.addWidget(checklist_area)
            bulk_row = QHBoxLayout()
            select_all_button = QPushButton("全選", details)
            select_all_button.setToolTip("包含低信度候選，請先看過黃框")
            clear_button = QPushButton("清除勾選", details)
            select_all_button.setEnabled(False)
            clear_button.setEnabled(False)
            select_all_button.clicked.connect(
                lambda: [cb.setChecked(True) for cb in checkboxes.values()]
            )
            clear_button.clicked.connect(
                lambda: [cb.setChecked(False) for cb in checkboxes.values()]
            )
            bulk_row.addWidget(select_all_button)
            bulk_row.addWidget(clear_button)
            panel.addLayout(bulk_row)
        else:
            select_all_button = None
            clear_button = None
            panel.addWidget(QLabel(
                "目前沒有可預覽或儲存的候選。請顯示目標欄位後重新掃描。"
            ))
        commands = QHBoxLayout()
        save_button = QPushButton("③ 儲存我已勾選的項目", details)
        save_button.setEnabled(False)
        commands.addWidget(save_button)
        close_button = QPushButton("關閉結果（不儲存）", details)
        close_button.clicked.connect(details.accept)
        commands.addWidget(close_button)
        panel.addLayout(commands)
        state = {
            "dialog":details, "report":report, "checkboxes":checkboxes,
            "save_button":save_button, "status":status,
            "select_all_button":select_all_button, "clear_button":clear_button,
            "context":dict(self._inventory_scan_context)
                if self._inventory_scan_context is not None else None,
            "previewed":False, "saved":False,
        }
        self._inventory_save_preview = state
        for checkbox in checkboxes.values():
            checkbox.toggled.connect(
                lambda _checked, s=state: self._update_inventory_save_button(s)
            )
        save_button.clicked.connect(lambda: self._save_inventory_selection(state))
        try:
            details.exec()
        finally:
            if self._inventory_save_preview is state:
                self._inventory_save_preview = None
            self._inventory_scan_context = None
            if state["saved"]:
                # Only after the settings transaction succeeded do we close
                # the parent calibration dialog as requested.
                self.accept()

    def _update_inventory_save_button(self, state: dict[str, Any]) -> None:
        enabled = (
            self._inventory_save_preview is state
            and state["previewed"]
            and not state["saved"]
            and state["context"] is not None
            and not state["report"].warnings
            and any(cb.isChecked() and cb.isEnabled() for cb in state["checkboxes"].values())
        )
        state["save_button"].setEnabled(enabled)

    def _save_inventory_selection(self, state: dict[str, Any]) -> None:
        """Double opt-in: successful preview, individual ticks, then Yes."""
        details = state["dialog"]
        if (
            self._inventory_save_preview is not state
            or not state["previewed"] or state["saved"]
            or state["context"] is None or state["report"].warnings
            or self._candidate_preview_running
        ):
            QMessageBox.warning(details, "無法儲存", "請先完成這次候選的黃色框預覽。")
            return
        selected = tuple(
            key for key, cb in state["checkboxes"].items()
            if cb.isChecked() and cb.isEnabled()
        )
        if not selected:
            return
        confirmation = QMessageBox.question(
            details, "確認儲存校準",
            f"要儲存你勾選的 {len(selected)} 個位置嗎？\n"
            "只更新已勾選項目；其他原有校準維持不變。\n"
            "這不會對交易平台點擊或送出任何訂單。",
            QMessageBox.Yes | QMessageBox.No, QMessageBox.No,
        )
        if confirmation != QMessageBox.Yes:
            return
        state["save_button"].setEnabled(False)
        state["status"].setText("正在重新確認視窗及候選位置；尚未寫入設定……")
        try:
            ctx = state["context"]
            original = ctx["window"]
            if ctx["platform"] != self.platform:
                raise CalibrationConfirmationError("平台已切換，請重新掃描")
            # Use the SAME stage-specific scanner that produced the preview.
            # The generic scanner never emits post-entry position candidates,
            # so using it here falsely rejects every valid MT5/cTrader save.
            # Re-read every field of the stage (not only selected fields)
            # to reject stale, moved, duplicate or differently identified UI.
            stage = {key for key,_ in state["report"].targets}
            if stage == set(POSITION_GRID_KEYS):
                fresh = scan_position_grid(
                    original.handle, self.platform, state["report"].targets
                )
            elif stage == set(POSITION_EDIT_KEYS):
                fresh = scan_open_modify_dialog(
                    original.handle, self.platform, state["report"].targets
                )
            else:
                fresh = inspect_all_targets(
                    original.handle, self.platform, state["report"].targets
                )
            if fresh.warnings:
                raise CalibrationConfirmationError(
                    "儲存前重新掃描有警示；請先確認平台與欄位沒有改動："
                    + "；".join(fresh.warnings)
                )
            for key in selected:
                prior = state["report"].candidates.get(key)
                latest = fresh.candidates.get(key)
                if latest is None or prior is None or latest.rect != prior.rect:
                    raise CalibrationConfirmationError(
                        f"{key} 的欄位已移動或辨識變更，請重新掃描並預覽"
                    )
            points = candidate_calibration_points(
                fresh, selected, self.app.windows.list_windows(),
                original, ctx["pid"], process_id_for_window,
            )
            save_confirmed_points(self.app, self.platform, points)
            self._refresh_stage_progress()
            state["saved"] = True
            for cb in state["checkboxes"].values():
                cb.setEnabled(False)
            for button_name in ("select_all_button", "clear_button"):
                if state[button_name] is not None:
                    state[button_name].setEnabled(False)
            state["status"].setText(
                f"已儲存 {len(points)} 個你勾選的項目，其他位置保持原樣。"
            )
            self.result.setText(f"已儲存 {len(points)} 個人工確認的校準位置")
            self.app.log(
                f"已人工確認並儲存 {self.platform} {len(points)} 個校準項目："
                + ", ".join(points)
            )
            # Finish the nested preview modal immediately after a SUCCESSFUL
            # atomic save; the outer dialog closes when exec() returns.
            details.accept()
        except Exception as exc:
            state["status"].setText("未儲存；請檢查錯誤後重新掃描。")
            QMessageBox.warning(details, "校準未儲存", str(exc))
        finally:
            self._update_inventory_save_button(state)

    def preview_inventory_candidate(
        self, details: QDialog, report: ScanReport, key: str | None
    ) -> None:
        """Highlight one already-scanned candidate; no broker input or saving."""
        if (self._candidate_preview_running or self._hover_running
                or self._inspection_running or self._inventory_running):
            return
        candidate = report.candidates.get(key or "")
        if candidate is None:
            return
        self._candidate_preview_running = True
        self._candidate_preview_error = ""
        # Minimize, never hide, while modal QDialog.exec() remains alive.
        details.showMinimized()
        self.showMinimized()
        self.app.showMinimized()
        QTimer.singleShot(
            150, lambda: self._show_inventory_outline(candidate.rect)
        )
        QTimer.singleShot(1850, lambda: self._restore_inventory_preview(details))

    def _show_inventory_outline(self, rect: tuple[int, int, int, int]) -> None:
        try:
            self._hover_outline.display(rect, 1500)
        except Exception as exc:
            self._candidate_preview_error = str(exc)

    def preview_all_inventory_candidates(
        self, details: QDialog, report: ScanReport
    ) -> None:
        """Show every unverified candidate together for 1.5 seconds, read-only."""
        if (self._candidate_preview_running or self._hover_running
                or self._inventory_running or self._inspection_running):
            return
        rectangles = tuple(candidate.rect for candidate in report.candidates.values())
        if not rectangles:
            return
        self._candidate_preview_running = True
        self._candidate_preview_error = ""
        details.showMinimized()
        self.showMinimized()
        self.app.showMinimized()
        QTimer.singleShot(
            150, lambda: self._show_all_inventory_outlines(rectangles)
        )
        QTimer.singleShot(1850, lambda: self._restore_inventory_preview(details))

    def _show_all_inventory_outlines(
        self, rectangles: tuple[tuple[int, int, int, int], ...]
    ) -> None:
        try:
            for rect in rectangles:
                overlay = CandidateOutline()
                self._inventory_overlays.append(overlay)
                overlay.display(rect, 1500)
        except Exception as exc:
            self._candidate_preview_error = str(exc)
            for overlay in self._inventory_overlays:
                overlay.hide()
                overlay.close()
            self._inventory_overlays.clear()

    def _restore_inventory_preview(self, details: QDialog) -> None:
        self._hover_outline.hide()
        for overlay in self._inventory_overlays:
            overlay.hide()
            overlay.close()
        self._inventory_overlays.clear()
        self._candidate_preview_running = False
        self.app.showNormal()
        self.showNormal()
        details.showNormal()
        details.raise_()
        details.activateWindow()
        state = self._inventory_save_preview
        if state is not None and state["dialog"] is details and not state["saved"]:
            if (not self._candidate_preview_error and state["context"] is not None and not state["report"].warnings):
                state["previewed"] = True
                for cb in state["checkboxes"].values():
                    cb.setEnabled(True)
                for button_name in ("select_all_button", "clear_button"):
                    if state[button_name] is not None:
                        state[button_name].setEnabled(True)
                state["status"].setText(
                    "黃色框預覽完成。請只勾選你親眼確認正確的項目；"
                    "尤其要核對 SL／TP 點數與真正送單按鈕。"
                )
            else:
                state["previewed"] = False
                state["status"].setText(
                    "預覽尚未成功完成，請重新預覽；尚無法儲存。"
                )
            self._update_inventory_save_button(state)
        if self._candidate_preview_error:
            QMessageBox.warning(details, "框線預覽失敗", self._candidate_preview_error)
        self._candidate_preview_error = ""

    def inspect_hover(self) -> None:
        """Inspect the actual hovered element without editing, clicking or saving."""
        if self._hover_running or self._inspection_running or self._inventory_running:
            return
        profile = self.app.store.data["platforms"][self.platform]
        role = self._display_role("lot_input")
        pattern = profile.get("window_title", {}).get(role, "")
        try:
            target = self.app.windows.find(pattern)
            target_pid = process_id_for_window(target.handle)
            if not target_pid:
                raise ValueError("無法確認目標視窗所屬程序")
        except Exception as exc:
            QMessageBox.warning(self, "游標檢查", f"找不到已綁定的平台視窗：{exc}")
            return
        self._hover_running = True
        self.result.setText("倒數 4 秒；請把滑鼠移到交易平台的目標欄位內並停住。")
        # hide() makes modal QDialog.exec() return immediately and destroys its callbacks.
        self.showMinimized()
        self.app.showMinimized()
        QTimer.singleShot(4000, lambda: self._sample_hover(target_pid))

    def _sample_hover(self, target_pid: int) -> None:
        def task() -> None:
            try:
                self.hover_finished.emit(hover_snapshot(target_pid))
            except Exception as exc:
                self.hover_finished.emit(f"UIA 游標檢查失敗：{exc}")
        threading.Thread(target=task, daemon=True).start()

    def _finish_hover(self, snapshot: object) -> None:
        if isinstance(snapshot, str):
            self._hover_summary = snapshot
        else:
            details = [
                f"位置：{snapshot.position}",
                f"控制項類型：{snapshot.control_type or '未知'}",
                f"名稱：{snapshot.name or '（空白）'}",
                f"AutomationId：{snapshot.automation_id or '（空白）'}",
                f"ClassName：{snapshot.class_name or '（空白）'}",
                f"上層類型：{' > '.join(snapshot.ancestor_types) or '（無）'}",
                snapshot.note,
            ]
            self._hover_summary = '\n'.join(details)
            if snapshot.is_candidate:
                try:
                    self._hover_outline.display(snapshot.rectangle, 5500)
                except Exception as exc:
                    self._hover_summary += f"\n外框無法顯示：{exc}"
        QTimer.singleShot(5700 if not isinstance(snapshot, str) and snapshot.is_candidate else 100,
                          self._restore_hover_ui)

    def _restore_hover_ui(self) -> None:
        self._hover_outline.hide()
        self._hover_running = False
        self.app.showNormal()
        self.showNormal()
        self.raise_()
        self.activateWindow()
        self.result.setText("已完成游標檢查，候選位置仍未確認，也未儲存座標。")
        QMessageBox.information(self, "UIA 游標檢查（唯讀）", self._hover_summary)

    def inspect_fields(self) -> None:
        """Only discover candidate UIA fields; never interact with the platform."""
        if self._inspection_running or self._inventory_running:
            return
        role = self._display_role("lot_input")
        profile = self.app.store.data["platforms"][self.platform]
        pattern = profile.get("window_title", {}).get(role, "")
        try:
            target = self.app.windows.find(pattern)
        except Exception as exc:
            QMessageBox.warning(self, "UIA 欄位檢測", f"找不到目標視窗：{exc}")
            return

        self._inspection_running = True
        self.result.setText("正在唯讀掃描 UIA 欄位……")

        def task() -> None:
            try:
                matched, warnings, scanned = inspect_uia_window(target.handle)
                result = {"matched": matched, "warnings": warnings, "scanned": scanned}
            except Exception as exc:
                result = {"matched": {}, "warnings": (f"掃描失敗：{exc}",), "scanned": 0}
            self.inspection_finished.emit(result)

        threading.Thread(target=task, daemon=True).start()

    def _finish_inspection(self, report: dict[str, Any]) -> None:
        self._inspection_running = False
        labels = {"lot_input": "手數", "sl_input": "止損", "tp_input": "止盈"}
        matched = report["matched"]
        lines = [
            "唯讀辨識結果（尚未儲存或套用校準）：",
            f"已檢查控制項：{report['scanned']}",
        ]
        for key, label in labels.items():
            suggestion = matched.get(key)
            if suggestion is None:
                lines.append(f"{label}：未確認")
            else:
                left, top, right, bottom = suggestion.rect
                lines.append(f"{label}：候選位置 ({(left+right)//2}, {(top+bottom)//2})，{suggestion.source}")
        lines.extend(report["warnings"])
        all_found = len(matched) == len(labels) and not report["warnings"]
        self.result.setText("三個輸入欄均找到候選位置" if all_found else "仍需檢查或使用備援校準")
        QMessageBox.information(self, "UIA 欄位檢測（不執行下單）", "\n".join(lines))

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
                point["calibration_window_title"] = re.escape(active.title)
                profile = self.app.store.data["platforms"][self.platform]
                if self.platform == "TradingView":
                    stable_title = r"/\s*常用$"
                    point["window_title"] = stable_title
                    profile["window_title"]["internal"] = stable_title
                    profile["window_title"]["external"] = stable_title
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
        self.app.showMinimized()
        key = next(key for key, radio in self.radios.items() if radio.isChecked())
        profile = self.app.store.data["platforms"][self.platform]
        point = profile.get("points", {}).get(key)
        if not point:
            QMessageBox.warning(self, "顯示位置", "這個項目尚未校準。")
            return
        try:
            role = self._display_role(key)
            target_window = self.app.automation._window_for_point(
                profile, role, point
            )
            x, y = self.app.windows.screen_point_for_display(
                target_window, point
            )
        except Exception as exc:
            QMessageBox.critical(self, "顯示位置", str(exc))
            return
        self.app.windows.show_marker(x, y, duration_ms=5000)
        self.result.setText(f"正在顯示：{key}")

    def _display_role(self, key: str) -> str:
        if key.startswith("position_") or key == "positions_entry_price":
            # Both platforms can be configured on either side. The native
            # post-entry column belongs to the currently selected platform,
            # not always to 'external' or always to 'internal'.
            return ("internal"
                if self.app.internal_platform.currentText()==self.platform
                else "external")
        if self.app.internal_platform.currentText() == self.platform:
            return "internal"
        return "external"

    def _finish_capture(self, key: str) -> None:
        self._refresh_stage_progress()
        self.result.setText(f"已儲存：{key}" if key else "擷取失敗。")
        self.showNormal()
        self.raise_()
        self.activateWindow()


class PostEntryCalibrationDialog(QDialog):
    """Stage two: user-armed observation of an existing cTrader position only."""

    scan_finished = Signal(object)

    def __init__(self, parent: CalibrationDialog):
        super().__init__(parent)
        self.owner = parent
        self.app = parent.app
        self.setWindowTitle("② cTrader 進場後校準（唯讀）")
        self.resize(760, 540)
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self._scanning = False
        self._watching = False
        self.last_report: PostEntryReport | None = None
        body = QVBoxLayout(self)
        body.addWidget(QLabel(
            "① 在 cTrader 打開 Positions（持倉）分頁；"
            "使用模擬帳戶或已經存在的持倉。\n"
            "② 按「開始辨識持倉欄位」即可，程式會定期檢查。\n"
            "0 筆會繼續等待；1 筆會停止並顯示候選；"
            "多筆會停止請你確認。\n"
            "此功能不會下單、雙擊持倉、修改止損或儲存位置。"
        ))
        self.status_label = QLabel("尚未開始。若目前沒有持倉，可以先關閉此視窗。")
        body.addWidget(self.status_label)
        self.results = QPlainTextEdit(self)
        self.results.setReadOnly(True)
        self.results.setPlainText(
            "目前尚未開始。\n"
            "先在 cTrader 顯示 Positions（持倉）分頁，"
            "再按「開始辨識持倉欄位」。\n"
            "沒有持倉時可以先離開，不需要為了校準開真倉。"
        )
        body.addWidget(self.results)
        self.watch_timer = QTimer(self)
        self.watch_timer.setInterval(3500)
        self.watch_timer.timeout.connect(self.scan_once)
        self.preview_note = QLabel(
            "黃色框預覽會在辨識到唯一持倉及候選欄位後出現。"
        )
        body.addWidget(self.preview_note)
        commands = QHBoxLayout()
        self.watch_button = QPushButton("開始辨識持倉欄位（唯讀）")
        self.watch_button.clicked.connect(self.toggle_watch)
        commands.addWidget(self.watch_button)
        self.preview_button = QPushButton("預覽找到的位置（1.5 秒）")
        self.preview_button.hide()
        self.preview_button.clicked.connect(self.preview_candidates)
        commands.addWidget(self.preview_button)
        end = QPushButton("關閉")
        end.clicked.connect(self.accept)
        commands.addWidget(end)
        body.addLayout(commands)
        self.scan_finished.connect(self._finish_scan)
        self.finished.connect(self._finish_session)

    def _finish_session(self, _result: int) -> None:
        self.watch_timer.stop()
        self._watching = False

    def preview_candidates(self) -> None:
        """Highlight stage-two suggestions in one go, never submit or save."""
        if (self.last_report and self.last_report.state == "single"
                and self.last_report.candidates):
            self.owner.preview_all_inventory_candidates(self, self.last_report)

    def toggle_watch(self) -> None:
        if self._watching:
            self._stop_watching("已停止辨識；未更改任何持倉")
            return
        self._watching = True
        self.watch_button.setText("停止辨識")
        self.watch_timer.start()
        self.scan_once()

    def _stop_watching(self, message: str) -> None:
        self._watching = False
        self.watch_timer.stop()
        self.watch_button.setText("開始辨識持倉欄位（唯讀）")
        self.status_label.setText(message)

    def scan_once(self) -> None:
        if self._scanning:
            return
        profile = self.app.store.data["platforms"]["cTrader"]
        role = self.owner._display_role("lot_input")
        pattern = str(profile.get("window_title", {}).get(role, "")).strip()
        try:
            if not pattern:
                raise ValueError("尚未設定 cTrader 視窗標題")
            target = self.app.windows.find(pattern)
            hwnd = int(target.handle)
            if not process_id_for_window(hwnd):
                raise ValueError("無法確認 cTrader 視窗程序")
        except Exception as exc:
            self._stop_watching("無法確認持倉視窗")
            QMessageBox.warning(self, "進場後校準", str(exc))
            return
        self._scanning = True
        self.status_label.setText("正在唯讀檢查 Positions 表格……")

        def worker() -> None:
            try:
                report = inspect_post_entry(hwnd)
            except Exception as exc:
                report = PostEntryReport(
                    notes=(f"檢查失敗：{exc}",)
                )
            self.scan_finished.emit(report)

        threading.Thread(target=worker, daemon=True).start()

    def _finish_scan(self, report: PostEntryReport) -> None:
        self._scanning = False
        self.last_report = report
        if report.state == "empty":
            self.results.setPlainText(
                "目前 0 筆持倉。程式會繼續等待；"
                "你不用重複按掃描，也不需要為了校準建立真實訂單。"
            )
        elif report.state == "multiple":
            self.results.setPlainText(
                "偵測到多筆持倉。已停止自動選取，"
                "避免誤認另一筆交易；請先自行確認目標。"
            )
        elif report.state == "unknown":
            self.results.setPlainText(
                "暫時看不到可靠的持倉列表。"
                "請先把 cTrader 的 Positions 分頁打開，再按開始辨識。"
            )
        else:
            self.results.setPlainText(report.as_text())
        can_preview = report.state == "single" and bool(report.candidates)
        self.preview_button.setVisible(can_preview)
        self.preview_note.setText(
            "已找到候選！按「預覽找到的位置」即可同時查看。"
            if can_preview else
            "尚無可預覽的欄位；0 筆時會等待，修改 SL／TP 需先自行開啟修改視窗。"
        )
        if report.state == "empty":
            self.status_label.setText(
                "目前沒有持倉；" + ("正在自動等待第一筆持倉" if self._watching else "可稍後再開始辨識")
            )
        elif report.state == "single":
            self._stop_watching(
                "找到唯一持倉，已停止等待；可核對候選欄位，不會開啟修改視窗"
            )
        elif report.state == "multiple":
            self._stop_watching("發現多筆持倉：停止自動辨識，請指定目標")
        else:
            self._stop_watching("無法確定持倉數量：已安全停止")

    def closeEvent(self, event: QCloseEvent) -> None:
        self._finish_session(0)
        event.accept()


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
        self.ctrader_mode_combo = QComboBox()
        tabs.addTab(self._sheet_tab(), "Google 試算表")
        tabs.addTab(self._columns_tab(), "欄位對應")
        tabs.addTab(self._windows_tab(), "視窗標題")
        tabs.addTab(self._ctrader_tab(), "cTrader SL/TP")
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
            if key == "expected_sl_percent":
                continue
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

    def _ctrader_tab(self) -> QWidget:
        tab = QWidget()
        form = QFormLayout(tab)
        self.ctrader_mode_combo.addItem(
            "cTrader 原本輸入方式（每個新方案預設）", "native"
        )
        self.ctrader_mode_combo.addItem(
            "與 Gooey 相同：依 point_size 換算點數", "gooey"
        )
        selected = ctrader_mode_for_profile(
            self.draft, self.app.profiles.active_name
        )
        index = self.ctrader_mode_combo.findData(selected)
        self.ctrader_mode_combo.setCurrentIndex(max(0,index))
        form.addRow("止盈／止損點數輸入", self.ctrader_mode_combo)
        help_label = QLabel(
            "只有此方案及目前試算表網址會使用此設定。\n"
            "更改方案名稱或試算表網址後，視為新方案並恢復原本方式。\n"
            "原本方式若連續兩次輸入小數只留下整數，程式會停止並詢問"
            "是否切換；不會自行更換，也不會自動下單。"
        )
        help_label.setWordWrap(True)
        form.addRow(help_label)
        return tab

    def save(self) -> None:
        try:
            old_url = str(
                self.app.store.data["sheet"].get("spreadsheet_url", "")
            ).strip()
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
            new_url = str(
                self.draft["sheet"].get("spreadsheet_url", "")
            ).strip()
            mode = (
                "native" if new_url != old_url
                else str(self.ctrader_mode_combo.currentData())
            )
            set_ctrader_mode_for_profile(
                self.draft, self.app.profiles.active_name, mode
            )
            self.app.store.data = self.draft
            self.app.save_config()
            self.accept()
        except Exception as exc:
            QMessageBox.critical(self, "設定", str(exc))


