"""Self-contained trading-terminal visual theme for the TEST helper.

Only paint/style Qt widgets. No service connections, order logic, or trading IO.
Icons are simple vector paths rendered at runtime; no font or external assets.
"""
from __future__ import annotations

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer


ICON_PATHS: dict[str, str] = {
    "settings": '<path d="M12 2v3m0 14v3M4.9 4.9l2.1 2.1m10 10 2.1 2.1M2 12h3m14 0h3M4.9 19.1 7 17m10-10 2.1-2.1"/><circle cx="12" cy="12" r="4"/>',
    "help": '<circle cx="12" cy="12" r="10"/><path d="M9.2 9a3 3 0 0 1 5.7 1.2c0 2-2.9 2.5-2.9 4.2"/><path d="M12 18h.01"/>',
    "link": '<path d="M10 13.5a5 5 0 0 0 7.1 0l2.1-2.1a5 5 0 0 0-7.1-7.1L10.9 5.5"/><path d="M14 10.5a5 5 0 0 0-7.1 0l-2.1 2.1a5 5 0 0 0 7.1 7.1l1.2-1.2"/>',
    "database": '<ellipse cx="12" cy="5" rx="9" ry="3"/><path d="M3 5v7c0 1.7 4 3 9 3s9-1.3 9-3V5M3 12v7c0 1.7 4 3 9 3s9-1.3 9-3v-7"/>',
    "refresh": '<path d="M20 11a8 8 0 0 0-14-5L3 9m0-6v6h6M4 13a8 8 0 0 0 14 5l3-3m0 6v-6h-6"/>',
    "tune": '<path d="M4 7h16M4 17h16"/><circle cx="9" cy="7" r="3" fill="#111b2c"/><circle cx="16" cy="17" r="3" fill="#111b2c"/>',
    "crosshair": '<circle cx="12" cy="12" r="7"/><circle cx="12" cy="12" r="2"/><path d="M12 2v3m0 14v3M2 12h3m14 0h3"/>',
    "monitor": '<rect x="3" y="4" width="18" height="13" rx="2"/><path d="M8 21h8m-4-4v4"/>',
    "sliders": '<path d="M4 6h10m4 0h2M4 12h3m4 0h9M4 18h11m4 0h1"/><circle cx="16" cy="6" r="2"/><circle cx="9" cy="12" r="2"/><circle cx="17" cy="18" r="2"/>',
    "arrow-left-right": '<path d="M8 3 3 8l5 5M3 8h18M16 21l5-5-5-5M21 16H3"/>',
    "arrow-up-right": '<path d="M7 17 17 7M8 7h9v9"/>',
    "chart": '<path d="M3 3v18h18M7 16l5-6 4 3 5-7"/>',
    "history": '<path d="M3 12a9 9 0 1 0 2-5M3 4v5h5M12 7v5l3 2"/>',
    "eye": '<path d="M2 12s3.6-7 10-7 10 7 10 7-3.6 7-10 7S2 12 2 12Z"/><circle cx="12" cy="12" r="3"/>',
    "book": '<path d="M4 4h7a3 3 0 0 1 3 3v14a3 3 0 0 0-3-3H4zM20 4h-3a3 3 0 0 0-3 3v14a3 3 0 0 1 3-3h3z"/>',
    "folder": '<path d="M3 7a2 2 0 0 1 2-2h5l2 2h7a2 2 0 0 1 2 2v10H3Z"/>',
    "plus": '<path d="M12 5v14M5 12h14"/>',
    "save": '<path d="M4 3h14l3 3v15H3V3h1Zm4 0v6h9V3M7 21v-9h10v9"/>',
    "edit": '<path d="m4 20 5-.9L20 8a2 2 0 0 0-4-4L5 15zM14 6l4 4"/>',
    "trash": '<path d="M4 7h16M9 7V4h6v3m3 0-1 14H7L6 7M10 11v6m4-6v6"/>',
    "check": '<path d="m4 12 5 5L20 6"/>',
    "lock": '<rect x="5" y="11" width="14" height="10" rx="2"/><path d="M8 11V8a4 4 0 0 1 8 0v3"/>',
}


def themed_icon(name: str, color: str = "#bcb5c0", size: int = 18) -> QIcon:
    paths = ICON_PATHS.get(name, ICON_PATHS["settings"])
    markup = (
        '<svg xmlns="http://www.w3.org/2000/svg" width="24" height="24" '
        'viewBox="0 0 24 24" fill="none" stroke="' + color +
        '" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round">' +
        paths + "</svg>"
    )
    renderer = QSvgRenderer(QByteArray(markup.encode("utf-8")))
    canvas = QPixmap(size * 2, size * 2)
    canvas.fill(Qt.transparent)
    painter = QPainter(canvas)
    renderer.render(painter)
    painter.end()
    canvas.setDevicePixelRatio(2.0)
    return QIcon(canvas)


