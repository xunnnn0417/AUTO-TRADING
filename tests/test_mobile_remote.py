"""Private temporary stores, loopback sockets and stubbed desktop operations only."""
import http.client
import json
import os
import secrets
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch

from PySide6.QtCore import QCoreApplication, QTimer, QUrl
from PySide6.QtNetwork import QAbstractSocket, QNetworkRequest, QSslSocket
from PySide6.QtTest import QTest
from PySide6.QtWebSockets import QWebSocket
from PySide6.QtWidgets import QApplication

import test_compact_followup_controls as fixtures
from test_fill_workflow_guards import sample
from trading_helper import gui
from trading_helper.remote_control import MobileServer, RemoteStore, normalized_origin
from trading_helper.remote_mobile import ASSETS
from trading_helper.remote_ui import RemoteController


def wait_for(predicate, timeout=3000):
    until = time.monotonic()+timeout/1000
    while not predicate() and time.monotonic() < until:
        QTest.qWait(10)
    return predicate()


class RemoteStoreTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name)/"remote.db"
        self.store = RemoteStore(self.path)
        self.addCleanup(self.store.db.close)

    def test_grant_survives_restart_and_can_be_revoked_without_touching_profiles(self):
        device, token = self.store.pair("手機")
        self.assertEqual(self.store.authenticate(token), device)
        self.assertNotIn(token, repr(self.store.devices()))
        reopened = RemoteStore(self.path)
        self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.authenticate(token), device)
        reopened.revoke(device)
        self.assertIsNone(reopened.authenticate(token))
        self.assertFalse(reopened.authorized(device))
        self.assertEqual(list(Path(self.temp.name).glob("*profile*")), [])

    def test_expired_grant_is_not_accepted(self):
        device, token = self.store.pair("手機")
        self.store.db.execute("UPDATE devices SET expires=0 WHERE id=?", (device,))
        self.store.db.commit()
        self.assertIsNone(self.store.authenticate(token))

    def test_pairing_cookie_cannot_authorize_a_different_temporary_hostname(self):
        device, token = self.store.pair('手機', 'https://first.trycloudflare.com')
        self.assertEqual(self.store.authenticate(token, 'https://first.trycloudflare.com'), device)
        self.assertIsNone(self.store.authenticate(token, 'https://second.trycloudflare.com'))
        self.assertIsNone(self.store.authenticate(token, 'http://127.0.0.1:8765'))

    def test_previous_device_database_migrates_without_erasing_saved_grants(self):
        legacy = Path(self.temp.name)/'legacy.db'
        with sqlite3.connect(legacy) as db:
            db.execute('CREATE TABLE devices (id TEXT PRIMARY KEY, name TEXT NOT NULL, '
                       'digest TEXT NOT NULL UNIQUE, expires REAL NOT NULL, revoked INTEGER NOT NULL DEFAULT 0)')
            db.execute('INSERT INTO devices VALUES (?,?,?,?,?)', ('old','手機',self.store.digest('oldtoken'),time.time()+1000,0))
        db.close()
        migrated = RemoteStore(legacy)
        self.addCleanup(migrated.db.close)
        self.assertEqual(migrated.authenticate('oldtoken', 'http://127.0.0.1:8765'), 'old')
        self.assertIsNone(migrated.authenticate('oldtoken', 'https://new.trycloudflare.com'))

    def test_unfinished_operation_becomes_unknown_after_restart_not_replayed(self):
        device, _ = self.store.pair("手機")
        self.store.begin(device, "operation-id", "fill_both", "digest")
        reopened = RemoteStore(self.path)
        self.addCleanup(reopened.db.close)
        self.assertEqual(reopened.latest(device)["status"], "unknown")
        with self.assertRaises(sqlite3.IntegrityError):
            reopened.begin(device, "operation-id", "fill_both", "digest")

    def test_external_origin_requires_https_and_no_credentials_or_paths(self):
        self.assertEqual(normalized_origin("https://Phone.Example:443/"), "https://phone.example")
        for origin in ("http://phone.example", "https://u:p@host", "https://host/a",
                       "https://host?x=1", "https://host#x", "https://host:99999"):
            with self.subTest(origin=origin), self.assertRaises(ValueError):
                normalized_origin(origin)


class MobileTransportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RemoteStore(Path(self.temp.name)/"remote.db")
        self.server = MobileServer(self.store, ASSETS)
        self.server.start(port=0)
        self.server.publish({"health": "正常", "value": "測試"})

    def tearDown(self):
        self.server.stop()
        self.qtapp.processEvents()
        self.store.db.close()
        self.temp.cleanup()

    def http(self, method="GET", path="/", body=None, headers=None):
        port = self.server.http.serverPort()
        def request():
            conn = http.client.HTTPConnection("127.0.0.1", port, timeout=3)
            try:
                conn.request(method, path, body=body, headers=headers or {})
                response = conn.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                conn.close()
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(request)
            self.assertTrue(wait_for(future.done, 4000), "loopback request timed out")
            return future.result()

    def pair(self, code=None, origin=None, **extra):
        body = json.dumps(dict(code=code or self.server.arm_pairing(), name="測試手機", **extra))
        return self.http("POST", "/api/pair", body,
                         {"Origin": origin or self.server.local_origin, "Content-Type": "application/json"})

    def test_listener_is_loopback_and_static_assets_have_security_headers(self):
        self.assertTrue(self.server.http.serverAddress().isLoopback())
        status, headers, body = self.http()
        self.assertEqual(status, 200)
        self.assertIn("手機控制", body.decode())
        self.assertEqual(headers["Cache-Control"], "no-store")
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", headers["Content-Security-Policy"])

    @unittest.skipUnless(os.name == 'nt', 'Windows native TLS backend')
    def test_windows_transport_selects_native_tls_without_disabling_verification(self):
        self.assertEqual(QSslSocket.activeBackend(), 'schannel')
        self.assertTrue(QSslSocket.supportsSsl())
        socket = QSslSocket()
        self.assertNotEqual(socket.peerVerifyMode(), QSslSocket.VerifyNone)

    @unittest.skipUnless(os.name == 'nt', 'Windows native TLS backend')
    def test_missing_windows_backend_does_not_fall_back_to_conflicting_openssl(self):
        paths = QCoreApplication.libraryPaths()
        with patch('trading_helper.remote_control._native_tls_ready', False), \
             patch.object(QSslSocket, 'setActiveBackend', return_value=False), \
             patch('trading_helper.remote_control.QWebSocketServer') as websocket:
            with self.assertRaisesRegex(ValueError, '加密連線元件'):
                MobileServer(self.store, ASSETS)
        websocket.assert_not_called()
        self.assertEqual(QCoreApplication.libraryPaths(), paths)

    def test_pair_is_one_use_and_cookie_is_http_only(self):
        code = self.server.arm_pairing()
        status, headers, _ = self.pair(code)
        self.assertEqual(status, 200)
        self.assertIn("HttpOnly", headers["Set-Cookie"])
        self.assertIn("SameSite=Strict", headers["Set-Cookie"])
        self.assertEqual(self.pair(code)[0], 403)

    def test_session_check_remembers_pairing_and_rejects_missing_credentials(self):
        self.assertEqual(self.http(path="/api/session")[0], 401)
        _, headers, _ = self.pair()
        cookie = headers["Set-Cookie"].split(";")[0]
        self.assertEqual(self.http(path="/api/session", headers={"Cookie": cookie})[0], 200)
        self.store.revoke(self.store.devices()[0]["id"])
        self.assertEqual(self.http(path="/api/session", headers={"Cookie": cookie})[0], 401)

    def test_public_proxy_origin_sets_secure_cookie(self):
        self.server.public_origin = "https://phone.example"
        status, headers, _ = self.http("POST", "/api/pair", json.dumps({"code": self.server.arm_pairing()}),
                    {"Host": "phone.example", "Origin": "https://phone.example", "Content-Type": "application/json"})
        self.assertEqual(status, 200)
        self.assertIn("; Secure", headers["Set-Cookie"])

    def test_cross_origin_rebinding_and_path_traversal_are_rejected(self):
        self.assertEqual(self.pair(origin="https://attacker.example")[0], 403)
        self.assertEqual(self.http(headers={"Host": "attacker.example"})[0], 403)
        self.assertEqual(self.http(path="/../config.json")[0], 404)
        self.assertEqual(self.http(path="/mobile-remote.sqlite3")[0], 404)

    def test_pair_code_expires_and_locks_after_five_failures(self):
        code = self.server.arm_pairing()
        for _ in range(5):
            self.assertEqual(self.pair("wrong")[0], 403)
        self.assertEqual(self.pair(code)[0], 403)
        code = self.server.arm_pairing()
        self.server.pair_until = 0
        self.assertEqual(self.pair(code)[0], 403)

    def test_websocket_authenticates_cookie_and_delivers_state(self):
        status, headers, _ = self.pair()
        self.assertEqual(status, 200)
        socket = QWebSocket(self.server.local_origin)
        self.addCleanup(socket.close)
        messages = []
        socket.textMessageReceived.connect(lambda raw: messages.append(json.loads(raw)))
        request = QNetworkRequest(QUrl(self.server.local_origin.replace("http", "ws")+"/ws"))
        request.setRawHeader(b"Cookie", headers["Set-Cookie"].split(";")[0].encode())
        socket.open(request)
        self.assertTrue(wait_for(lambda: bool(messages)), socket.errorString())
        self.assertEqual(messages[0]["state"]["value"], "測試")
        self.server.publish({"health": "正常", "value": "已更新"})
        self.assertTrue(wait_for(lambda: len(messages) > 1))
        self.assertEqual(messages[-1]["state"]["value"], "已更新")
        device = self.store.devices()[0]["id"]
        self.store.revoke(device)
        socket.sendTextMessage('{"type":"ping"}')
        self.assertTrue(wait_for(lambda: socket.state() == QAbstractSocket.UnconnectedState))


class MobileDesktopAdapterTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        fixtures.CompactFollowUpControlsTests.setUp(self)
        patcher = patch("trading_helper.remote_ui.interactive_desktop", return_value=True)
        patcher.start()
        self.addCleanup(patcher.stop)
        self.w.instruction = sample()
        self.w._show_instruction(self.w.instruction)
        self.controller = RemoteController(self.w)
        self.w.remote_controller = self.controller
        self.controller.start(port=0)
        self.device, _ = self.controller.store.pair("測試手機")
        self.replies = []
        self.reply_patch = patch.object(self.controller.server, "reply", side_effect=lambda d, m: self.replies.append(m))
        self.reply_patch.start()
        self.addCleanup(self.reply_patch.stop)

    def tearDown(self):
        for widget in QApplication.topLevelWidgets():
            if widget is not self.w and widget.isVisible() and hasattr(widget, "reject"):
                widget.reject()
        self.controller.stop()
        self.w._mobile_resume_timer.stop()
        self.controller.store.db.close()
        fixtures.CompactFollowUpControlsTests.tearDown(self)

    def command(self, action, args=None, **changes):
        self.controller.tick()
        request = dict(id=secrets.token_hex(12), action=action, args=args or {},
                       revision=self.controller.server.revision, lease=self.controller.server.lease)
        request.update(changes)
        self.controller._command(self.device, request)
        return request

    def test_shared_drafts_sync_without_sheet_or_mouse_reentry(self):
        with patch.object(self.w, "_write_trade_parameter_values") as write:
            self.command("draft", {"internal_balance": "51234", "expected_sl_combined": "-8.59"})
        write.assert_not_called()
        self.assertEqual(self.w.parameter_inputs["internal_balance"].text(), "51234")
        self.w.parameter_inputs["daily_pnl"].setText("-12")
        self.controller.tick()
        self.assertEqual(self.controller.server.state["parameters"]["daily_pnl"]["raw"], "-12")

    def test_local_edit_between_publish_and_mobile_draft_cannot_be_overwritten(self):
        self.controller.tick()
        request = dict(id=secrets.token_hex(12), action="draft", args={"internal_balance": "49000"},
                       revision=self.controller.server.revision, lease=self.controller.server.lease)
        self.w.parameter_inputs["internal_balance"].setText("53000")
        self.controller._command(self.device, request)
        self.assertEqual(self.replies[-1]["type"], "rejected")
        self.assertEqual(self.w.parameter_inputs["internal_balance"].text(), "53000")

    def test_stale_state_busy_and_unknown_fields_do_not_dispatch(self):
        with patch.object(self.w, "fill_both") as fill:
            self.command("fill_both", revision=-1)
            self.assertEqual(self.replies[-1]["type"], "rejected")
            self.w._active_tasks = 1
            self.command("fill_both")
            self.w._active_tasks = 0
            self.command("draft", {"service_account_file": "a"})
            self.command("calibrate")
            self.qtapp.processEvents()
        fill.assert_not_called()
        self.assertTrue(all(r["type"] == "rejected" for r in self.replies))

    def test_fill_delegates_once_and_duplicate_id_never_replays(self):
        with patch.object(self.w, "fill_both") as fill:
            request = self.command("fill_both")
            self.qtapp.processEvents()
            fill.assert_called_once()
            self.controller._command(self.device, request)
            fill.assert_called_once()
            self.assertEqual(self.replies[-1]["type"], "result")
        self.controller.last_busy = 0
        self.controller.tick()
        self.assertEqual(self.controller.store.latest(self.device)["status"], "not_started")

    def test_real_receipt_is_required_to_report_auto_entry_success(self):
        self.w.auto_entry_on_fill_both.blockSignals(True)
        self.w.auto_entry_on_fill_both.setChecked(True)
        self.w.auto_entry_on_fill_both.blockSignals(False)
        with patch.object(self.w, "fill_both"):
            self.command("fill_both")
            self.qtapp.processEvents()
        self.controller._task_result({"name": "填入兩邊", "status": "completed"})
        self.controller.last_busy = 0
        self.controller.tick()
        self.assertEqual(self.controller.store.latest(self.device)["status"], "needs_review")

    def test_local_change_after_acceptance_prevents_dispatching_different_values(self):
        with patch.object(self.w, "fill_both") as fill:
            self.command("fill_both")
            self.w.parameter_inputs["internal_balance"].setText("49000")
            self.qtapp.processEvents()
            fill.assert_not_called()
        self.controller.last_busy = 0
        self.controller.tick()
        self.assertEqual(self.controller.store.latest(self.device)["status"], "failed")

    def test_confirmations_are_answered_on_phone_without_bypassing_checks(self):
        answers = []
        def desktop_flow():
            answers.append(gui.QMessageBox.question(self.w, "確認止損", "手數可能增加，仍要進場嗎？",
                           gui.QMessageBox.Yes | gui.QMessageBox.No, gui.QMessageBox.No,
                           yes_text="繼續進場", no_text="取消"))
        def answer_on_phone():
            self.controller.tick()
            descriptor = self.controller.server.state["dialog"]
            self.assertIsNotNone(descriptor)
            button = next(b for b in descriptor["buttons"] if b["text"] == "取消")
            self.command("dialog", {"dialog": descriptor["id"], "button": button["id"], "checks": {}})
        with patch.object(self.w, "fill_both", side_effect=desktop_flow):
            QTimer.singleShot(120, answer_on_phone)
            self.command("fill_both")
            self.assertTrue(wait_for(lambda: bool(answers)))
        self.assertEqual(answers, [gui.QMessageBox.No])

    def test_locked_desktop_is_not_reported_ready_and_cannot_dispatch(self):
        with patch("trading_helper.remote_ui.interactive_desktop", return_value=False), patch.object(self.w, "fill_both") as fill:
            self.controller._desktop_checked = 0
            self.command("fill_both")
            self.assertEqual(self.controller.server.state["health"], "無法操作")
            self.qtapp.processEvents()
            fill.assert_not_called()

    def test_old_remote_receipt_cannot_grant_control_of_later_local_settings(self):
        from PySide6.QtWidgets import QDialog, QVBoxLayout, QPushButton
        self.controller.dialog_owner = self.device
        local = QDialog(self.w)
        local.setWindowTitle("電腦設定")
        local.setModal(True)
        layout = QVBoxLayout(local)
        layout.addWidget(QPushButton("更改校準", local))
        local.show()
        self.qtapp.processEvents()
        try:
            self.assertIsNone(self.controller._dialog_snapshot())
        finally:
            local.reject()

    def test_mobile_snapshot_does_not_contain_sheet_credentials_or_calibration(self):
        self.w.store.data["sheet"]["service_account_file"] = "PRIVATE_KEY_FILE"
        self.w.store.data["sheet"]["spreadsheet_url"] = "PRIVATE_SHEET_URL"
        self.w.store.data["platforms"]["MT5"]["points"] = {"secret_calibration": [1, 2]}
        payload = json.dumps(self.controller.snapshot(), ensure_ascii=False)
        for secret in ("PRIVATE_KEY_FILE", "PRIVATE_SHEET_URL", "secret_calibration"):
            self.assertNotIn(secret, payload)

    def test_temporary_phone_origin_and_pairing_never_replace_saved_fixed_origin(self):
        self.controller.store.set_setting('origin', 'https://fixed.example.com')
        with patch.object(self.controller.tunnel, 'start') as start:
            self.controller.start_temporary(port=0)
        start.assert_called_once_with(self.controller.server.local_origin)
        self.assertTrue(self.controller.temporary_connection)
        self.assertEqual(self.controller.store.setting('enabled'), '0')
        self.assertEqual(self.controller.server.public_origin, '')
        self.controller._tunnel_ready('https://example-control.trycloudflare.com')
        self.assertEqual(self.controller.server.public_origin, 'https://example-control.trycloudflare.com')
        self.assertEqual(len(self.controller.server.pair_code), 8)
        self.assertEqual(self.controller.store.setting('origin'), 'https://fixed.example.com')
        self.controller._tunnel_failed('連線已中斷')
        self.assertFalse(self.controller.server.http.isListening())
        self.assertFalse(self.controller.temporary_connection)
        self.assertEqual(self.controller.server.pair_code, '')
        self.assertEqual(self.controller.tunnel.message, '連線已中斷')

    def test_closing_desktop_cancels_delayed_mobile_resume(self):
        self.w._mobile_resume_timer.start(500)
        self.w.close()
        self.assertFalse(self.w._mobile_resume_timer.isActive())

    def test_backend_failure_is_explained_in_desktop_settings(self):
        with patch.object(self.w, '_mobile_remote', side_effect=ValueError('Windows 加密連線元件無法啟用')), \
             patch.object(gui.QMessageBox, 'warning') as warning:
            self.w.open_mobile_remote()
        warning.assert_called_once()
        self.assertIn('加密連線元件', warning.call_args.args[2])
