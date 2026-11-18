"""Mobile adapter: share the desktop widgets/callbacks, never broker logic."""
from __future__ import annotations

import ctypes
import json
import os
import re
import time
import math
from dataclasses import asdict

from PySide6.QtCore import QObject, QSignalBlocker, QTimer
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QPushButton, QTextBrowser

from .remote_control import MobileServer, RemoteStore
from .remote_mobile import ASSETS
from .remote_tunnel import QuickTunnel, FixedTunnel

FIELDS = ("internal_balance", "daily_pnl", "expected_sl_combined", "internal_entry_price")
ACTIONS = {"direction", "stage", "profile", "update", "fill_both", "fill_internal",
           "fill_external", "sync", "view_sl_tp", "rule", "option", "warning", "refresh_news"}


def interactive_desktop() -> bool:
    """A locked Windows desktop cannot be treated as ready for UI input."""
    if os.name != "nt":
        return True
    user32 = ctypes.windll.user32
    user32.OpenInputDesktop.restype = ctypes.c_void_p
    handle = user32.OpenInputDesktop(0, False, 0x100)
    if not handle:
        return False
    user32.CloseDesktop.argtypes = [ctypes.c_void_p]
    user32.CloseDesktop(handle)
    return True


class RemoteController(QObject):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.store = RemoteStore(app.store.path.parent / "mobile-remote.sqlite3")
        self.server = MobileServer(self.store, ASSETS, self)
        self.server.command.connect(self._command)
        self.tunnel = QuickTunnel(self, diagnostic_path=app.store.path.parent / 'diagnostics' / 'mobile-connection.json')
        self.tunnel.ready.connect(self._tunnel_ready)
        self.tunnel.failed.connect(self._tunnel_failed)
        self.fixed_tunnel = FixedTunnel(self, diagnostic_path=app.store.path.parent / 'diagnostics' / 'mobile-fixed-connection.json')
        self.fixed_tunnel.ready.connect(self._fixed_ready)
        self.fixed_tunnel.failed.connect(self._fixed_failed)
        self.temporary_connection = False
        self.active = None
        self.dialog_owner = None
        self.dialog_widgets = {}
        self.dialog_id = ""
        self.dialog = None
        self.consumed_dialog = None
        self.phase = "就緒"
        self.last_busy = time.monotonic()
        self._desktop_ok = True
        self._desktop_checked = 0.0
        self._message_counts = {}
        self.timer = QTimer(self)
        self.timer.setInterval(150)
        self.timer.timeout.connect(self.tick)
        self.heartbeat = QTimer(self)
        self.heartbeat.setInterval(1000)
        self.heartbeat.timeout.connect(self._heartbeat)
        app.signals.status.connect(self._status)
        app.signals.error.connect(self._error)
        app.signals.auto_entry_result.connect(self._report)
        app.signals.remote_task_result.connect(self._task_result)
        QApplication.instance().aboutToQuit.connect(self.stop)
        self.settings_dialog = None

    def start(self, origin: str = "", port: int = 8765):
        self.server.start(origin, port)
        self.timer.start()
        self.heartbeat.start()
        self.tick()

    def stop(self):
        self.tunnel.stop()
        self.fixed_tunnel.stop()
        self.temporary_connection = False
        self.timer.stop()
        self.heartbeat.stop()
        if self.active:
            self.store.finish(self.active["device"], self.active["id"], "unknown",
                              {"message": "手機連線已關閉，請在電腦核對本次結果；不會重送。"})
            self.active = None
        self.server.stop()

    def start_temporary(self, port=8765):
        if self.active or self._busy():
            raise ValueError('電腦正在操作，請完成後再開啟手機連線。')
        self.stop()
        # Temporary hostnames cannot restore a browser session after restart.
        # Never persist one as if it were a stable, configured endpoint.
        self.store.set_setting('enabled', '0')
        self.temporary_connection = True
        try:
            self.start(port=port)
            self.tunnel.start(self.server.local_origin)
        except ValueError:
            self.stop()
            raise

    def _tunnel_ready(self, origin):
        from .remote_control import normalized_origin
        self.server.public_origin = normalized_origin(origin)
        self.server.arm_pairing()
        self.server.changed.emit()

    def start_fixed(self, port=8765):
        if self.active or self._busy():
            raise ValueError('電腦正在操作，請完成後再設定固定入口。')
        # Check prerequisites before stopping a working temporary connection.
        from .remote_tunnel import tailscale_path
        if not tailscale_path():
            raise ValueError('請先安裝 Tailscale 並登入，再按「建立固定入口」。不需要購買網域。')
        self.stop()
        try:
            self.start(port=port)
            self.fixed_tunnel.start(self.server.local_origin)
        except ValueError:
            self.stop()
            raise

    def _fixed_ready(self, origin):
        from .remote_control import normalized_origin
        self.server.public_origin = normalized_origin(origin)
        self.store.set_setting('origin', self.server.public_origin)
        self.store.set_setting('provider', 'tailscale')
        self.store.set_setting('enabled', '1')
        self.server.arm_pairing()
        self.server.changed.emit()

    def _fixed_failed(self, message):
        self.stop()
        self.fixed_tunnel.message = message
        self.tunnel.message = message
        self.app.log(message)
        self.server.changed.emit()

    def resume(self):
        if self.store.setting('provider') == 'tailscale':
            self.start_fixed()
        else:
            self.start(self.store.setting('origin'))

    def _tunnel_failed(self, message):
        self.stop()
        self.tunnel.message = message
        self.app.log(message)
        self.server.changed.emit()

    def _heartbeat(self):
        for sock in list(self.server.sockets):
            self.server.send(sock, {"type": "heartbeat", "time": time.time()})

    def _busy(self):
        app = self.app
        return bool(app._active_tasks or app._parameter_write_active or app._parameter_write_pending
                    or app._trade_settings_busy or app._update_in_progress or app._fill_waiting_for_sheet)

    def _status(self, text):
        self.phase = text

    def _error(self, text):
        if self.active:
            self.active["errors"].append(str(text))

    def _task_result(self, result):
        if self.active:
            self.active["tasks"].append(dict(result))
            self.last_busy = time.monotonic()

    def _report(self, result):
        if self.active:
            self.active["report"] = {key: result.get(key) for key in ("title", "message", "success")}
            self.last_busy = time.monotonic()

    def _current_dialog(self):
        modal = QApplication.activeModalWidget()
        if modal is not None:
            return modal
        for candidate in (getattr(self.app, "_auto_entry_receipt", None), self.dialog):
            if candidate is not None:
                try:
                    if candidate.isVisible():
                        return candidate
                except RuntimeError:
                    pass
        return None

    def _dialog_snapshot(self):
        dialog = self._current_dialog()
        if not self.dialog_owner or dialog is self.settings_dialog or dialog is None:
            return None
        if self.active is None and dialog is not self.dialog:
            # Owning an earlier result is not permission to control a local
            # settings dialog opened afterwards.
            return None
        if dialog is self.consumed_dialog:
            return dict(id="", title=dialog.windowTitle(), text="正在處理確認…",
                        buttons=[], checks=[], desktop_required=False)
        if dialog is not self.dialog:
            import secrets
            self.dialog_id = secrets.token_hex(12)
            self.dialog_widgets.clear()
            self.dialog = dialog
        if self.active and dialog.objectName() == "autoEntryResultDialog":
            self.active["receipt_shown"] = True
        texts = []
        for label in dialog.findChildren(QLabel):
            if (label.isVisible() and label.objectName() not in
                    {"dialogTitle", "messageIcon"} and label.text().strip() not in {"?", "!", "×", "i"}):
                if label.text().strip():
                    texts.append(label.text())
        for browser in dialog.findChildren(QTextBrowser):
            if browser.isVisible():
                texts.append(browser.toPlainText())
        buttons, checks = [], []
        for widget in dialog.findChildren(QPushButton)+dialog.findChildren(QCheckBox):
            if not widget.isVisible() or not widget.text().strip():
                continue
            key = str(id(widget))
            self.dialog_widgets[key] = widget
            item = dict(id=key, text=widget.text().replace("&", ""), enabled=widget.isEnabled())
            if isinstance(widget, QCheckBox):
                item["checked"] = widget.isChecked()
                checks.append(item)
            else:
                buttons.append(item)
        # Do not guess at unsupported editors or a desktop setup dialog.
        unsupported = any(w.isVisible() for w in dialog.findChildren(QLineEdit))
        return dict(id=self.dialog_id, title=dialog.windowTitle(), text="\n".join(dict.fromkeys(texts))[:12000],
                    buttons=[] if unsupported else buttons, checks=checks,
                    desktop_required=unsupported)

    def snapshot(self):
        app = self.app
        busy = self._busy()
        modal = self._current_dialog()
        available = not busy and not self.active and modal is None and self._desktop_ok
        parameters = {key: dict(raw=app.parameter_inputs[key].text(),
                               value=app.parameter_inputs[key].placeholderText(),
                               enabled=available and app.parameter_inputs[key].isEnabled()) for key in FIELDS}
        options = {key: dict(checked=widget.isChecked(), enabled=available and widget.isEnabled())
                   for key, widget in self._options().items()}
        calendar = getattr(app, "_event_calendar", None)
        news = []
        if calendar is not None:
            from datetime import datetime, timedelta, timezone
            recent = datetime.now(timezone.utc)-timedelta(days=1)
            for event in sorted(event for event in calendar.events
                                if recent <= event.when <= datetime.now(timezone.utc)+timedelta(days=45))[:60]:
                news.append(dict(when=event.when.isoformat(), title=calendar.title(event.title),
                                 source=event.source, scheduled=True, details=event.details))
            for event in calendar.news[:30]:
                from .news_relevance import assess_headline
                if not recent <= event.when <= datetime.now(timezone.utc) or not assess_headline(event.title).notify:
                    continue
                news.append(dict(when=event.when.isoformat(), title=calendar.title(event.title),
                                 source=event.source, scheduled=False, details=event.details))
        ruler = app.account_ruler.state
        if ruler != getattr(self, '_ruler_state', None):
            from .progress_ruler import render_mobile_ruler
            import hashlib
            self.server.ruler_image = render_mobile_ruler(ruler)
            self._ruler_state = ruler
            self._ruler_revision = hashlib.sha256(self.server.ruler_image).hexdigest()[:16]
        return dict(
            profile=app.profiles.active_name, profiles=app.profiles.names(),
            stage=app.stage_selector.currentText(),
            stages=[app.stage_selector.itemText(i) for i in range(app.stage_selector.count())],
            stage_enabled=available and app.stage_selector.isEnabled(),
            direction=app.internal_direction_input.currentData(),
            direction_enabled=available and app.internal_direction_input.isEnabled(),
            platforms={role: getattr(app, role+"_platform").currentText() for role in ("internal", "external")},
            parameters=parameters, options=options,
            values={key: value.text() for key, value in app.data_labels.items()},
            ruler=json.loads(json.dumps(asdict(ruler), default=str)) if ruler is not None else None,
            ruler_revision=getattr(self, '_ruler_revision', ''),
            warnings={"internal_balance": app._balance_warning_active(),
                      "expected_sl_combined": app._expected_sl_warning_values() is not None},
            actions={"fill_both": available and app.action_buttons["填入兩邊"].isEnabled(),
                     "fill_internal": available and app.action_buttons["填入場內"].isEnabled(),
                     "fill_external": available and app.action_buttons["填入場外"].isEnabled(),
                     "update": available, "sync": available, "view_sl_tp": available},
            available=available, busy=busy or bool(self.active),
            health="無法操作" if not self._desktop_ok else "執行中" if busy or self.active else
                   f"請先處理電腦上的「{modal.windowTitle() or '確認'}」視窗" if modal and modal is not self.dialog else
                   "請確認下方提示" if modal else "請調整場內餘額" if app._balance_warning_active()
                   else "等待交易資料" if app.instruction is None else "正常",
            phase=self.phase, dialog=self._dialog_snapshot(), news=news,
            news_error=calendar.error if calendar else "消息尚未載入",
        )

    def _options(self):
        app = self.app
        return {"auto_entry": app.auto_entry_on_fill_both,
                "auto_sync": app.auto_sync_sl_tp_after_entry,
                **{"rule:"+key: value for key, value in app.trade_rule_checkboxes.items()}}

    def tick(self):
        if time.monotonic()-self._desktop_checked > 2:
            self._desktop_ok = interactive_desktop()
            self._desktop_checked = time.monotonic()
        state = self.snapshot()
        self.server.publish(state)
        if self.active:
            if self._busy() or state["dialog"]:
                self.last_busy = time.monotonic()
            elif time.monotonic()-self.last_busy > 0.7:
                self._finish()

    def _finish(self):
        item = self.active
        report = item["report"]
        tasks = item["tasks"]
        if item["errors"]:
            status, message = "failed", item["errors"][-1]
        elif report:
            status = "completed" if report.get("success") else "needs_review"
            message = str(report.get("message") or "請核對兩側進場結果。")
        elif any(t["status"] in {"failed", "stopped"} for t in tasks):
            status, message = "needs_review", "操作已停止，請核對目前結果；不會重送。"
        elif tasks and all(t["status"] == "completed" for t in tasks):
            status = "completed"
            message = "填入已完成。" if item["action"].startswith("fill_") else "操作流程已完成。"
            if item["action"] == "fill_both" and self.app.auto_entry_on_fill_both.isChecked():
                status, message = "needs_review", "流程已結束，但尚未取得完整成交確認，請核對兩側。"
        elif item["action"] in {"warning", "view_sl_tp"}:
            status, message = "completed", "已顯示電腦核對資料。"
        elif item["action"] == "refresh_news":
            status, message = "completed", "已要求背景更新消息，來源完成後會同步顯示。"
        elif item["action"] in {"option", "rule"}:
            widget = self._options().get(item["args"]["key"])
            matched = widget is not None and widget.isChecked() == item["args"]["checked"]
            status, message = ("completed", "交易選項已更新。") if matched else ("not_started", "未變更交易選項。")
        else:
            status, message = "not_started", "操作已結束，沒有新增執行結果；請查看畫面或確認是否已取消。"
        result = dict(message=message[:12000], title=report.get("title", "操作結果") if report else "操作結果")
        result["popup_required"] = status != 'completed' and not item.get("receipt_shown", False)
        self.store.finish(item["device"], item["id"], status, result)
        self.active = None
        self.server.reply(item["device"], {"type": "result", "operation": self.store.latest(item["device"])})
        # Keep ownership of an already displayed result card, but not a later
        # unrelated desktop settings window.
        if self._current_dialog() is None:
            self.dialog_owner = None
            self.dialog = None
            self.consumed_dialog = None
        self.server.publish(self.snapshot())

    def _reject(self, device, identifier, message):
        self.server.reply(device, dict(type="rejected", id=identifier, message=message))

    def _command(self, device: str, payload: dict):
        identifier = payload.get("id")
        if not isinstance(identifier, str) or not re.fullmatch(r"[a-f0-9-]{16,64}", identifier):
            self._reject(device, "", "操作編號無效，請重新連線。")
            return
        try:
            action, args = payload.get("action"), payload.get("args", {})
            if not isinstance(action, str) or not isinstance(args, dict):
                raise ValueError("無法辨識操作。")
            if action in {"dialog", "stop"}:
                self._dialog_command(device, identifier, action, args)
                return
            if action not in ACTIONS | {"draft"}:
                raise ValueError("手機不提供此功能。")
            digest = self.store.digest(json.dumps([action, args], sort_keys=True, ensure_ascii=False))
            previous = self.store.operation(device, identifier)
            if previous:
                if previous["digest"] != digest:
                    raise ValueError("此操作編號已使用，請核對結果。")
                previous.pop("digest")
                self.server.reply(device, {"type": "result", "operation": previous})
                return
            # Read the live desktop before comparing revisions, not just the
            # last periodic snapshot: local edits must never be overwritten.
            self.server.publish(self.snapshot())
            if (type(payload.get("revision")) is not int or payload["revision"] != self.server.revision
                    or payload.get("lease") != self.server.lease
                    or time.monotonic() > self.server.lease_until):
                raise ValueError("電腦資料已更新，請看最新數值後再操作。")
            if (self.active or self._busy() or self._current_dialog() is not None
                    or not interactive_desktop()):
                raise ValueError("電腦正在操作或等待確認，請稍後再試。")
            self._validate(action, args)
            if action == "draft":
                for key, raw in args.items():
                    self.app.parameter_inputs[key].setText(raw)
                self.server.publish(self.snapshot())
                self.server.reply(device, dict(type="ack", id=identifier, status="applied"))
                return
            self.store.begin(device, identifier, action, digest)
            self.active = dict(device=device, id=identifier, action=action, args=args,
                               errors=[], tasks=[], report=None, context=self._decision_context())
            self.dialog_owner = device
            self.dialog = None
            self.consumed_dialog = None
            self.last_busy = time.monotonic()
            self.server.reply(device, dict(type="ack", id=identifier, status="accepted"))
            QTimer.singleShot(0, self._dispatch)
        except (ValueError, TypeError, KeyError) as exc:
            self._reject(device, identifier, str(exc))

    def _decision_context(self):
        state = self.snapshot()
        return json.dumps({
            key: state[key] for key in ("profile", "stage", "direction", "platforms", "values")
        } | {"inputs": {key: (item["raw"], item["value"]) for key, item in state["parameters"].items()},
             "options": {key: item["checked"] for key, item in state["options"].items()}},
            sort_keys=True, ensure_ascii=False)

    def _validate(self, action, args):
        if action == "draft":
            if not args or set(args)-set(FIELDS):
                raise ValueError("交易欄位不正確。")
            for key, value in args.items():
                if (not isinstance(value, str) or len(value) > 64
                        or not re.fullmatch(r"[0-9.,+\-~=%\s]*", value)
                        or not self.app.parameter_inputs[key].isEnabled()):
                    raise ValueError("請輸入有效的交易數值。")
        elif action in {"direction", "stage", "profile"}:
            if set(args) != {"value"} or not isinstance(args["value"], str):
                raise ValueError("選項不正確。")
            allowed = ({"BUY", "SELL"} if action == "direction" else self.app.profiles.names()
                       if action == "profile" else
                       [self.app.stage_selector.itemText(i) for i in range(self.app.stage_selector.count())])
            if args["value"] not in allowed:
                raise ValueError("選項已改變，請重新選擇。")
            if action == "stage" and not self.app.stage_selector.isEnabled():
                raise ValueError("階段尚未載入。")
        elif action in {"option", "rule"}:
            if (set(args) != {"key", "checked"} or type(args["checked"]) is not bool
                    or args["key"] not in self._options()
                    or not self._options()[args["key"]].isEnabled()):
                raise ValueError("此交易選項目前無法調整。")
        elif action == "warning":
            if set(args) != {"key"} or args["key"] not in {"internal_balance", "expected_sl_combined"}:
                raise ValueError("提醒項目不正確。")
        elif args:
            raise ValueError("操作資料不正確。")
        if action.startswith("fill_") and not self.snapshot()["actions"].get(action):
            raise ValueError("目前交易資料尚未就緒。")

    def _dispatch(self):
        item = self.active
        if item is None:
            return
        try:
            app, action, args = self.app, item["action"], item["args"]
            # Recheck immediately before side effects; a local timer may have
            # opened a dialog or begun a task after the command was accepted.
            if self._busy() or QApplication.activeModalWidget() is not None or not interactive_desktop():
                raise ValueError("電腦狀態已改變，本次未執行。")
            if item["context"] != self._decision_context():
                raise ValueError("電腦交易數值已改變，本次未執行；請核對最新數值。")
            if action == "direction":
                app.internal_direction_input.setCurrentIndex(0 if args["value"] == "BUY" else 1)
            elif action == "stage":
                app.stage_selector.setCurrentText(args["value"])
            elif action == "profile":
                app.switch_profile(args["value"])
            elif action in {"option", "rule"}:
                self._options()[args["key"]].setChecked(args["checked"])
            elif action == "update":
                if any(entry.text().strip() for entry in app.parameter_inputs.values()):
                    app.parameter_update_button.click()
                else:
                    app.read_sheet()
            elif action == "warning":
                (app._show_balance_warning if args["key"] == "internal_balance"
                 else app._show_expected_sl_warning)()
            elif action == "refresh_news":
                app._get_event_calendar().refresh()
            else:
                {"fill_both": app.fill_both, "fill_internal": lambda: app.fill_role("internal"),
                 "fill_external": lambda: app.fill_role("external"), "sync": app.sync_external_sl_tp,
                 "view_sl_tp": app.show_internal_external_sl_tp}[action]()
        except Exception as exc:
            item["errors"].append(str(exc))
        self.last_busy = time.monotonic()
        self.tick()

    def _dialog_command(self, device, identifier, action, args):
        if self.dialog_owner != device:
            raise ValueError("這不是此手機發起的操作。")
        if action == "stop":
            if not self.active or args:
                raise ValueError("目前沒有此手機可停止的操作。")
            self.app.emergency.stop()
        else:
            descriptor = self._dialog_snapshot()
            if (not descriptor or args.get("dialog") != self.dialog_id
                    or not self.dialog_id or self.dialog is self.consumed_dialog
                    or set(args)-{"dialog", "button", "checks"} or descriptor["desktop_required"]):
                raise ValueError("確認畫面已改變，請查看最新提示。")
            button = self.dialog_widgets.get(args.get("button"))
            checks = args.get("checks", {})
            if not isinstance(button, QPushButton) or not button.isVisible() or not button.isEnabled():
                raise ValueError("此按鈕目前無法操作。")
            if not isinstance(checks, dict):
                raise ValueError("確認選項不正確。")
            for key, value in checks.items():
                checkbox = self.dialog_widgets.get(key)
                if not isinstance(checkbox, QCheckBox) or type(value) is not bool or not checkbox.isEnabled():
                    raise ValueError("確認選項已改變。")
            for key, value in checks.items():
                self.dialog_widgets[key].setChecked(value)
            # Disable before posting the click, preventing a double tap from
            # reusing the old dialog/button while its nested loop unwinds.
            self.dialog_widgets = {}
            self.dialog_id = ""
            self.consumed_dialog = self.dialog
            QTimer.singleShot(0, button.click)
        self.server.reply(device, dict(type="ack", id=identifier, status="accepted"))

    def show_settings(self):
        from .gui import QMessageBox
        from .window_chrome import ThemedDialog
        from .ui_theme import themed_icon
        from PySide6.QtWidgets import (QGroupBox, QHBoxLayout, QListWidget, QVBoxLayout,
                                      QScrollArea, QWidget, QSizePolicy)
        from PySide6.QtCore import Qt
        if self.settings_dialog is not None:
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        dialog = ThemedDialog(self.app)
        self.settings_dialog = dialog
        dialog.setWindowModality(Qt.NonModal)
        dialog.setWindowTitle("手機連線")
        dialog.resize(520, 540)
        root = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(body)
        root.addWidget(scroll)
        note = QLabel("第一次掃碼並輸入配對碼，之後從手機桌面圖示開啟。\n長期使用請設定固定入口；臨時網址重開後會變更。")
        note.setWordWrap(True)
        layout.addWidget(note)
        quick = QPushButton('啟用手機連線（臨時網址）')
        layout.addWidget(quick)
        phone_url = QLineEdit()
        phone_url.setReadOnly(True)
        phone_url.setPlaceholderText('啟用後顯示手機可開啟的網址')
        layout.addWidget(phone_url)
        qr_toggle = QPushButton('顯示 QR Code')
        qr_toggle.setObjectName('phoneQrToggle')
        qr_toggle.setCheckable(True)
        layout.addWidget(qr_toggle)
        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        qr.setFixedHeight(220)
        qr.setStyleSheet('QLabel { background: transparent; border: none; }')
        qr.setVisible(False)
        layout.addWidget(qr)
        def fit():
            if self.settings_dialog is not dialog:
                return
            layout.activate()
            root.activate()
            available = dialog.screen().availableGeometry()
            # Content owns its natural height; the device list never absorbs
            # the space left by a hidden QR. Scroll only on shorter screens.
            height = body.sizeHint().height()+root.contentsMargins().top()+root.contentsMargins().bottom()+root.spacing()+close.sizeHint().height()+dialog.title_bar.height()+8
            dialog.resize(dialog.width(), min(height, available.height()-24))
            if dialog.frameGeometry().bottom() > available.bottom():
                dialog.move(dialog.x(), max(available.top(), available.bottom()-dialog.height()))

        def show_qr(visible):
            qr.setVisible(visible)
            qr_toggle.setText('收起 QR Code' if visible else '顯示 QR Code')
            QTimer.singleShot(0, fit)
        qr_toggle.toggled.connect(show_qr)
        status = QLabel()
        status.setWordWrap(True)
        status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(status)
        fixed_toggle = QPushButton('設定固定入口 ▾')
        fixed_toggle.setCheckable(True)
        layout.addWidget(fixed_toggle)
        fixed_group = QGroupBox('固定入口：不用購買網域')
        fixed_group.setVisible(False)
        fixed_layout = QVBoxLayout(fixed_group)
        fixed_note = QLabel('電腦安裝 Tailscale 並登入一次，再按「建立固定入口」。\n手機不用安裝 Tailscale；首次會要求你同意開啟連線。')
        fixed_note.setWordWrap(True)
        fixed_layout.addWidget(fixed_note)
        fixed_row = QHBoxLayout()
        download = QPushButton('安裝與登入說明')
        fixed_start = QPushButton('建立固定入口')
        fixed_row.addWidget(download)
        fixed_row.addWidget(fixed_start)
        fixed_layout.addLayout(fixed_row)
        approval = QPushButton('允許固定入口')
        approval.setVisible(False)
        fixed_layout.addWidget(approval)
        layout.addWidget(fixed_group)
        fixed_toggle.toggled.connect(fixed_group.setVisible)
        fixed_toggle.toggled.connect(lambda _: QTimer.singleShot(0, fit))
        advanced_toggle = QPushButton('其他連線設定 ▾')
        advanced_toggle.setCheckable(True)
        layout.addWidget(advanced_toggle)
        advanced = QGroupBox('固定網址（需先設定連線服務）')
        advanced.setVisible(False)
        advanced_toggle.toggled.connect(advanced.setVisible)
        advanced_toggle.toggled.connect(lambda _: QTimer.singleShot(0, fit))
        advanced_layout = QVBoxLayout(advanced)
        origin = QLineEdit(self.store.setting("origin"))
        origin.setPlaceholderText('已設定轉送的固定 HTTPS 網址；本機預覽可留空')
        advanced_layout.addWidget(origin)
        row = QHBoxLayout()
        toggle = QPushButton("停止連線" if self.server.http.isListening() else "啟用連線")
        preview = QPushButton("電腦預覽")
        preview.setToolTip('只在這台電腦檢查手機版面；手機請使用上方網址或 QR Code。')
        for button in (toggle, preview):
            row.addWidget(button)
        advanced_layout.addLayout(row)
        layout.addWidget(advanced)
        code_row = QHBoxLayout()
        code = QLabel()
        code.setObjectName('phonePairCode')
        code.setWordWrap(True)
        pair = QPushButton()
        pair.setIcon(themed_icon('refresh'))
        pair.setFixedSize(32, 32)
        pair.setToolTip('重新產生配對碼')
        pair.setAccessibleName('重新產生配對碼')
        code_row.addWidget(code, 1)
        code_row.addWidget(pair)
        layout.addLayout(code_row)
        layout.addWidget(QLabel('已配對裝置'))
        devices = QListWidget()
        devices.setFixedHeight(80)
        devices.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        layout.addWidget(devices)
        revoke = QPushButton("移除選取的手機")
        layout.addWidget(revoke)
        close = QPushButton("關閉")
        root.addWidget(close)

        def update_code():
            remaining = max(0, math.ceil(self.server.pair_until-time.monotonic()))
            if self.server.pair_code and self.server.pair_attempts > 5:
                code.setText('配對碼已停用，請按 ↻ 重新產生。')
            elif self.server.pair_code and remaining:
                code.setText(f'配對碼：{self.server.pair_code}　{remaining//60:02d}:{remaining%60:02d}')
            elif self.server.pair_code:
                code.setText('配對碼已過期，請按 ↻ 重新產生。')
            else:
                code.setText('新手機請按右側重整取得配對碼；已配對手機可直接連線。')

        def refresh():
            listening = self.server.http.isListening()
            toggle.setText("停止連線" if listening else "啟用連線")
            ready = listening and (not self.temporary_connection or self.tunnel.connected) and (not self.fixed_tunnel.running or self.fixed_tunnel.connected)
            quick.setText('停止手機連線' if listening else '啟用手機連線（臨時網址）')
            fixed_start.setEnabled(not self.fixed_tunnel.running)
            approval.setVisible(bool(self.fixed_tunnel.approval_url))
            pair.setEnabled(ready)
            preview.setEnabled(listening)
            origin.setEnabled(not listening)
            phone_url.setText(self.server.public_origin if ready else '')
            qr_toggle.setEnabled(bool(phone_url.text()))
            if phone_url.text() and qr.property('origin') != phone_url.text():
                from .remote_qr import phone_qr_image
                from PySide6.QtGui import QPixmap
                try:
                    qr.setPixmap(QPixmap.fromImage(phone_qr_image(phone_url.text())))
                    qr.setProperty('origin', phone_url.text())
                except (ImportError, AttributeError, ValueError):
                    qr.setText('QR Code 無法顯示，請在手機開啟上方網址。')
            elif not phone_url.text():
                qr.clear()
                qr.setProperty('origin', '')
            status.setText(('已準備好，請用手機掃碼。' + ('（臨時網址）' if self.temporary_connection else '（固定網址）')) if ready and self.server.public_origin else
                           (self.fixed_tunnel.message if self.fixed_tunnel.running or self.store.setting('provider') == 'tailscale' else self.tunnel.message if not listening or self.temporary_connection else '僅限電腦預覽，手機尚不能連線。'))
            update_code()
            selected = devices.currentItem().data(Qt.UserRole) if devices.currentItem() else None
            devices.clear()
            for device in self.store.devices():
                devices.addItem(device["name"])
                item = devices.item(devices.count()-1)
                item.setData(Qt.UserRole, device['id'])
                if device['id'] == selected:
                    devices.setCurrentItem(item)
        def toggle_server():
            try:
                if self.server.http.isListening():
                    self.stop()
                    self.store.set_setting("enabled", "0")
                else:
                    self.start(origin.text().strip())
                    self.store.set_setting('provider', 'manual')
                    self.store.set_setting("origin", self.server.public_origin)
                    self.store.set_setting("enabled", "1")
                refresh()
            except ValueError as exc:
                QMessageBox.warning(dialog, "手機連線", str(exc))
        def arm():
            self.server.arm_pairing()
            update_code()
        def toggle_temporary():
            try:
                if self.server.http.isListening():
                    self.stop()
                    self.store.set_setting('enabled', '0')
                else:
                    self.start_temporary()
                refresh()
            except ValueError as exc:
                QMessageBox.warning(dialog, '手機連線', str(exc))
        def remove():
            entries = self.store.devices()
            index = devices.currentRow()
            if 0 <= index < len(entries):
                self.store.revoke(entries[index]["id"])
                self.server.publish(self.snapshot())
                refresh()
        def open_preview():
            import webbrowser
            webbrowser.open(self.server.local_origin)
        def start_fixed():
            try:
                self.start_fixed()
            except ValueError as exc:
                QMessageBox.warning(dialog, '固定手機入口', str(exc))
            refresh()
        toggle.clicked.connect(toggle_server)
        quick.clicked.connect(toggle_temporary)
        download.clicked.connect(lambda: __import__('webbrowser').open('https://tailscale.com/download/windows'))
        approval.clicked.connect(lambda: __import__('webbrowser').open(self.fixed_tunnel.approval_url) if self.fixed_tunnel.approval_url else None)
        fixed_start.clicked.connect(start_fixed)
        pair.clicked.connect(arm)
        revoke.clicked.connect(remove)
        preview.clicked.connect(open_preview)
        close.clicked.connect(dialog.accept)
        self.server.changed.connect(refresh)
        self.tunnel.changed.connect(refresh)
        self.fixed_tunnel.changed.connect(refresh)
        countdown = QTimer(dialog)
        countdown.setInterval(1000)
        countdown.timeout.connect(update_code)
        countdown.start()
        refresh()
        dialog.install_chrome()
        def cleanup():
            self.server.changed.disconnect(refresh)
            self.tunnel.changed.disconnect(refresh)
            self.fixed_tunnel.changed.disconnect(refresh)
            countdown.stop()
            self.settings_dialog = None
            dialog.deleteLater()
        dialog.finished.connect(cleanup)
        dialog.show()
        QTimer.singleShot(0, fit)