MAIN_THEME = """
QMainWindow#tradingHelperMain {
    background-color: #0b111b;
    color: #e3edfa;
    font-family: "Segoe UI", "Microsoft JhengHei UI", sans-serif;
    font-size: 12px;
}
QWidget#appSurface {
    background: #0b111b;
}
QFrame#headerCard {
    background: #141f2e;
    border: 1px solid #26374b;
    border-radius: 13px;
}
QFrame#headerCard QLabel {
    background: transparent;
}
QLabel#appTitle {
    color: #f1f6fd;
    font-size: 20px;
    font-weight: 700;
}
QLabel#versionPill {
    background: #193b45;
    border: 1px solid #226977;
    border-radius: 8px;
    color: #7fe6db;
    font-weight: 600;
    padding: 3px 9px;
    font-size: 10px;
}
QLabel#moduleKicker {
    color: #8ea3be;
    font-size: 10px;
    font-weight: 600;
}
QFrame#autoEntryPanel {
    background: #1d2635;
    border: 1px solid #344457;
    border-radius: 8px;
}
QLabel#entryStatus {
    color: #dba964;
    font-size: 11px;
}
QGroupBox#platformCard, QGroupBox#dataCard, QGroupBox#parameterCard,
QGroupBox#actionsCard, QGroupBox#afterEntryCard, QGroupBox#activityCard {
    background-color: #141e2d;
    border: 1px solid #263548;
    border-radius: 12px;
    margin-top: 15px;
    padding: 11px 10px 8px 10px;
    color: #e3edfa;
    font-weight: 600;
}
QGroupBox#platformCard::title, QGroupBox#dataCard::title,
QGroupBox#parameterCard::title, QGroupBox#actionsCard::title,
QGroupBox#afterEntryCard::title, QGroupBox#activityCard::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 13px;
    padding: 0px 8px;
    color: #d9eafa;
    font-size: 12px;
    font-weight: 700;
}
QGroupBox#actionsCard {
    background-color: #151f2e;
    border-color: #34516c;
}
QMainWindow#tradingHelperMain QLabel {
    color: #becbda;
}
QMainWindow#tradingHelperMain QLabel[role="value"] {
    color: #f2f7ff;
    font-size: 12px;
    font-weight: 700;
}
QMainWindow#tradingHelperMain QLabel[role="caption"] {
    color: #8497b0;
    font-size: 11px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QLineEdit,
QMainWindow#tradingHelperMain QComboBox {
    color: #e7f1ff;
    background-color: #0e1826;
    border: 1px solid #324357;
    border-radius: 7px;
    min-height: 29px;
    padding: 1px 9px;
    selection-background-color: #2e73c8;
}
QMainWindow#tradingHelperMain QLineEdit:hover,
QMainWindow#tradingHelperMain QComboBox:hover {
    border-color: #577a9d;
}
QMainWindow#tradingHelperMain QLineEdit:focus,
QMainWindow#tradingHelperMain QComboBox:focus {
    border: 1px solid #54a9f2;
    background-color: #142236;
}
QMainWindow#tradingHelperMain QComboBox::drop-down {
    width: 22px;
    border: none;
}
QMainWindow#tradingHelperMain QComboBox QAbstractItemView {
    color: #edf5ff;
    background: #172337;
    selection-background-color: #28547b;
    border: 1px solid #3c5572;
    outline: 0;
}
QMainWindow#tradingHelperMain QPushButton,
QMainWindow#tradingHelperMain QToolButton {
    color: #d9e5f3;
    background: #233146;
    border: 1px solid #354860;
    border-radius: 7px;
    min-height: 28px;
    padding: 3px 12px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QPushButton:hover,
QMainWindow#tradingHelperMain QToolButton:hover {
    background: #2d415d;
    border-color: #5d799a;
}
QMainWindow#tradingHelperMain QPushButton:pressed,
QMainWindow#tradingHelperMain QToolButton:pressed {
    background: #152a42;
}
QMainWindow#tradingHelperMain QPushButton:disabled,
QMainWindow#tradingHelperMain QToolButton:disabled {
    color: #687c95;
    background: #182333;
    border-color: #28374a;
}
QMainWindow#tradingHelperMain QPushButton#fillBothPrimary {
    background: #2478d4;
    border: 1px solid #4aacf8;
    color: #ffffff;
    border-radius: 9px;
    font-size: 14px;
    font-weight: 700;
    min-height: 36px;
}
QMainWindow#tradingHelperMain QPushButton#fillBothPrimary:hover {
    background: #308eea;
}
QMainWindow#tradingHelperMain QPushButton#fillBothPrimary:disabled {
    background: #233a52;
    color: #788fa8;
    border-color: #3a4f66;
}
QMainWindow#tradingHelperMain QPushButton[variant="accentOutline"] {
    border-color: #356886;
    color: #b7e1f8;
    background: #20334b;
}
QMainWindow#tradingHelperMain QToolButton#profile_manage_button,
QMainWindow#tradingHelperMain QToolButton#display_settings_button {
    color: #d8e8f8;
    background: #1b2a3e;
    border-color: #3c536d;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QCheckBox {
    color: #e0eaf5;
    spacing: 8px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QCheckBox::indicator {
    width: 16px;
    height: 16px;
}
QMainWindow#tradingHelperMain QPlainTextEdit {
    color: #a6c0db;
    background: #0e1724;
    border: 1px solid #28394b;
    border-radius: 8px;
    padding: 6px 9px;
    selection-background-color: #276ba8;
}
QMainWindow#tradingHelperMain QScrollBar:vertical {
    width: 9px;
    background: #111c29;
}
QMainWindow#tradingHelperMain QScrollBar::handle:vertical {
    background: #344e6a;
    border-radius: 4px;
    min-height: 24px;
}
QMainWindow#tradingHelperMain QScrollBar::add-line:vertical,
QMainWindow#tradingHelperMain QScrollBar::sub-line:vertical {
    height: 0px;
}
QMenu {
    background: #182537;
    color: #e5eef9;
    border: 1px solid #39506a;
    border-radius: 9px;
    padding: 7px;
    font-family: "Segoe UI", "Microsoft JhengHei UI", sans-serif;
}
QMenu::item { padding: 9px 22px 9px 12px; border-radius: 5px; }
QMenu::item:selected { background: #294764; }
QMenu::separator { height: 1px; margin: 5px 8px; background: #375069; }
QToolTip {
    color: #e7f0f9; background: #223249;
    border: 1px solid #46647f; padding: 5px;
}
"""


