"""Mobile adapter: share the desktop widgets/callbacks, never broker logic."""
from __future__ import annotations

import ctypes
import json
import os
import re
import time
import math
from dataclasses import asdict

from PySide6.QtCore import QObject, QSignalBlocker, QTimer, Qt, QSize
from PySide6.QtWidgets import QApplication, QCheckBox, QLabel, QLineEdit, QListWidget, QPushButton, QTextBrowser

from .remote_control import MobileServer, RemoteStore
from .remote_mobile import ASSETS
from .remote_tunnel import QuickTunnel, FixedTunnel

FIELDS = ("internal_balance", "daily_pnl", "expected_sl_combined", "internal_entry_price")
ACTIONS = {"direction", "stage", "profile", "update", "fill_both", "fill_internal",
           "fill_external", "sync", "view_sl_tp", "rule", "option", "warning", "refresh_news",
           "close_both", "read_balance", "rest_settings", "live_profile"}


class DeviceList(QListWidget):
    """Single selection with a second click to deselect the same phone."""

    def mousePressEvent(self, event):
        item = self.itemAt(event.position().toPoint())
        if event.button() == Qt.LeftButton and (item is None or item.isSelected()):
            self.clearSelection()
            self.setCurrentRow(-1)
            event.accept()
            return
        super().mousePressEvent(event)


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
        # Phone progress card for 「填入兩邊」 (display only).
        self._fill_steps = None
        from . import fill_progress
        fill_progress.add_listener(self._fill_step)
        QApplication.instance().aboutToQuit.connect(self.stop)
        self.settings_dialog = None
        # Computer-rendered PiP video (see pip_stream); idle unless a phone plays it.
        from .pip_stream import PipStream, FPS
        self.pip_stream = PipStream(self._render_pip_frame)
        self.server.pip_stream = self.pip_stream
        self._pip_bar = None
        self.pip_timer = QTimer(self)
        self.pip_timer.setInterval(1000 // FPS)
        self.pip_timer.timeout.connect(self._pip_tick)
        self.pip_timer.start()

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
        self.pip_stream.stop()
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
        self.server.notifications.poll(getattr(self.app, '_event_calendar', None), self.server.public_origin)
        for sock in list(self.server.sockets):
            self.server.send(sock, {"type": "heartbeat", "time": time.time()})

    def _busy(self):
        app = self.app
        return bool(app._active_tasks or app._parameter_write_active or app._parameter_write_pending
                    or app._trade_settings_busy or app._update_in_progress or app._fill_waiting_for_sheet)

    def _status(self, text):
        self.phase = text

    def _fill_step(self, step):
        # Called from the worker thread: only records a finished step.
        steps = self._fill_steps
        if steps is not None:
            self._fill_steps = dict(steps, done=steps["done"] | {step})

    def _fill_progress(self):
        steps = self._fill_steps
        if not (self.active and self.active.get("action") == "fill_both" and steps):
            return None
        order = [("form_internal", "場內填寫"), ("form_external", "場外填寫")]
        if steps["entry"]:
            order += [("entered_internal", "場內進場"), ("entered_external", "場外進場")]
            if steps["sync"]:
                order.append(("synced", "同步場外 SL／TP"))
        return [{"label": label, "done": key in steps["done"]} for key, label in order]

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
            if isinstance(widget, QPushButton):
                item["default"] = bool(widget.isDefault())
                # The computer colours the action (accept) button; the phone
                # highlights that same button instead of the focused default.
                item["accept"] = widget.property("messageRole") == "accept"
                item["danger"] = widget.property("danger") is True
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
        # The news list is the costly part and this runs every 0.15 s on the
        # GUI thread (it made the spinner and dragging stutter). Rebuild it
        # only when the calendar changed, or every 5 s for the time window.
        news_key = None
        if calendar is not None:
            items = getattr(calendar, "news", None) or []
            news_key = (id(calendar), len(items), id(items[0]) if items else None,
                        len(getattr(calendar, "events", None) or ()), int(time.monotonic() // 5))
        cached = getattr(self, "_news_cache", None)
        news = cached[1] if cached is not None and cached[0] == news_key else []
        if calendar is not None and (cached is None or cached[0] != news_key):
            from datetime import datetime, timedelta, timezone
            from .calendar_events import publication_values, events_for_display
            from .news_relevance import assess_headline, KEYWORDS
            def news_item(event, scheduled):
                title = calendar.title(event.title)
                assessment = assess_headline(event.title, scheduled=scheduled)
                parts, end = [], 0
                for match in KEYWORDS.finditer(title):
                    parts.extend(((title[end:match.start()],False),(match.group(),True)))
                    end = match.end()
                parts.append((title[end:],False))
                return dict(when=event.when.isoformat(), title=title, original=event.title, source=event.source,
                    scheduled=scheduled, details=event.details, local_rest=event.source == '休市提醒',
                    category='休市提醒' if event.source == '休市提醒' else assessment.category,
                    color='#aaa5b7' if event.source == '休市提醒' else assessment.color, parts=parts,
                    values=publication_values(event.details) if scheduled else {})
            recent = datetime.now(timezone.utc)-timedelta(days=1)
            for event in sorted(event for event in events_for_display(calendar, datetime.now(timezone.utc))
                                if recent <= event.when <= datetime.now(timezone.utc)+timedelta(days=45))[:60]:
                news.append(news_item(event, True))
            recent = datetime.now(timezone.utc)-timedelta(days=7)  # published news: one week
            for event in calendar.news[:150]:
                from .news_relevance import assess_headline
                from .event_summary import relevant_announcement
                if not recent <= event.when <= datetime.now(timezone.utc) or not relevant_announcement(event.title):
                    continue
                news.append(news_item(event, False))
            self._news_cache = (news_key, news)
        # 「已達到獲利目標」 etc.: the "!" sits on 每日獲利/虧損 (same as desktop).
        pnl_warning = app._balance_warning_active() and app._pnl_warning(app._balance_range_warning_detail())
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
            warnings={"internal_balance": app._balance_warning_active() and not pnl_warning,
                      "daily_pnl": pnl_warning,
                      "expected_sl_combined": app._expected_sl_warning_values() is not None},
            actions={"fill_both": available and app.action_buttons["填入兩邊"].isEnabled(),
                     "fill_internal": available and app.action_buttons["填入場內"].isEnabled(),
                     "fill_external": available and app.action_buttons["填入場外"].isEnabled(),
                     "update": available, "sync": available, "view_sl_tp": available,
                     "close_both": available,
                     "read_balance": available and app.internal_platform.currentText() in ("cTrader", "MT5")
                     and not getattr(app, "_balance_read_running", False)},
            balance_ready=getattr(app, "_balance_button_state", "") == "ready",
            rest_settings=self._rest_settings(),
            available=available, busy=busy or bool(self.active),
            health="無法操作" if not self._desktop_ok else "執行中" if busy or self.active else
                   f"請先處理電腦上的「{modal.windowTitle() or '確認'}」視窗" if modal and modal is not self.dialog else
                   "請確認下方提示" if modal else "請調整場內餘額" if app._balance_warning_active()
                   else "等待交易資料" if app.instruction is None else "正常",
            phase=self.phase, dialog=self._dialog_snapshot(), news=news,
            fill_progress=self._fill_progress(),
            # Same as the side panel's 目前持倉: may be another 方案 with a position.
            live_pnl=(getattr(app, "live_pnl_payload", None) or {}).get("state"),
            live_profile=(getattr(app, "live_pnl_payload", None) or {}).get("profile") or app.profiles.active_name,
            live_choices=list((getattr(app, "live_pnl_payload", None) or {}).get("choices") or []),
            live_closed=app.shown_after_close_card() if hasattr(app, "shown_after_close_card") else None,
            news_error=calendar.error if calendar else "消息尚未載入",
            pip_stream=self.pip_stream.path,
        )

    def _pip_tick(self):
        # Keep the stream warm while a phone page is open so PiP starts at once.
        if self.server.sockets and self.pip_stream.available:
            self.pip_stream.last_request = time.monotonic()
            if not self.pip_stream.running:
                self.pip_stream.start()
        self.pip_stream.tick()

    def _render_pip_frame(self) -> bytes:
        """目前持倉 for the phone PiP: title, 方案, time, then the side panel's bar."""
        from datetime import datetime
        from PySide6.QtCore import QPoint, QRectF
        from PySide6.QtGui import QColor, QFont, QImage, QPainter, QRegion
        from PySide6.QtWidgets import QWidget
        from .live_pnl_view import FONT, LivePnlBar, MUTED
        from .pip_stream import HEIGHT, WIDTH
        app = self.app
        payload = getattr(app, "live_pnl_payload", None) or {}
        if self._pip_bar is None:
            self._pip_bar = LivePnlBar()
            self._pip_bar.resize(332, 150)
        bar = self._pip_bar
        bar.set_state(payload.get("state"))
        bar.set_closed(app.shown_after_close_card() if hasattr(app, "shown_after_close_card") else None)
        image = QImage(WIDTH, HEIGHT, QImage.Format_ARGB32)
        image.fill(QColor("#09090c"))
        p = QPainter(image)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.TextAntialiasing)
        k = WIDTH / 360
        p.scale(k, k)

        def text(rect, value, color, size, bold=False, align=Qt.AlignVCenter | Qt.AlignLeft):
            font = QFont(FONT)
            font.setPixelSize(size)
            font.setBold(bold)
            p.setFont(font)
            p.setPen(QColor(color))
            p.drawText(rect, align, value)

        # Header on one baseline: 更新 time (left) and 方案 (right) in the same colour,
        # inset from the corners because a small PiP window rounds/crops them.
        from PySide6.QtCore import QPointF
        from PySide6.QtGui import QFontMetricsF

        def line(x, value, color, size, bold=False, anchor="left", baseline=23):
            font = QFont(FONT)
            font.setPixelSize(size)
            font.setBold(bold)
            p.setFont(font)
            p.setPen(QColor(color))
            width = QFontMetricsF(font).horizontalAdvance(value)
            left = x - width if anchor == "right" else x - width / 2 if anchor == "center" else x
            p.drawText(QPointF(left, baseline), value)
            return width

        stamp = line(34, datetime.now().strftime("%H:%M:%S"), "#b8a8d5", 11)
        if getattr(self.server, "pip_silent", False):
            line(34 + stamp + 3, "鎖定不更新", MUTED, 5)  # small, right after the time
        line(180, "目前持倉", "#ece8f4", 13, True, "center")
        line(326, payload.get("profile") or app.profiles.active_name or "", "#b8a8d5", 11, anchor="right")
        p.translate(14, 36)
        bar.render(p, QPoint(0, 0), QRegion(), QWidget.RenderFlag.DrawChildren)
        p.end()
        return bytes(image.constBits())[:WIDTH * HEIGHT * 4]

    def _rest_settings(self):
        from .gui import rest_close_minutes
        from .rest_reminders import normalize_settings
        ui = self.app.store.data.get("ui", {})
        try:
            reminder = normalize_settings(ui.get("rest_reminder", {}))
        except ValueError:
            reminder = {"enabled": False, "minutes": [60, 30], "custom": False}
        scope = ui.get("rest_close_all", {})
        from datetime import datetime, timedelta, timezone
        from .calendar_events import format_event_time
        from .gui import next_rest_close_time
        from .rest_reminders import rest_occurrences
        now = datetime.now(timezone.utc)
        taipei = timezone(timedelta(hours=8))
        rest = next((t for t in rest_occurrences({"enabled": True}, now) if t > now), None)
        next_rest = (f"下次黃金例行休市：{rest.astimezone(taipei):%m/%d} {format_event_time(rest)}（台北）"
                     if rest else "")
        # Same wording as the computer's 休市平倉設定.
        when = next_rest_close_time(self.app.store.data, now)
        if ui.get("rest_close_enabled") is not True:
            next_close = "這個方案沒有開休市平倉（主畫面勾選後才會執行）"
        else:
            next_close = ("這個方案下次約 " + when.astimezone(taipei).strftime("%m/%d %H:%M") + " 執行（台北時間）"
                          if when else "下次執行時間：無")
        schedule_rows = getattr(self.app, "rest_close_schedule", lambda: [])()
        schedule = ("有開休市平倉的方案（依執行順序）：\n" + "\n".join(
            f"{i}. {name}：{at.astimezone(taipei):%m/%d %H:%M}（休市前 {minutes} 分鐘）"
            for i, (at, name, minutes) in enumerate(schedule_rows, 1))
            + "\n不管目前開哪個方案，以上都會執行。") if schedule_rows else "目前沒有方案開啟休市平倉。"
        return {"reminder": {"enabled": reminder["enabled"], "minutes": reminder["minutes"],
                             "custom": reminder["custom"], "next": next_rest},
                "close": {"minutes": rest_close_minutes(self.app.store.data),
                          "internal": scope.get("internal") is True,
                          "external": scope.get("external") is True,
                          "next": next_close, "schedule": schedule}}

    @staticmethod
    def _clean_rest_settings(args):
        """Phone 休市提醒 (消息 page) and/or 休市平倉 (gear): either part alone."""
        from .gui import REST_CLOSE_CUSTOM_RANGE
        from .rest_reminders import normalize_settings
        if (not args or not set(args) <= {"reminder", "close"}
                or not all(isinstance(args[k], dict) for k in args)):
            raise ValueError("休市設定格式不正確。")
        reminder = close = None
        if "reminder" in args:
            if not set(args["reminder"]) <= {"enabled", "minutes", "custom"}:
                raise ValueError("休市提醒格式不正確。")
            reminder = normalize_settings(args["reminder"])
        if "close" in args:
            close = args["close"]
            low, high = REST_CLOSE_CUSTOM_RANGE
            if (set(close) != {"minutes", "internal", "external"} or type(close["minutes"]) is not int
                    or not low <= close["minutes"] <= high
                    or type(close["internal"]) is not bool or type(close["external"]) is not bool):
                raise ValueError(f"休市平倉時間請填 {low}–{high} 分鐘。")
        return reminder, close

    def _apply_rest_settings(self, args):
        reminder, close = self._clean_rest_settings(args)
        app = self.app
        ui = app.store.data.setdefault("ui", {})
        previous = {key: ui.get(key) for key in ("rest_reminder", "rest_close_minutes", "rest_close_all")}
        if reminder is not None:
            ui["rest_reminder"] = reminder
        if close is not None:
            ui["rest_close_minutes"] = close["minutes"]
            ui["rest_close_all"] = {"internal": close["internal"], "external": close["external"]}
        try:
            app.save_config()
        except OSError:
            for key, value in previous.items():
                if value is None:
                    ui.pop(key, None)
                else:
                    ui[key] = value
            raise ValueError("休市設定未儲存，請重試。")
        calendar = app._get_event_calendar()
        calendar.changed.emit()
        calendar._check_reminders()
        if reminder is not None:
            # Show the phone's change in the computer's 休市提醒 panel too.
            from .rest_reminder_settings import RestReminderSettings
            for editor in QApplication.allWidgets():
                if isinstance(editor, RestReminderSettings):
                    editor.load()

    def _options(self):
        app = self.app
        return {"auto_entry": app.auto_entry_on_fill_both,
                "auto_sync": app.auto_sync_sl_tp_after_entry,
                "auto_sl": app.auto_adjust_repeat_sl,
                **{"rule:"+key: value for key, value in app.trade_rule_checkboxes.items()},
                "rest_close": app.rest_close_checkbox}

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
        elif item["action"] == "rest_settings":
            status, message = "completed", "休市設定已儲存。"
        elif item["action"] == "live_profile":
            status, message = "completed", "已切換顯示的持倉方案。"
        elif item["action"] == "read_balance":
            status, message = "completed", "已讀取場內餘額。"
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
            if action == "fill_both":
                sync = getattr(self.app, "auto_sync_sl_tp_after_entry", None)
                entry = self.app.auto_entry_on_fill_both.isChecked()
                self._fill_steps = {"done": frozenset(), "entry": entry,
                                    "sync": entry and (sync is None or sync.isChecked())}
            else:
                self._fill_steps = None
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
        elif action == "rest_settings":
            self._clean_rest_settings(args)
        elif action == "live_profile":
            choices = (getattr(self.app, "live_pnl_payload", None) or {}).get("choices") or []
            if set(args) != {"name"} or args["name"] not in choices:
                raise ValueError("這個方案目前沒有持倉。")
        elif action == "warning":
            if set(args) != {"key"} or args["key"] not in {"internal_balance", "daily_pnl", "expected_sl_combined"}:
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
                if getattr(app, "_balance_button_state", "") == "ready":
                    app._set_balance_button_state("idle")
                if any(entry.text().strip() for entry in app.parameter_inputs.values()):
                    app.parameter_update_button.click()
                else:
                    app.read_sheet()
            elif action == "warning":
                (app._show_balance_warning if args["key"] in ("internal_balance", "daily_pnl")
                 else app._show_expected_sl_warning)()
            elif action == "refresh_news":
                app._get_event_calendar().refresh()
            elif action == "rest_settings":
                self._apply_rest_settings(args)
            elif action == "live_profile":
                app.set_live_preference(args["name"])
            else:
                {"fill_both": app.fill_both, "fill_internal": lambda: app.fill_role("internal"),
                 "fill_external": lambda: app.fill_role("external"), "sync": app.sync_external_sl_tp,
                 "close_both": app.close_both_sides,
                 "read_balance": lambda: app.read_internal_balance("phone"),
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
        import webbrowser
        from .gui import QMessageBox
        from .window_chrome import ThemedDialog
        from .ui_theme import themed_icon, DIALOG_THEME
        from PySide6.QtWidgets import QGroupBox, QHBoxLayout, QListWidget, QVBoxLayout, QScrollArea, QWidget
        from PySide6.QtCore import Qt
        if self.settings_dialog is not None:
            self.settings_dialog.show()
            self.settings_dialog.raise_()
            self.settings_dialog.activateWindow()
            return
        dialog = ThemedDialog(self.app)
        dialog.setStyleSheet(DIALOG_THEME)
        self.settings_dialog = dialog
        dialog.setWindowModality(Qt.NonModal)
        dialog.setWindowTitle('手機連線')
        dialog.resize(520, 540)
        root = QVBoxLayout(dialog)
        scroll = QScrollArea()
        scroll.setObjectName('phoneSettingsScroll')
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        body = QWidget()
        body.setObjectName('phoneSettingsBody')
        body.setAttribute(Qt.WA_StyledBackground, True)
        layout = QVBoxLayout(body)
        layout.setContentsMargins(0, 0, 0, 0)
        scroll.setWidget(body)
        root.addWidget(scroll)
        note = QLabel('首次掃碼並配對；之後從手機桌面圖示直接連線。')
        note.setWordWrap(True)
        layout.addWidget(note)
        fixed_group = QGroupBox('固定手機入口')
        fixed_group.setObjectName('phoneFixedSetup')
        fixed_layout = QVBoxLayout(fixed_group)
        guide = QLabel('① 電腦安裝 Tailscale 並登入，完成後可關閉它的視窗。\n② 按「建立固定入口」，依提示允許；手機不用安裝 Tailscale。\nTailscale 需在背景執行，請勿登出或結束其服務。')
        guide.setWordWrap(True)
        fixed_layout.addWidget(guide)
        row = QHBoxLayout()
        download = QPushButton('安裝與登入')
        fixed_start = QPushButton('建立固定入口')
        row.addWidget(download)
        row.addWidget(fixed_start)
        fixed_layout.addLayout(row)
        approval = QPushButton('允許固定入口')
        approval.hide()
        fixed_layout.addWidget(approval)
        stop = QPushButton('停止手機連線')
        stop.setObjectName('phoneStop')
        stop.setToolTip('中斷手機連線；不會平倉或撤回已送出的操作。')
        fixed_layout.addWidget(stop)
        layout.addWidget(fixed_group)
        status = QLabel()
        status.setWordWrap(True)
        status.setTextInteractionFlags(Qt.TextSelectableByMouse)
        layout.addWidget(status)
        waiting = QLabel('第一次啟用若無法建立安全連線，請等幾分鐘再開啟；網址生效可能需約 10 分鐘。')
        waiting.setWordWrap(True)
        layout.addWidget(waiting)
        phone_url = QLineEdit()
        phone_url.setReadOnly(True)
        phone_url.setPlaceholderText('建立入口後顯示固定手機網址')
        layout.addWidget(phone_url)
        qr_toggle = QPushButton('顯示 QR Code ▾')
        qr_toggle.setObjectName('phoneQrToggle')
        qr_toggle.setCheckable(True)
        qr_toggle.setStyleSheet('QPushButton:checked { background: #292531; border-color: #74658f; }')
        layout.addWidget(qr_toggle)
        qr = QLabel()
        qr.setAlignment(Qt.AlignCenter)
        qr.setFixedHeight(236)
        qr.hide()
        layout.addWidget(qr)
        code_row = QHBoxLayout()
        code = QLabel()
        code.setObjectName('phonePairCode')
        code.setWordWrap(True)
        countdown_text = QLabel()
        countdown_text.setObjectName('phonePairCountdown')
        countdown_text.setMinimumWidth(42)
        countdown_text.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        pair = QPushButton()
        pair.setIcon(themed_icon('refresh'))
        pair.setFixedSize(32, 32)
        pair.setToolTip('重新產生配對碼')
        pair.setAccessibleName('重新產生配對碼')
        code_row.addWidget(code, 1)
        code_row.addWidget(countdown_text)
        code_row.addWidget(pair)
        layout.addLayout(code_row)
        layout.addWidget(QLabel('已配對裝置'))
        devices = DeviceList()
        devices.setObjectName('pairedDevices')
        devices.setFixedHeight(80)
        # Fill the whole box in the dialog's colours; rows are full width with
        # a clear (not system-blue) selection instead of a grey empty area.
        devices.setStyleSheet(
            'QListWidget#pairedDevices { background: #131218; border: 1px solid #34303d;'
            ' border-radius: 8px; padding: 4px; outline: 0; }'
            'QListWidget#pairedDevices::item { padding: 0; border: 0; border-radius: 6px;'
            ' color: #e9e7ef; }'
            'QListWidget#pairedDevices::item:hover:!selected { background: #1d1b24; }'
            'QListWidget#pairedDevices::item:selected { background: #2d2738; color: #ffffff; }'
        )
        layout.addWidget(devices)
        test_push = QPushButton('傳送測試通知到手機')
        test_push.setObjectName('phoneTestNotification')
        test_push.setToolTip('傳一則測試通知給已開啟通知的手機；不含任何交易資料。')
        layout.addWidget(test_push)

        def send_test_notification():
            origin = self.server.public_origin
            if not origin:
                QMessageBox.information(dialog, '測試通知', '請先建立固定入口。')
                return
            sent, waiting, errors = 0, 0, []
            for device in self.store.devices():
                try:
                    if not self.server.notifications.subscribed(device['id'], origin):
                        continue
                    result = self.server.notifications.test(device['id'], origin)
                    if result.get('queued', True):
                        sent += 1
                    else:
                        waiting += 1
                except Exception as exc:  # show why instead of failing silently
                    errors.append(f"{device['name']}：{exc}")
            if errors:
                QMessageBox.warning(dialog, '測試通知', '傳送失敗：\n' + '\n'.join(errors))
            elif sent:
                QMessageBox.information(dialog, '測試通知', f'已傳送給 {sent} 支手機，幾秒內應該會收到。')
            elif waiting:
                QMessageBox.information(dialog, '測試通知', '剛剛才傳過，請等 10 秒後再試。')
            else:
                QMessageBox.information(dialog, '測試通知',
                                        '沒有已開啟通知的手機。請在手機頁面開啟通知後再試。')
        test_push.clicked.connect(send_test_notification)

        def fit():
            if self.settings_dialog is not dialog:
                return
            layout.activate()
            root.activate()
            area = dialog.screen().availableGeometry()
            height = body.sizeHint().height()+root.contentsMargins().top()+root.contentsMargins().bottom()+dialog.title_bar.height()+8
            dialog.resize(dialog.width(), min(height, area.height()-24))
            if dialog.frameGeometry().bottom() > area.bottom():
                dialog.move(dialog.x(), max(area.top(), area.bottom()-dialog.height()+1))

        def show_qr(visible):
            qr.setVisible(visible)
            qr_toggle.setText('收起 QR Code ▴' if visible else '顯示 QR Code ▾')
            QTimer.singleShot(0, fit)
        qr_toggle.toggled.connect(show_qr)

        def update_code():
            remaining = max(0, math.ceil(self.server.pair_until-time.monotonic()))
            countdown_text.setText('')
            if not self.server.http.isListening():
                code.setText('建立入口後，可在此產生一次性配對碼。')
            elif self.server.pair_code and self.server.pair_attempts > 5:
                code.setText('配對碼已停用，請按右側重整。')
            elif self.server.pair_code and remaining:
                code.setText('配對碼：'+self.server.pair_code)
                countdown_text.setText(f'{remaining//60:02d}:{remaining%60:02d}')
            elif self.server.pair_code:
                code.setText('配對碼已過期，請按右側重整。')
            else:
                code.setText('新手機請按右側重整；已配對手機可直接連線。')

        def selection_changed():
            # The list's own ::item:selected style paints the row; the row
            # widget stays transparent so the colour fills the whole width.
            for index in range(devices.count()):
                item = devices.item(index)
                row = devices.itemWidget(item)
                if row is not None:
                    row.findChild(QPushButton, 'phoneRevoke').setVisible(item.isSelected())
        devices.itemSelectionChanged.connect(selection_changed)

        def refresh():
            listening = self.server.http.isListening()
            ready = listening and bool(self.server.public_origin) and (not self.fixed_tunnel.running or self.fixed_tunnel.connected)
            fixed_start.setEnabled(not listening)
            fixed_start.setText('固定入口已啟用' if ready else '正在建立入口…' if self.fixed_tunnel.running else '建立固定入口')
            stop.setEnabled(listening)
            approval.setVisible(bool(self.fixed_tunnel.approval_url))
            pair.setEnabled(ready)
            phone_url.setText(self.server.public_origin if ready else '')
            qr_toggle.setEnabled(ready)
            if ready and qr.property('origin') != phone_url.text():
                from .remote_qr import phone_qr_image
                from PySide6.QtGui import QPixmap
                try:
                    qr.setPixmap(QPixmap.fromImage(phone_qr_image(phone_url.text())))
                    qr.setProperty('origin', phone_url.text())
                except (ImportError, AttributeError, ValueError):
                    qr.setText('QR Code 無法顯示，請在手機開啟上方網址。')
            elif not ready:
                qr.clear()
                qr.setProperty('origin', '')
            status.setText('固定入口已建立，請用手機掃碼。' if ready else self.fixed_tunnel.message)
            update_code()
            selected = {item.data(Qt.UserRole) for item in devices.selectedItems()}
            signature = [(device['id'],device['name']) for device in self.store.devices()]
            if signature != getattr(devices, '_device_signature', None):
                devices._device_signature = signature
                with QSignalBlocker(devices):
                    devices.clear()
                    for device_id, name in signature:
                        # Text lives only in the row widget (not also drawn
                        # underneath by the item); the item keeps it for access.
                        devices.addItem('')
                        item = devices.item(devices.count()-1)
                        item.setData(Qt.UserRole, device_id)
                        item.setData(Qt.AccessibleTextRole, name)
                        item.setSizeHint(QSize(0,36))
                        row = QWidget()
                        row.setStyleSheet('background: transparent;')
                        row_layout = QHBoxLayout(row)
                        row_layout.setContentsMargins(14,2,6,2)
                        name_label = QLabel(name)
                        name_label.setAttribute(Qt.WA_TransparentForMouseEvents)
                        row_layout.addWidget(name_label,1)
                        slot = QWidget()
                        slot.setFixedSize(30,30)
                        revoke = QPushButton(slot)
                        revoke.setObjectName('phoneRevoke')
                        revoke.setFixedSize(28,28)
                        revoke.move(1,1)  # centred in its 30x30 slot
                        # Plain square icon button: the dialog's button
                        # padding/min-width pushed the icon off-centre.
                        revoke.setStyleSheet(
                            'QPushButton#phoneRevoke { padding: 0; margin: 0; min-width: 0; min-height: 0;'
                            ' border: 1px solid #4a4356; border-radius: 6px; background: #1d1b24; }'
                            'QPushButton#phoneRevoke:hover { background: #3a2730; border-color: #b9576a; }')
                        revoke.setIconSize(QSize(16,16))
                        revoke.setIcon(themed_icon('trash'))
                        revoke.setAccessibleName('移除'+name)
                        revoke.setToolTip('移除此手機的連線授權')
                        revoke.clicked.connect(remove)
                        row_layout.addWidget(slot)
                        devices.setItemWidget(item,row)
                        item.setSelected(device_id in selected)
                # Fit the box to the phones (1–3 rows) instead of a fixed
                # height that left an empty grey band under a single phone.
                devices.setFixedHeight(min(max(len(signature), 1), 3) * 38 + 12)
            selection_changed()

        def start_fixed():
            try:
                self.start_fixed()
            except ValueError as exc:
                QMessageBox.warning(dialog, '固定手機入口', str(exc))
            refresh()

        def stop_connection():
            self.stop()
            self.store.set_setting('enabled', '0')
            refresh()

        def arm():
            self.server.arm_pairing()
            update_code()

        def remove():
            selected = devices.selectedItems()
            if selected:
                self.store.revoke(selected[0].data(Qt.UserRole))
                self.server.publish(self.snapshot())
                refresh()

        download.clicked.connect(lambda: webbrowser.open('https://tailscale.com/download/windows'))
        approval.clicked.connect(lambda: webbrowser.open(self.fixed_tunnel.approval_url) if self.fixed_tunnel.approval_url else None)
        fixed_start.clicked.connect(start_fixed)
        stop.clicked.connect(stop_connection)
        pair.clicked.connect(arm)
        self.server.changed.connect(refresh)
        self.tunnel.changed.connect(refresh)
        self.fixed_tunnel.changed.connect(refresh)
        countdown = QTimer(dialog)
        countdown.setInterval(1000)
        countdown.timeout.connect(update_code)
        countdown.start()
        dialog.install_chrome()
        def cleanup():
            self.server.changed.disconnect(refresh)
            self.tunnel.changed.disconnect(refresh)
            self.fixed_tunnel.changed.disconnect(refresh)
            countdown.stop()
            self.settings_dialog = None
            dialog.deleteLater()
        dialog.finished.connect(cleanup)
        refresh()
        dialog.show()
        QTimer.singleShot(0, fit)
