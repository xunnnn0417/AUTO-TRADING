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

    def test_reopening_same_origin_reuses_cookie_without_another_pairing_code(self):
        status, headers, _ = self.pair()
        self.assertEqual(status, 200)
        cookie = headers['Set-Cookie'].split(';')[0]
        for _ in range(5):
            status, _, body = self.http(path='/api/session', headers={'Cookie': cookie})
            self.assertEqual(status, 200)
            self.assertEqual(json.loads(body), {'paired': True})
        self.assertEqual(len(self.store.devices()), 1)
        self.assertEqual(self.server.pair_code, '')

    def test_install_assets_work_without_caching_trades_or_weakening_auth(self):
        from PySide6.QtGui import QImage
        status, headers, body = self.http('GET', '/manifest.webmanifest')
        self.assertEqual(status, 200)
        manifest = json.loads(body)
        self.assertEqual(manifest['scope'], '/')
        for icon in manifest['icons']:
            status, _, raw = self.http('GET', icon['src'])
            self.assertEqual(status, 200)
            image = QImage.fromData(raw)
            self.assertFalse(image.isNull())
            self.assertEqual(f'{image.width()}x{image.height()}', icon['sizes'])
        status, headers, raw = self.http('GET', '/sw.js')
        self.assertEqual(status, 200)
        self.assertIn('no-store', dict(headers)['Cache-Control'])
        self.assertNotIn(b'caches.', raw)
        self.assertNotIn(b'fetch', raw)
        self.assertEqual(self.http('GET', '/api/session')[0], 401)

    def test_shared_ruler_image_is_not_served_to_unpaired_clients(self):
        self.server.ruler_image = b'<svg xmlns="http://www.w3.org/2000/svg"><text>private</text></svg>'
        path = '/api/ruler.png?v='+'a'*16
        status, _, body = self.http(path=path)
        self.assertEqual(status, 401)
        self.assertNotIn(b'private', body)
        _, headers, _ = self.pair()
        status, headers, body = self.http(path=path, headers={'Cookie': headers['Set-Cookie'].split(';')[0]})
        self.assertEqual(status, 200)
        self.assertEqual(headers['Content-Type'], 'image/png')
        self.assertIn(b'private', body)

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

    def test_fixed_origin_resumes_after_restart_without_discarding_grants(self):
        with patch('trading_helper.remote_tunnel.tailscale_path', return_value='tailscale.exe'), \
             patch.object(self.controller.fixed_tunnel, 'start'):
            self.controller.start_fixed(port=0)
        origin = 'https://laptop.example.ts.net:8443'
        self.controller._fixed_ready(origin)
        device, token = self.controller.store.pair('固定手機', origin)
        self.controller.stop()
        self.assertEqual(self.controller.store.authenticate(token, origin), device)
        self.assertEqual(self.controller.store.setting('origin'), origin)
        with patch.object(self.controller, 'start_fixed') as start:
            self.controller.resume()
        start.assert_called_once()

    def test_missing_fixed_tool_preserves_working_connection(self):
        with patch('trading_helper.remote_tunnel.tailscale_path', return_value=''):
            with self.assertRaisesRegex(ValueError, '安裝 Tailscale'):
                self.controller.start_fixed(port=0)
        self.assertTrue(self.controller.server.http.isListening())

    def test_backend_failure_is_explained_in_desktop_settings(self):
        with patch.object(self.w, '_mobile_remote', side_effect=ValueError('Windows 加密連線元件無法啟用')), \
             patch.object(gui.QMessageBox, 'warning') as warning:
            self.w.open_mobile_remote()
        warning.assert_called_once()
        self.assertIn('加密連線元件', warning.call_args.args[2])

    def test_phone_connection_settings_do_not_block_paired_phone(self):
        self.controller.show_settings()
        self.qtapp.processEvents()
        dialog = self.controller.settings_dialog
        self.assertIsNotNone(dialog)
        self.assertFalse(dialog.isModal())
        self.assertTrue(self.controller.snapshot()['available'])
        self.assertNotIn('待確認', self.controller.snapshot()['health'])
        with patch.object(self.w, 'fill_both') as fill:
            self.command('fill_both')
            self.qtapp.processEvents()
            fill.assert_called_once()
        dialog.close()
        self.qtapp.processEvents()
        self.assertIsNone(self.controller.settings_dialog)

    def test_qr_collapse_restores_height_and_keeps_device_list_compact(self):
        from PySide6.QtWidgets import QListWidget, QPushButton, QLabel
        self.controller.show_settings()
        self.qtapp.processEvents()
        dialog = self.controller.settings_dialog
        self.addCleanup(dialog.close)
        qr = dialog.findChild(QPushButton, 'phoneQrToggle')
        self.assertIsNotNone(qr)
        self.controller.server.public_origin = 'https://phone.example.com'
        self.controller.server.changed.emit()
        self.qtapp.processEvents()
        original = dialog.height()
        devices = dialog.findChild(QListWidget)
        for _ in range(3):
            qr.setChecked(True)
            QTest.qWait(20)
            self.assertGreater(dialog.height(), original)
            qr.setChecked(False)
            QTest.qWait(20)
            self.assertLessEqual(abs(dialog.height()-original), 2)
            self.assertLessEqual(devices.height(), 90)
        self.assertFalse(any(b.text() == '複製手機網址' for b in dialog.findChildren(QPushButton)))
        code = dialog.findChild(QLabel, 'phonePairCode')
        self.controller.server.arm_pairing()
        self.controller.server.pair_until = time.monotonic()+62
        self.controller.server.changed.emit()
        countdown = dialog.findChild(QLabel, 'phonePairCountdown')
        self.assertIn('01:02', countdown.text())
        self.controller.server.pair_until = 0
        self.controller.server.changed.emit()
        self.assertIn('已過期', code.text())
        self.controller.server.pair_code = ''
        self.controller.server.changed.emit()
        self.assertNotIn('已過期', code.text())

    def test_routine_success_is_inline_but_failures_still_request_attention(self):
        self.command('refresh_news')
        self.controller.last_busy = 0
        self.controller._finish()
        self.assertFalse(self.controller.store.latest(self.device)['result']['popup_required'])
        self.command('refresh_news')
        self.controller.active['errors'].append('來源失敗')
        self.controller._finish()
        self.assertTrue(self.controller.store.latest(self.device)['result']['popup_required'])

    def test_phone_settings_show_fixed_setup_and_only_offer_revoke_after_selection(self):
        from PySide6.QtWidgets import QListWidget, QPushButton, QGroupBox
        self.controller.show_settings()
        self.qtapp.processEvents()
        dialog = self.controller.settings_dialog
        self.addCleanup(dialog.close)
        labels = [b.text() for b in dialog.findChildren(QPushButton)]
        for removed in ('關閉', '其他連線設定 ▾', '設定固定入口 ▾', '啟用手機連線（臨時網址）'):
            self.assertNotIn(removed, labels)
        group = dialog.findChild(QGroupBox, 'phoneFixedSetup')
        self.assertIsNotNone(group)
        self.assertTrue(group.isVisible())
        revoke = dialog.findChild(QPushButton, 'phoneRevoke')
        devices = dialog.findChild(QListWidget)
        self.assertFalse(revoke.isVisible())
        devices.setCurrentRow(0)
        self.assertTrue(revoke.isVisible())
        self.controller.server.changed.emit()
        self.assertTrue(revoke.isVisible())
        devices.clearSelection()
        self.assertFalse(revoke.isVisible())

    def test_mobile_news_bounds_dates_and_omits_price_recaps(self):
        from datetime import datetime, timedelta, timezone
        from trading_helper.calendar_events import CalendarEvent, Announcement
        now = datetime.now(timezone.utc)
        calendar = self.w._get_event_calendar()
        calendar.events = [CalendarEvent(now+timedelta(days=400), 'USD', 'far'),
                           CalendarEvent(now+timedelta(days=2), 'USD', 'later'),
                           CalendarEvent(now+timedelta(hours=1), 'USD', 'near')]
        calendar.news = [Announcement(now, '來源', '金價曾反彈1%'),
                         Announcement(now, '來源', '美軍襲擊中東基地', '來源提供的事件內容')]
        items = self.controller.snapshot()['news']
        self.assertEqual([item['title'] for item in items if item['scheduled']], ['near', 'later'])
        self.assertEqual([item['title'] for item in items if not item['scheduled']], ['美軍襲擊中東基地'])
        self.assertEqual(items[-1]['details'], '來源提供的事件內容')


class PhoneQrTests(unittest.TestCase):
    def test_local_qr_scans_to_exact_url_without_including_a_pairing_secret(self):
        import cv2
        import numpy as np
        from trading_helper.remote_qr import phone_qr_image
        origin = 'https://phone-test.trycloudflare.com'
        image = phone_qr_image(origin)
        rows = np.frombuffer(image.constBits(), dtype=np.uint8).reshape(image.height(), image.bytesPerLine())
        value, _, _ = cv2.QRCodeDetector().detectAndDecode(rows[:, :image.width()])
        self.assertEqual(value, origin)