# Lyricify / DeepCharts-inspired minimal monochrome variant. The existing
# theme above remains as a rollback reference. This layer intentionally strips
# out saturated blues, oversized corner radii and dashboard-like card chrome.
# It changes PAINT ONLY: not widget types, callbacks, config or trading steps.
MAIN_THEME += """
QMainWindow#tradingHelperMain {
    background: #0c0c0e;
    color: #dedbe0;
    font-size: 12px;
}
QWidget#appSurface {
    background: #0c0c0e;
}
QFrame#headerCard {
    background: #101012;
    border: 0;
    border-bottom: 1px solid #333036;
    border-radius: 0;
}
QLabel#appTitle {
    color: #f4f2f5;
    font-weight: 650;
    font-size: 17px;
}
QLabel#versionPill {
    color: #a69cab;
    background: #1a181b;
    border: 1px solid #37323a;
    border-radius: 3px;
    font-size: 10px;
    font-weight: 500;
    padding: 2px 7px;
}
QLabel#moduleKicker, QLabel#entryStatus {
    color: #89828e;
    font-size: 11px;
    font-weight: 400;
}
QFrame#autoEntryPanel {
    background: transparent;
    border: 0;
    border-radius: 0;
}
QGroupBox#platformCard, QGroupBox#dataCard, QGroupBox#parameterCard,
QGroupBox#actionsCard, QGroupBox#afterEntryCard, QGroupBox#activityCard {
    background-color: #111113;
    border: 1px solid #29272d;
    border-radius: 4px;
    margin-top: 13px;
    padding: 9px 9px 7px 9px;
    color: #dcd9e0;
    font-weight: 500;
}
QGroupBox#platformCard::title, QGroupBox#dataCard::title,
QGroupBox#parameterCard::title, QGroupBox#actionsCard::title,
QGroupBox#afterEntryCard::title, QGroupBox#activityCard::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 11px;
    padding: 0 6px;
    color: #a9a5ad;
    font-size: 11px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QLabel {
    color: #bdb9c1;
}
QMainWindow#tradingHelperMain QLabel[role="value"] {
    color: #f0edf2;
    font-size: 12px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QLabel[role="caption"] {
    color: #99949e;
    font-size: 11px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QLineEdit,
QMainWindow#tradingHelperMain QComboBox {
    color: #eeeaf0;
    background: #1b1b1e;
    border: 1px solid #37343b;
    border-radius: 3px;
    min-height: 28px;
    padding: 1px 25px 1px 10px;
    selection-background-color: #59496a;
}
QMainWindow#tradingHelperMain QComboBox::drop-down {
    width: 27px;
    border: 0;
}
QMainWindow#tradingHelperMain QComboBox::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
QMainWindow#tradingHelperMain QLineEdit:hover,
QMainWindow#tradingHelperMain QComboBox:hover {
    border-color: #6b6372;
}
QMainWindow#tradingHelperMain QLineEdit:focus,
QMainWindow#tradingHelperMain QComboBox:focus {
    background: #222024;
    border: 1px solid #ab96bc;
}
QMainWindow#tradingHelperMain QComboBox QAbstractItemView {
    color: #e8e3e9;
    background: #1b1a1e;
    selection-background-color: #473b50;
    border: 1px solid #434047;
    outline: 0;
}
QMainWindow#tradingHelperMain QPushButton,
QMainWindow#tradingHelperMain QToolButton {
    color: #dad6de;
    background: #242326;
    border: 1px solid #3a373d;
    border-radius: 3px;
    min-height: 28px;
    padding: 3px 11px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QPushButton:hover,
QMainWindow#tradingHelperMain QToolButton:hover {
    background: #323035;
    border-color: #86758f;
}
QMainWindow#tradingHelperMain QPushButton:pressed,
QMainWindow#tradingHelperMain QToolButton:pressed {
    background: #3b3542;
}
QMainWindow#tradingHelperMain QPushButton:disabled,
QMainWindow#tradingHelperMain QToolButton:disabled {
    color: #77737a;
    background: #1d1c20;
    border-color: #29282c;
}
QMainWindow#tradingHelperMain QPushButton#fillBothPrimary {
    background: #37303e;
    color: #f5ecfa;
    border: 1px solid #aa91b9;
    border-radius: 4px;
    font-size: 13px;
    font-weight: 600;
    min-height: 35px;
}
QMainWindow#tradingHelperMain QPushButton#fillBothPrimary:hover {
    background: #4c4055;
    border-color: #c5aed5;
}
QMainWindow#tradingHelperMain QPushButton#fillBothPrimary:disabled {
    background: #25212a;
    color: #827b87;
    border-color: #4d4553;
}
QMainWindow#tradingHelperMain QPushButton[variant="accentOutline"] {
    color: #d4c5de;
    background: #29252e;
    border-color: #53495b;
}
QMainWindow#tradingHelperMain QToolButton#profile_manage_button,
QMainWindow#tradingHelperMain QToolButton#display_settings_button {
    color: #dad5dc;
    background: #242326;
    border-color: #444049;
    border-radius: 3px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QCheckBox {
    color: #d2ced5;
    spacing: 7px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QPlainTextEdit {
    color: #afaab6;
    background: #151416;
    border: 1px solid #2b2930;
    border-radius: 3px;
    padding: 6px 9px;
    selection-background-color: #5c4c66;
}
QMainWindow#tradingHelperMain QScrollBar:vertical {
    width: 7px;
    background: #111114;
}
QMainWindow#tradingHelperMain QScrollBar::handle:vertical {
    background: #424046;
    border-radius: 3px;
    min-height: 25px;
}
QMenu {
    background: #1d1c1f;
    color: #e4e0e7;
    border: 1px solid #3e3943;
    border-radius: 3px;
    padding: 5px;
}
QMenu::item {
    padding: 8px 21px 8px 12px;
    border-radius: 2px;
}
QMenu::item:selected { background: #3c3443; }
QMenu::separator { height: 1px; margin: 4px 7px; background: #3c3940; }
QToolTip {
    color: #e4dfe8;
    background: #27252a;
    border: 1px solid #514757;
}
"""


