"""Temporary tunnel lifecycle with stubbed child processes, no public listener."""
import unittest
import json
import tempfile
from pathlib import Path
from unittest.mock import patch

from PySide6.QtWidgets import QApplication

from trading_helper.remote_tunnel import QuickTunnel


class QuickTunnelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        self.tunnel = QuickTunnel()
        self.addCleanup(self.tunnel.stop)
        self.urls, self.errors = [], []
        self.tunnel.ready.connect(self.urls.append)
        self.tunnel.failed.connect(self.errors.append)

    def start_stub(self):
        with patch('trading_helper.remote_tunnel.cloudflared_path', return_value='cloudflared.exe'), \
             patch.object(self.tunnel.process, 'start') as start:
            self.tunnel.start('http://127.0.0.1:18765')
        start.assert_called_once()

    def test_explicit_start_uses_only_loopback_with_private_isolated_config(self):
        self.assertFalse(self.tunnel.timeout.isActive())
        self.start_stub()
        args = self.tunnel.process.arguments()
        self.assertEqual(args[-2:], ['--url', 'http://127.0.0.1:18765'])
        self.assertIn('--no-autoupdate', args)
        self.assertIn('127.0.0.1:0', args)
        config = Path(args[args.index('--config') + 1])
        self.assertEqual(config.read_text(), '{}\n')
        self.tunnel.stop()
        self.assertFalse(config.exists())

    def test_url_only_is_not_success_until_connection_is_registered(self):
        self.start_stub()
        self.tunnel._consume('INF https://example-control.trycloud')
        self.tunnel._consume('flare.com |\n')
        self.assertEqual(self.urls, [])
        self.assertFalse(self.tunnel.connected)
        self.tunnel._consume('INF Registered tunnel connection connIndex=0\n')
        self.assertEqual(self.urls, ['https://example-control.trycloudflare.com'])
        self.assertTrue(self.tunnel.connected)
        self.assertFalse(self.tunnel.timeout.isActive())
        self.tunnel._consume('INF Registered tunnel connection connIndex=1\n')
        self.assertEqual(len(self.urls), 1)

    def test_untrusted_or_incomplete_hostname_cannot_become_phone_origin(self):
        self.start_stub()
        for value in ('https://example.trycloudflare.com.evil.org', 'https://evil.org',
                      'http://example.trycloudflare.com'):
            self.tunnel._consume(value+'\nINF Registered tunnel connection\n')
        self.assertEqual(self.urls, [])
        self.assertFalse(self.tunnel.connected)

    def test_stopping_ignores_late_readiness_and_never_restarts_process(self):
        self.start_stub()
        self.tunnel.stop()
        self.tunnel._consume('https://example-control.trycloudflare.com\nRegistered tunnel connection\n')
        self.assertEqual(self.urls, [])
        self.assertFalse(self.tunnel.connected)
        self.assertFalse(self.tunnel.timeout.isActive())

    def test_failure_is_reported_once_and_stops_timeout(self):
        self.start_stub()
        self.tunnel._fail('手機連線逾時')
        self.tunnel._finished(1)
        self.tunnel._error(None)
        self.assertEqual(self.errors, ['手機連線逾時'])
        self.assertFalse(self.tunnel.timeout.isActive())
        self.assertFalse(self.tunnel.connected)

    def test_missing_tool_does_not_download_install_or_start(self):
        with patch('trading_helper.remote_tunnel.cloudflared_path', return_value=''), \
             patch.object(self.tunnel.process, 'start') as start:
            with self.assertRaisesRegex(ValueError, '尚未安裝'):
                self.tunnel.start('http://127.0.0.1:8765')
        start.assert_not_called()
        self.assertFalse(self.tunnel.timeout.isActive())

    def test_other_hosts_and_shell_arguments_are_rejected(self):
        for url in ('http://0.0.0.0:8765', 'http://127.0.0.1:8765/a',
                    'https://example.org', 'http://127.0.0.1:8765 --evil'):
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.tunnel.start(url)

    def test_failure_diagnostics_are_local_bounded_and_redact_sensitive_values(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder)/'mobile-connection.json'
            self.tunnel.diagnostic_path = path
            self.start_stub()
            self.tunnel._consume('ERR request https://secret.trycloudflare.com token=PRIVATEKEY Cookie=PRIVATECOOKIE C:\\Users\\Private\\file\n')
            self.tunnel._finished(7)
            records = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(records[-1]['exit_code'], '7')
            self.assertEqual(records[-1]['event'], 'failed')
            text = path.read_text(encoding='utf-8')
            for secret in ('secret.trycloudflare.com','PRIVATEKEY','PRIVATECOOKIE','Private'):
                self.assertNotIn(secret, text)
            for _ in range(25):
                self.tunnel._record('test')
            self.assertEqual(len(json.loads(path.read_text(encoding='utf-8'))), 20)

    def test_unwritable_diagnostics_never_break_connection_failure_handling(self):
        with tempfile.TemporaryDirectory() as folder:
            self.tunnel.diagnostic_path = Path(folder)
            self.start_stub()
            self.tunnel._fail('網路失敗')
            self.assertEqual(self.errors, ['網路失敗'])