# Phase 1 of the DeepCharts-inspired redesign:
# A genuinely flat, text-first *application toolbar*.
# Window chrome remains native until the separately tested Phase 3.
MAIN_THEME += """
QFrame#headerCard {
    background: #0f0f10;
    border: none;
    border-bottom: 1px solid #29282b;
    border-radius: 0;
}
QFrame#headerCard QLabel#appTitle {
    font-size: 16px;
    font-weight: 700;
    color: #e8e6e9;
}
QFrame#headerCard QLabel#versionPill {
    background: transparent;
    border: none;
    border-radius: 0;
    color: #817d83;
    padding: 0px 1px;
    font-size: 10px;
    font-weight: 400;
}
QFrame#headerCard QLabel#moduleKicker {
    color: #aaa5ac;
    font-size: 11px;
    font-weight: 400;
}
QFrame#headerCard QComboBox#headerProfileCombo {
    background: transparent;
    color: #e1dfe2;
    border: 1px solid transparent;
    border-radius: 2px;
    min-height: 30px;
    padding: 1px 28px 1px 7px;
}
QFrame#headerCard QComboBox#headerProfileCombo:hover {
    background: #1c1b1e;
}
QFrame#headerCard QComboBox#headerProfileCombo:focus {
    background: #211e25;
    border: 1px solid #5d4e64;
}
QFrame#headerCard QComboBox#headerProfileCombo::drop-down {
    width: 25px;
    border: 0;
}
QFrame#headerCard QComboBox#headerProfileCombo::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
QMainWindow#tradingHelperMain QToolButton#profile_manage_button,
QMainWindow#tradingHelperMain QToolButton#display_settings_button,
QMainWindow#tradingHelperMain QPushButton#headerHelpButton,
QMainWindow#tradingHelperMain QPushButton#headerSheetButton {
    background: transparent;
    border: 1px solid transparent;
    color: #d6d2d9;
    border-radius: 2px;
    padding: 3px 21px 3px 9px;
    font-size: 12px;
    font-weight: 400;
    min-height: 29px;
}
QMainWindow#tradingHelperMain QPushButton#headerHelpButton,
QMainWindow#tradingHelperMain QPushButton#headerSheetButton {
    padding: 3px 9px;
}
QMainWindow#tradingHelperMain QToolButton#profile_manage_button:hover,
QMainWindow#tradingHelperMain QToolButton#display_settings_button:hover,
QMainWindow#tradingHelperMain QPushButton#headerHelpButton:hover,
QMainWindow#tradingHelperMain QPushButton#headerSheetButton:hover {
    background: #242127;
    border: 1px solid transparent;
    color: #f5f1f8;
}
QMainWindow#tradingHelperMain QToolButton#profile_manage_button:pressed,
QMainWindow#tradingHelperMain QToolButton#display_settings_button:pressed,
QMainWindow#tradingHelperMain QPushButton#headerHelpButton:pressed,
QMainWindow#tradingHelperMain QPushButton#headerSheetButton:pressed {
    background: #312b36;
}
QToolButton#profile_manage_button::menu-indicator,
QToolButton#display_settings_button::menu-indicator {
    image: none;
    width: 0px;
    height: 0px;
}
QFrame#headerCard QFrame#autoEntryPanel {
    background: transparent;
    border: 0;
}
QFrame#headerCard QLabel#entryStatus {
    color: #8b858f;
    font-size: 11px;
}
"""


# Compact frameless title bar (custom window controls, all existing actions
# remain connected to their original slots). No bright blocks or dashboard row.
MAIN_THEME += """
QFrame#compactTitleBar {
    background-color: #111113;
    border: 0;
    border-bottom: 1px solid #29272a;
    border-radius: 0;
}
QFrame#compactTitleBar QLabel#appTitle {
    font-size: 14px;
    font-weight: 700;
    color: #e9e6ec;
    background: transparent;
}
QFrame#compactTitleBar QLabel#versionPill {
    color: #89828f;
    font-size: 9px;
    padding: 0 2px;
    font-weight: 400;
    border: 0;
    background: transparent;
}
QFrame#compactTitleBar QLabel#moduleKicker {
    color: #aba4ad;
    font-size: 11px;
    background: transparent;
}
QFrame#compactTitleBar QComboBox#headerProfileCombo {
    color: #e0dde1;
    background: transparent;
    border: 1px solid transparent;
    min-height: 28px;
    border-radius: 2px;
    padding: 0px 27px 0px 7px;
}
QFrame#compactTitleBar QComboBox#headerProfileCombo:hover {
    background: #252327;
}
QFrame#compactTitleBar QComboBox#headerProfileCombo:focus {
    border-color: #74657a;
}
QFrame#compactTitleBar QComboBox#headerProfileCombo::drop-down {
    width: 26px;
    border: none;
}
QFrame#compactTitleBar QComboBox#headerProfileCombo::down-arrow {
    image: none;
    width: 0;
    height: 0;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#profile_manage_button,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#display_settings_button,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerHelpButton,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerSheetButton {
    background: transparent;
    color: #d4d0d8;
    border: 1px solid transparent;
    border-radius: 2px;
    font-size: 11px;
    font-weight: 400;
    min-height: 27px;
    padding: 1px 7px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#profile_manage_button,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#display_settings_button {
    padding-right: 21px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#profile_manage_button:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#display_settings_button:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerHelpButton:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerSheetButton:hover {
    background: #29262c;
}
QFrame#compactTitleBar QCheckBox#auto_entry_on_fill_both {
    color: #c7c1cb;
    spacing: 6px;
    font-size: 11px;
    font-weight: 400;
    background: transparent;
}
QFrame#compactTitleBar QCheckBox#auto_entry_on_fill_both::indicator {
    width: 14px;
    height: 14px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_minimize,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_maximize,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_close {
    background: transparent;
    color: #c9c4cd;
    border: 0;
    padding: 0px;
    margin: 0px;
    border-radius: 0;
    min-width: 30px;
    min-height: 30px;
    max-width: 30px;
    max-height: 30px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_minimize:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_maximize:hover {
    background: #1d1b25;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_close:hover {
    background: #38202a;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_minimize:pressed,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#chrome_maximize:pressed {
    background: #463d49;
}
QMainWindow#tradingHelperMain QWidget#appSurface {
    background: #0c0c0e;
}
"""


# Three-workspace update: a native-feeling text tab bar with restrained active
# state. The Trade workspace intentionally has no scroll container or cards
# containing settings/calibration shortcuts.
MAIN_THEME += """
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navTrade,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navEdit,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navRecords {
    background: transparent;
    border: none;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    min-height: 31px;
    padding: 0 9px;
    color: #aaa6ae;
    font-weight: 500;
    font-size: 11px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navTrade:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navEdit:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navRecords:hover {
    background: #211f23;
    color: #e4dfe8;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navTrade:checked,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navEdit:checked,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navRecords:checked {
    background: transparent;
    color: #f0edf3;
    border-bottom: 2px solid #ae96bd;
}
QWidget#editWorkspace, QWidget#recordsWorkspace, QWidget#tradeQuickActions {
    background: #0c0c0e;
}
QMainWindow#tradingHelperMain QGroupBox#editSheetGroup,
QMainWindow#tradingHelperMain QGroupBox#editWindowGroup,
QMainWindow#tradingHelperMain QGroupBox#editCalibrationGroup {
    background: #111113;
    border: 1px solid #29272d;
    border-radius: 3px;
    margin-top: 15px;
    padding: 10px 10px 8px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QGroupBox#editSheetGroup::title,
QMainWindow#tradingHelperMain QGroupBox#editWindowGroup::title,
QMainWindow#tradingHelperMain QGroupBox#editCalibrationGroup::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 11px;
    padding: 0 6px;
    color: #a9a5ad;
    font-size: 11px;
    font-weight: 600;
}
QLabel#workspaceCaption {
    color: #a8a2ae;
    font-weight: 500;
    font-size: 11px;
}
QLabel#tradeRecentStatus {
    color: #8f8a93;
    background: #0c0c0e;
    border-top: 1px solid #28262b;
    padding: 0px 6px;
    font-size: 10px;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton {
    background: transparent;
    color: #d7cfdf;
    border: 1px solid transparent;
    border-radius: 2px;
    min-height: 28px;
    padding: 2px 8px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton:hover {
    background: #29242e;
    border-color: #4b4052;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard {
    background: #111113;
    border-color: #28262b;
}
"""


# Compact professional market-information & action layout. This is presentation
# only: original signal handlers, platform bindings, and all eleven data keys
# remain unchanged. Avoid dashboard-over-styling and heavy nested cards.
MAIN_THEME += """
QMainWindow#tradingHelperMain QGroupBox#dataCard {
    background: #111113;
    border: 1px solid #302d34;
    border-radius: 4px;
    margin-top: 13px;
    padding: 10px 6px 5px;
}
QMainWindow#tradingHelperMain QWidget#platformSelectorRow,
QMainWindow#tradingHelperMain QWidget#sheetDataValues,
QMainWindow#tradingHelperMain QWidget#automationOptionRow {
    background: transparent;
    border: none;
}
QFrame#dataSeparator {
    border: none;
    border-top: 1px solid #302c32;
    min-height: 1px;
    max-height: 1px;
}
QMainWindow#tradingHelperMain QLabel#automationCaption {
    color: #8f8993;
    font-size: 10px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QCheckBox#auto_entry_on_fill_both,
QMainWindow#tradingHelperMain QCheckBox#auto_sync_sl_tp_after_entry,
QMainWindow#tradingHelperMain QCheckBox#auto_draw_tv_after_entry {
    font-size: 11px;
    font-weight: 400;
    color: #cec9d1;
    background: transparent;
    spacing: 5px;
}
QMainWindow#tradingHelperMain QCheckBox#auto_entry_on_fill_both::indicator,
QMainWindow#tradingHelperMain QCheckBox#auto_sync_sl_tp_after_entry::indicator,
QMainWindow#tradingHelperMain QCheckBox#auto_draw_tv_after_entry::indicator {
    width: 14px;
    height: 14px;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard {
    background: transparent;
    border: none;
    border-radius: 0;
    margin-top: 9px;
    padding: 4px 2px 0px;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 9px;
    padding: 0px 5px;
    color: #9d969f;
    font-size: 11px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QPushButton#manualSyncSlTp,
QMainWindow#tradingHelperMain QPushButton#manualDrawTv {
    background: #1c1b1f;
    border: 1px solid #35323a;
    border-radius: 3px;
    color: #d4ced7;
    font-size: 11px;
    font-weight: 500;
    min-height: 27px;
    padding: 2px 8px;
}
QMainWindow#tradingHelperMain QPushButton#manualSyncSlTp:hover,
QMainWindow#tradingHelperMain QPushButton#manualDrawTv:hover {
    background: #29252d;
    border-color: #796a83;
}
QMainWindow#tradingHelperMain QGroupBox#editManualEntryGroup {
    background: #111113;
    border: 1px solid #302d34;
    margin-top: 15px;
    padding: 8px 7px 5px;
    border-radius: 3px;
}
QMainWindow#tradingHelperMain QGroupBox#editManualEntryGroup::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 11px;
    padding: 0 5px;
    color: #a9a2ad;
    font-size: 11px;
}
""";


# DeepCharts-inspired three-zone trading workspace, intentionally using
# fewer enclosing rectangles: one calm surface, a faint vertical divider,
# aligned information rows, and one unmistakable primary fill control.
MAIN_THEME += """
QMainWindow#tradingHelperMain QWidget#tradeThreeZoneBody,
QMainWindow#tradingHelperMain QWidget#tradeLeftZone,
QMainWindow#tradingHelperMain QWidget#tradeRightZone {
    background: #0c0c0e;
    border: none;
}
QMainWindow#tradingHelperMain QFrame#tradeVerticalDivider {
    border: 0;
    border-left: 1px solid #29272d;
    background: transparent;
    min-width: 1px;
    max-width: 1px;
}
QMainWindow#tradingHelperMain QGroupBox#dataCard,
QMainWindow#tradingHelperMain QGroupBox#parameterCard,
QMainWindow#tradingHelperMain QGroupBox#actionsCard {
    background: transparent;
    border: 0;
    border-radius: 0;
    margin-top: 18px;
    padding: 6px 0 0 0;
    color: #e9e5ec;
    font-size: 12px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QGroupBox#dataCard::title,
QMainWindow#tradingHelperMain QGroupBox#parameterCard::title,
QMainWindow#tradingHelperMain QGroupBox#actionsCard::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 2px;
    padding: 0 3px;
    color: #e9e5ec;
    font-size: 12px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QWidget#tradeDataPair {
    background: transparent;
    border: 0;
}
QMainWindow#tradingHelperMain QFrame#infoInnerDivider,
QMainWindow#tradingHelperMain QFrame#dataSeparator {
    border: 0;
    border-top: 1px solid #302d33;
    min-height: 1px;
    max-height: 1px;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QLineEdit,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QComboBox {
    background: #1b1a1e;
    border: 1px solid #49424e;
    border-radius: 3px;
    color: #eeeaf1;
    padding: 2px 9px;
    min-height: 27px;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QLineEdit:focus,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QComboBox:focus {
    border: 1px solid #ad95b9;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton {
    border: 1px solid #3b373e;
    background: #242126;
    color: #ddd7e1;
    border-radius: 3px;
    min-height: 33px;
    font-size: 12px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary {
    background: #332939;
    color: #f5edf8;
    border: 1px solid #a88ab8;
    min-height: 41px;
    font-size: 13px;
    font-weight: 650;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary:hover {
    background: #493852;
    border: 1px solid #c7afd2;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard {
    border: 0;
    background: transparent;
    margin-top: 13px;
    padding: 0;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 2px;
    color: #8f8893;
    font-size: 10px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard QPushButton {
    border: 1px solid #302e33;
    background: transparent;
    color: #bdb4c4;
    font-size: 11px;
    min-height: 27px;
    padding: 2px 6px;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton {
    border: 0;
    color: #d5bfdc;
    background: transparent;
    min-height: 26px;
    padding: 1px 3px;
    font-size: 11px;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton:hover {
    border: 0;
    color: #f0ddf9;
    background: #221e26;
}
QMainWindow#tradingHelperMain QLabel#tradeRecentStatus {
    border: 0;
    border-top: 1px solid #29272d;
    padding: 4px 2px 0 2px;
    color: #85808a;
    min-height: 19px;
    font-size: 10px;
}
""";


# Information-row alignment and understated inline parameter actions (2026-10-14).
MAIN_THEME += """
QMainWindow#tradingHelperMain QWidget#reloadToolbar,
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell,
QMainWindow#tradingHelperMain QWidget#tradePlatformCell,
QMainWindow#tradingHelperMain QWidget#parameterInlineActions {
    border: none;
    background: transparent;
}
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="caption"] {
    color: #92909a;
    font-size: 10px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="value"] {
    color: #ede9f0;
    font-size: 12px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction {
    color: #cfc9d1;
    background: #242126;
    border: 1px solid #46404a;
    border-radius: 3px;
    padding: 1px 5px;
    font-size: 11px;
    font-weight: 500;
    min-height: 0;
    max-height: 31px;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction:hover,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction:hover {
    background: #362e3b;
    border-color: #9c8ba8;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction:disabled,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction:disabled {
    color: #807a83;
    background: #1c1a1f;
    border-color: #29262d;
}
""";


# Two-column reference / action workspace. Custom inline information heading
# replaces the old extra refresh row; only presentation selectors change.
MAIN_THEME += """
QMainWindow#tradingHelperMain QGroupBox#dataCard {
    margin-top: 0;
    padding: 0;
    background: transparent;
    border: 0;
}
QMainWindow#tradingHelperMain QLabel#tradeDataHeading {
    color: #e9e5ec;
    font-size: 12px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QWidget#reloadToolbar {
    min-height: 28px;
    max-height: 33px;
}
QMainWindow#tradingHelperMain QWidget#tradePlatformCell QComboBox {
    min-height: 33px;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard,
QMainWindow#tradingHelperMain QGroupBox#actionsCard {
    margin-top: 18px;
    padding-top: 3px;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction {
    padding-left: 4px;
    padding-right: 4px;
}
""";

# Compact account-progress strip within unused space at bottom left.
MAIN_THEME += """
QWidget#accountRulerSection {
    background: transparent;
    border-top: 1px solid #29262d;
}
QLabel#accountRulerTitle {
    color: #ddd5e1;
    font-size: 12px;
    font-weight: 600;
}
QWidget#accountRulerScale {
    background: transparent;
}
QMainWindow#tradingHelperMain QPushButton#accountRulerSettings {
    background: transparent;
    border: none;
    color: #bfa7ca;
    font-size: 11px;
    font-weight: 500;
    min-height: 22px;
    padding: 1px 6px;
}
QMainWindow#tradingHelperMain QPushButton#accountRulerSettings:hover {
    background: #262129;
}
QLabel#rulerWinCount, QLabel#rulerLossCount {
    color: #a99baa;
    font-size: 10px;
    font-weight: 400;
    padding: 0px 3px;
}
"""

# ---------------------------------------------------------------------------
# DESIGN.md / Linear.app inspired desktop-workflow refinement (2026-10-14)
# Source: arumwu/design-md-skill -> voltagent/awesome-design-md/linear.app
# Tokens: canvas #010102, surfaces #0f1011/#18191a, hairline #23252a,
# primary #5e6ad2, ink #f7f8f8, subtle #8a8f98.
# Adapted to PySide6 desktop trading: 12-13px type, compact 4/8/12px rhythm.
# This is only a presentation layer; actions and service calls remain untouched.
# ---------------------------------------------------------------------------
MAIN_THEME += """
QMainWindow#tradingHelperMain,
QMainWindow#tradingHelperMain QWidget#appSurface,
QMainWindow#tradingHelperMain QWidget#tradeThreeZoneBody,
QMainWindow#tradingHelperMain QWidget#tradeLeftZone,
QMainWindow#tradingHelperMain QWidget#tradeRightZone {
    background-color: #101114;
    color: #e5e6ec;
    font-family: "Segoe UI", "Microsoft JhengHei UI";
    font-size: 12px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar {
    background: #141519;
    border: 0;
    border-bottom: 1px solid #292b32;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QLabel#appTitle {
    font-size: 14px;
    font-weight: 600;
    color: #f4f4f6;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QLabel#versionPill {
    color: #8b8e9a;
    font-size: 9px;
    font-weight: 500;
    background: transparent;
    padding: 0 2px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QLabel#moduleKicker {
    color: #828590;
    font-size: 10px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navTrade,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navEdit,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navRecords {
    color: #9b9da6;
    background: transparent;
    border: 0;
    border-bottom: 2px solid transparent;
    border-radius: 0;
    padding: 0 11px;
    font-size: 12px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navTrade:checked,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navEdit:checked,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navRecords:checked {
    background: transparent;
    color: #f0f0f5;
    border-bottom: 2px solid #7179d9;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navTrade:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navEdit:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navRecords:hover {
    color: #eeeff4;
    background: #1b1c22;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QComboBox#headerProfileCombo {
    color: #e6e7ed;
    background: #1b1c22;
    border: 1px solid #2d2f38;
    border-radius: 5px;
    min-height: 27px;
    padding: 0 28px 0 9px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QComboBox#headerProfileCombo:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QComboBox#headerProfileCombo:focus {
    border-color: #5e6ad2;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#profile_manage_button,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#display_settings_button,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerHelpButton,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerSheetButton {
    color: #aeb0bc;
    background: transparent;
    border: 0;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#profile_manage_button:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QToolButton#display_settings_button:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerHelpButton:hover,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#headerSheetButton:hover {
    color: #f7f8f8;
    background: #21232a;
}
QMainWindow#tradingHelperMain QFrame#tradeVerticalDivider {
    border: 0;
    border-left: 1px solid #292b32;
    background: transparent;
    min-width: 1px;
    max-width: 1px;
}
QMainWindow#tradingHelperMain QGroupBox#dataCard,
QMainWindow#tradingHelperMain QGroupBox#parameterCard,
QMainWindow#tradingHelperMain QGroupBox#actionsCard,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard {
    background: transparent;
    border: 0;
    border-radius: 0;
    color: #eeeff3;
    padding: 0;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard,
QMainWindow#tradingHelperMain QGroupBox#actionsCard {
    margin-top: 17px;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard {
    margin-top: 15px;
}
QMainWindow#tradingHelperMain QLabel#tradeDataHeading,
QMainWindow#tradingHelperMain QGroupBox#parameterCard::title,
QMainWindow#tradingHelperMain QGroupBox#actionsCard::title {
    color: #eff0f4;
    font-size: 13px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard::title,
QMainWindow#tradingHelperMain QGroupBox#actionsCard::title,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 4px;
    padding: 0 2px;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard::title {
    color: #9295a0;
    font-size: 11px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QFrame#dataSeparator,
QMainWindow#tradingHelperMain QFrame#infoInnerDivider {
    border: 0;
    border-top: 1px solid #292b32;
    min-height: 1px;
    max-height: 1px;
}
QMainWindow#tradingHelperMain QLabel[role="caption"],
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="caption"] {
    color: #8e929e;
    font-size: 11px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QLabel[role="value"],
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="value"] {
    color: #ededf1;
    font-size: 13px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="value"] {
    font-size: 14px;
}
QMainWindow#tradingHelperMain QLineEdit,
QMainWindow#tradingHelperMain QComboBox,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QLineEdit,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QComboBox {
    background: #1a1b21;
    border: 1px solid #32343e;
    color: #f0f0f5;
    border-radius: 5px;
    font-size: 12px;
    font-weight: 400;
    min-height: 31px;
    padding: 1px 9px;
    selection-background-color: #5e6ad2;
}
QMainWindow#tradingHelperMain QLineEdit:hover,
QMainWindow#tradingHelperMain QComboBox:hover,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QLineEdit:hover,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QComboBox:hover {
    border-color: #535762;
}
QMainWindow#tradingHelperMain QLineEdit:focus,
QMainWindow#tradingHelperMain QComboBox:focus,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QLineEdit:focus,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QComboBox:focus {
    border-color: #6670c7;
    background: #20212a;
}
QMainWindow#tradingHelperMain QWidget#tradePlatformCell QComboBox {
    min-height: 34px;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard QPushButton {
    color: #dddfe7;
    background: #202127;
    border: 1px solid #343640;
    border-radius: 5px;
    min-height: 33px;
    font-size: 12px;
    font-weight: 500;
    padding: 2px 10px;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton:hover,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard QPushButton:hover {
    color: #f7f7fb;
    background: #292c34;
    border-color: #5c606b;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary {
    background: #4854a9;
    border: 1px solid #6571c8;
    color: #f8f8ff;
    font-size: 13px;
    font-weight: 600;
    border-radius: 5px;
    min-height: 41px;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary:hover {
    background: #5d68c1;
    border-color: #8791e6;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton,
QMainWindow#tradingHelperMain QPushButton#accountRulerSettings {
    background: transparent;
    border: 1px solid transparent;
    border-radius: 4px;
    color: #9fa5e2;
    font-size: 11px;
    font-weight: 500;
    min-height: 25px;
    padding: 0 5px;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton:hover,
QMainWindow#tradingHelperMain QPushButton#accountRulerSettings:hover {
    color: #e6e9ff;
    background: #20232c;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction {
    background: #202127;
    color: #cdd0db;
    border: 1px solid #373944;
    border-radius: 4px;
    font-size: 11px;
    font-weight: 500;
    min-height: 0px;
    max-height: 31px;
    padding: 1px 4px;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction:hover,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction:hover {
    background: #2b2d35;
    border-color: #737aa5;
}
QMainWindow#tradingHelperMain QWidget#accountRulerSection {
    background: transparent;
    border: 0;
    border-top: 1px solid #30323a;
}
QMainWindow#tradingHelperMain QLabel#accountRulerTitle {
    color: #eff0f4;
    font-size: 13px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QLabel#rulerWinCount,
QMainWindow#tradingHelperMain QLabel#rulerLossCount {
    color: #aeb0bc;
    background: transparent;
    font-size: 11px;
    padding: 0 1px;
}
QMainWindow#tradingHelperMain QLabel#rulerWinCount {
    color: #bac0eb;
}
QMainWindow#tradingHelperMain QLabel#tradeRecentStatus {
    color: #777c88;
    border: 0;
    border-top: 1px solid #262930;
    background: #101114;
    padding: 3px 0;
    font-size: 10px;
}
"""

# Final density pass: 40px primary, 36px secondary desktop controls.
MAIN_THEME += """
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton {
    min-height: 29px;
    max-height: 37px;
    padding: 1px 10px;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary {
    min-height: 36px;
    max-height: 42px;
    padding: 1px 10px;
    background: #3d467d;
    border: 1px solid #6873be;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary:hover {
    background: #4d5894;
    border-color: #8894dc;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard QPushButton {
    min-height: 28px;
    max-height: 36px;
}
"""

# Revolut-inspired compact trading terminal, 2026-10-15.
# Reference: voltagent/awesome-design-md/design-md/revolut/DESIGN.md.
# Native app adaptation: near-black canvas, light primary action, restrained
# cobalt selection, 8-12px rounding on inputs; no oversized marketing cards.
MAIN_THEME += """
QMainWindow#tradingHelperMain,
QMainWindow#tradingHelperMain QWidget#appSurface,
QMainWindow#tradingHelperMain QWidget#tradeThreeZoneBody,
QMainWindow#tradingHelperMain QWidget#tradeLeftZone,
QMainWindow#tradingHelperMain QWidget#tradeRightZone {
    background: #08080b;
    color: #f4f4f8;
    font-family: "Segoe UI", "Microsoft JhengHei UI";
    font-size: 12px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar {
    background: #0a0a0d;
    border: 0;
    border-bottom: 1px solid #23232d;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QLabel#appTitle {
    color: #f9f9fc;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navTrade:checked,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navEdit:checked,
QMainWindow#tradingHelperMain QFrame#compactTitleBar QPushButton#navRecords:checked {
    color: #ffffff;
    border-bottom: 2px solid #9e87ff;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QComboBox#headerProfileCombo {
    color: #f1f1f7;
    background: #1a1a22;
    border: 1px solid #30303b;
    border-radius: 9px;
    padding: 0 26px 0 10px;
}
QMainWindow#tradingHelperMain QFrame#compactTitleBar QComboBox#headerProfileCombo:focus {
    border-color: #7979e5;
}
QMainWindow#tradingHelperMain QFrame#tradeVerticalDivider {
    border: 0;
    border-left: 1px solid #282830;
    background: transparent;
}
QMainWindow#tradingHelperMain QGroupBox#dataCard,
QMainWindow#tradingHelperMain QGroupBox#parameterCard,
QMainWindow#tradingHelperMain QGroupBox#actionsCard,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard {
    background: transparent;
    border: 0;
    border-radius: 0;
    color: #f3f3f6;
}
QMainWindow#tradingHelperMain QLabel#tradeDataHeading,
QMainWindow#tradingHelperMain QGroupBox#parameterCard::title,
QMainWindow#tradingHelperMain QGroupBox#actionsCard::title,
QMainWindow#tradingHelperMain QLabel#accountRulerTitle {
    color: #f5f5fa;
    font-size: 13px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard::title {
    color: #a3a3ae;
    font-size: 11px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QFrame#dataSeparator,
QMainWindow#tradingHelperMain QFrame#infoInnerDivider,
QMainWindow#tradingHelperMain QWidget#accountRulerSection {
    border: 0;
    border-top: 1px solid #282831;
    background: transparent;
}
QMainWindow#tradingHelperMain QLabel[role="caption"],
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="caption"] {
    color: #9797a4;
    font-size: 11px;
    font-weight: 400;
}
QMainWindow#tradingHelperMain QLabel[role="value"],
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="value"] {
    color: #f1f1f7;
    font-size: 13px;
    font-weight: 600;
}
QMainWindow#tradingHelperMain QWidget#centeredSummaryCell QLabel[role="value"] {
    font-size: 14px;
}
QMainWindow#tradingHelperMain QLineEdit,
QMainWindow#tradingHelperMain QComboBox,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QLineEdit,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QComboBox {
    color: #f4f4f9;
    background: #1b1b24;
    border: 1px solid #353540;
    border-radius: 9px;
    font-size: 12px;
    min-height: 31px;
    padding: 1px 9px;
    selection-background-color: #494fdf;
}
QMainWindow#tradingHelperMain QLineEdit:focus,
QMainWindow#tradingHelperMain QComboBox:focus,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QLineEdit:focus,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QComboBox:focus {
    background: #24242e;
    border-color: #777af1;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard QPushButton {
    color: #e4e4ec;
    background: #202029;
    border: 1px solid #33333e;
    border-radius: 10px;
    font-weight: 500;
    min-height: 30px;
    max-height: 39px;
    padding: 2px 10px;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton:hover,
QMainWindow#tradingHelperMain QGroupBox#afterEntryCard QPushButton:hover {
    color: #ffffff;
    background: #2d2d39;
    border-color: #555563;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary {
    background: #6955df;
    color: #faf9ff;
    border: 1px solid #8773f2;
    border-radius: 12px;
    font-size: 13px;
    font-weight: 600;
    min-height: 38px;
    max-height: 44px;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary:hover {
    background: #7d69f1;
    color: #ffffff;
    border-color: #9b8aff;
}
QMainWindow#tradingHelperMain QGroupBox#actionsCard QPushButton#fillBothPrimary:disabled {
    background: #2c2c35;
    color: #767683;
    border-color: #3a3a44;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction {
    background: #22222c;
    border: 1px solid #373743;
    border-radius: 8px;
    color: #dbdbe6;
    font-size: 11px;
    font-weight: 500;
    max-height: 31px;
    min-height: 0px;
    padding: 1px 4px;
}
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramPreviewAction:hover,
QMainWindow#tradingHelperMain QGroupBox#parameterCard QPushButton#paramUpdateAction:hover {
    background: #30303c;
    border-color: #626275;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton,
QMainWindow#tradingHelperMain QPushButton#accountRulerSettings {
    background: transparent;
    border: 0;
    border-radius: 7px;
    color: #b9b9f7;
    padding: 1px 6px;
    min-height: 25px;
    font-size: 11px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QPushButton#reloadSheetButton:hover,
QMainWindow#tradingHelperMain QPushButton#accountRulerSettings:hover {
    color: #ffffff;
    background: #22222d;
}
QMainWindow#tradingHelperMain QWidget#accountRulerScale {
    background: transparent;
    border: 0;
}
QMainWindow#tradingHelperMain QLabel#tradeRecentStatus {
    color: #858591;
    background: #08080b;
    border-top: 1px solid #26262f;
    font-size: 10px;
}
"""

# LAB closeout: native-tool-like settings instead of stacked AI dashboard cards.
MAIN_THEME += """
QMainWindow#tradingHelperMain QWidget#editWorkspace,
QMainWindow#tradingHelperMain QWidget#recordsWorkspace {
    background: #08080b;
}
QMainWindow#tradingHelperMain QGroupBox#editSheetGroup,
QMainWindow#tradingHelperMain QGroupBox#editWindowGroup,
QMainWindow#tradingHelperMain QGroupBox#editCalibrationGroup,
QMainWindow#tradingHelperMain QGroupBox#editManualEntryGroup {
    background: transparent;
    border: 0;
    border-bottom: 1px solid #292733;
    border-radius: 0;
    margin-top: 15px;
    padding: 8px 6px 6px;
    color: #eae8f0;
}
QMainWindow#tradingHelperMain QGroupBox#editSheetGroup::title,
QMainWindow#tradingHelperMain QGroupBox#editWindowGroup::title,
QMainWindow#tradingHelperMain QGroupBox#editCalibrationGroup::title,
QMainWindow#tradingHelperMain QGroupBox#editManualEntryGroup::title {
    color: #b4b0bd;
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 4px;
    padding: 0 3px;
    font-size: 11px;
    font-weight: 500;
}
QMainWindow#tradingHelperMain QGroupBox#editSheetGroup QPushButton,
QMainWindow#tradingHelperMain QGroupBox#editWindowGroup QPushButton,
QMainWindow#tradingHelperMain QGroupBox#editCalibrationGroup QPushButton {
    border-radius: 6px;
    background: #1b1b24;
    border: 1px solid #383540;
}
QMainWindow#tradingHelperMain QGroupBox#editSheetGroup QPushButton:hover,
QMainWindow#tradingHelperMain QGroupBox#editWindowGroup QPushButton:hover,
QMainWindow#tradingHelperMain QGroupBox#editCalibrationGroup QPushButton:hover {
    background: #292635;
    border-color: #6c5c9d;
}
"""
