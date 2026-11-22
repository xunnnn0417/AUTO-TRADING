"""Isolated notification storage, crypto and fake push transport; no actual phone/trades."""
import base64
import json
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QObject, Signal

from trading_helper.remote_control import RemoteStore
from trading_helper.remote_notifications import (
    MobileNotifications, load_webpush, send_notification, validated_subscription)
from trading_helper.calendar_events import CalendarEvent, Announcement


class Calendar(QObject):
    announcements = Signal(object)

    def __init__(self):
        super().__init__()
        self.events = []
        self.source_times = {'ff': datetime.now(timezone.utc)}
        self.source_errors = {}

    def title(self, value):
        return value


def subscription():
    load_webpush()
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives import serialization
    private = ec.generate_private_key(ec.SECP256R1())
    public = private.public_key().public_bytes(serialization.Encoding.X962,
                                              serialization.PublicFormat.UncompressedPoint)
    enc = lambda raw: base64.urlsafe_b64encode(raw).decode().rstrip('=')
    return private, dict(endpoint='https://web.push.apple.com/Q/test-subscription',
                         keys=dict(p256dh=enc(public), auth=enc(b'0123456789abcdef')))


class MobileNotificationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.qt = QApplication.instance() or QApplication([])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.store = RemoteStore(Path(self.temp.name)/'mobile.db')
        self.service = MobileNotifications(self.store)
        self.service.enabled = True
        self.origin = 'https://helper.example'
        self.service.origin = self.origin
        self.device, self.token = self.store.pair('測試手機', self.origin)
        self.key, self.sub = subscription()
        self.service.subscription(self.device, self.origin, self.sub)
        self.calendar = Calendar()
        self.now = time.time()
        self.dispatch = patch.object(self.service, '_dispatch')
        self.dispatch.start()

    def tearDown(self):
        self.service.stop()
        self.dispatch.stop()
        self.store.db.close()
        self.service.deleteLater()
        self.qt.processEvents()
        self.temp.cleanup()

    def rows(self):
        return self.store.db.execute('SELECT event,payload,status FROM push_deliveries ORDER BY rowid').fetchall()

    def test_public_key_is_stable_across_restarts_and_no_secrets_in_response(self):
        public = self.service.public_key()
        other = MobileNotifications(self.store)
        self.assertEqual(public, other.public_key())
        self.assertEqual(len(base64.urlsafe_b64decode(public+'=')), 65)
        self.assertNotEqual(public, self.store.setting('push_private_key'))

    def test_subscription_accepts_only_known_https_push_services_and_valid_points(self):
        self.assertEqual(validated_subscription(self.sub), self.sub)
        for endpoint in ('http://web.push.apple.com/a', 'https://127.0.0.1/a',
                         'https://web.push.apple.com.evil/a', 'https://user@web.push.apple.com/a',
                         'https://web.push.apple.com:8765/a', 'https://web.push.apple.com/a#secret'):
            with self.subTest(endpoint=endpoint), self.assertRaises(ValueError):
                validated_subscription(dict(self.sub, endpoint=endpoint))
        bad = dict(self.sub, keys=dict(self.sub['keys'], p256dh='B'+'A'*86))
        with self.assertRaises(ValueError):
            validated_subscription(bad)

    def test_before_and_release_each_sent_once_including_process_restart(self):
        event = CalendarEvent(datetime.fromtimestamp(self.now+590, timezone.utc), 'USD', 'CPI')
        self.calendar.events = [event]
        self.service.poll(self.calendar, self.origin, self.now)
        self.service.poll(self.calendar, self.origin, self.now+6)
        self.assertEqual(len(self.rows()), 1)
        other = MobileNotifications(self.store)
        other.enabled = True
        with patch.object(other, '_dispatch'):
            other.poll(self.calendar, self.origin, self.now+12)
            other.poll(self.calendar, self.origin, self.now+591)
            other.poll(self.calendar, self.origin, self.now+597)
        self.assertEqual([json.loads(row[1])['kind'] for row in self.rows()], ['before', 'release'])
        self.assertTrue(all(json.loads(row[1])['title'] == '對沖小幫手' for row in self.rows()))
        self.assertNotIn('實際值', json.loads(self.rows()[-1][1])['body'])
        self.assertNotIn('請查看消息確認公布結果', json.loads(self.rows()[-1][1])['body'])

    def test_old_pending_title_is_shortened_at_delivery_without_changing_body_or_tag(self):
        from trading_helper.remote_notifications import combined_payload
        old = dict(title='重大事件公布時間已到', body='公布時間已到 · 9:30 PM · CPI',
                   kind='release', tag='stable-event-id', expires=self.now+180)
        row = ('phone', 'event', json.dumps(old), self.now+180, 'subscription')
        delivered = combined_payload([row])
        self.assertEqual(delivered['title'], '對沖小幫手')
        self.assertEqual(delivered['body'], old['body'])
        self.assertEqual(delivered['tag'], old['tag'])
        self.assertEqual(json.loads(row[2]), old)

    def test_automatic_rest_schedule_uses_same_phone_queue_and_stays_deduplicated(self):
        from trading_helper.calendar_events import TAIPEI, format_event_time
        from trading_helper.rest_reminders import rest_occurrences
        config = dict(enabled=True, minutes=[60, 30])
        now = datetime.fromtimestamp(self.now, TAIPEI)
        close = next(t for t in rest_occurrences(config, now) if t > now+timedelta(hours=2))
        self.calendar.rest_settings = lambda: config
        first = close.timestamp()-3600
        self.service.poll(self.calendar, self.origin, first)
        self.service.poll(self.calendar, self.origin, first+10)
        self.service.poll(self.calendar, self.origin, first+1800)
        payloads = [json.loads(row[1]) for row in self.rows()]
        self.assertEqual([p['kind'] for p in payloads], ['rest:60', 'rest:30'])
        self.assertTrue(all(p['title'] == '對沖小幫手' for p in payloads))
        self.assertIn(format_event_time(close), payloads[0]['body'])
        self.assertNotIn('公布', payloads[0]['body'])
        config['enabled'] = False
        self.service.poll(self.calendar, self.origin, first+1810)
        self.assertTrue(all(row[2] == 'cancelled' for row in self.rows()))

    def test_simultaneous_release_members_share_one_delivery_and_all_keep_receipts(self):
        from test_mobile_remote import wait_for
        when = datetime.fromtimestamp(self.now+590,timezone.utc)
        names = [f'指標{i:02}' for i in range(13)]
        self.calendar.events = [CalendarEvent(when,'USD',name) for name in names]
        self.service.poll(self.calendar,self.origin,self.now)
        self.assertEqual(len(self.rows()),13)
        with patch('trading_helper.remote_notifications.send_notification',return_value=201) as send:
            MobileNotifications._dispatch(self.service,self.now)
            self.assertTrue(wait_for(lambda: not self.service._busy))
            self.assertEqual(send.call_count,1)
            payload = send.call_args.args[1]
            self.assertEqual(payload['title'], '對沖小幫手')
            self.assertIn('13 則',payload['body'])
            for name in names:self.assertIn(name,payload['body'])
            self.assertTrue(all(row[2]=='sent' for row in self.rows()))
            MobileNotifications._dispatch(self.service,self.now+61)
            self.assertEqual(send.call_count,1)

    def test_grouping_keeps_phones_phases_and_different_times_separate(self):
        from trading_helper.remote_notifications import delivery_groups
        when = datetime.fromtimestamp(self.now,timezone.utc)
        def row(event,device='one',kind='release',time_value=when):
            return (device,event,json.dumps(dict(kind=kind,when=time_value.isoformat())),self.now+180,'subscription')
        rows = [row('a'),row('b',time_value=when.astimezone(timezone(timedelta(hours=8)))),
                row('c',device='two'),row('d',kind='before'),row('e',time_value=when+timedelta(seconds=1))]
        self.assertEqual([len(group) for group in delivery_groups(rows)],[2,1,1,1])

    def test_group_retry_uses_same_tag_and_stops_after_three_provider_attempts(self):
        from test_mobile_remote import wait_for
        when = datetime.fromtimestamp(self.now+590,timezone.utc)
        self.calendar.events = [CalendarEvent(when,'USD',name) for name in ('CPI','PPI')]
        self.service.poll(self.calendar,self.origin,self.now)
        with patch('trading_helper.remote_notifications.send_notification',return_value=429) as send:
            for attempt in range(3):
                MobileNotifications._dispatch(self.service,self.now+61*attempt)
                self.assertTrue(wait_for(lambda: not self.service._busy))
            self.assertEqual(send.call_count,3)
            self.assertEqual(len({call.args[1]['tag'] for call in send.call_args_list}),1)
            self.assertTrue(all(row[2]=='failed' for row in self.rows()))
            MobileNotifications._dispatch(self.service,self.now+190)
            self.assertEqual(send.call_count,3)

    def test_stale_missing_source_error_and_old_releases_do_not_notify(self):
        self.calendar.events = [CalendarEvent(datetime.fromtimestamp(self.now-70, timezone.utc), 'USD', 'CPI')]
        self.service.poll(self.calendar, self.origin, self.now)
        self.calendar.events = [CalendarEvent(datetime.fromtimestamp(self.now+500, timezone.utc), 'USD', 'CPI')]
        self.calendar.source_errors['ff'] = 'offline'
        self.service.poll(self.calendar, self.origin, self.now+6)
        self.calendar.source_errors.clear()
        self.calendar.source_times.clear()
        self.service.poll(self.calendar, self.origin, self.now+12)
        self.assertEqual(self.rows(), [])

    def test_only_new_relevant_real_news_are_queued_not_recaps_or_preview(self):
        self.service.poll(self.calendar, self.origin, self.now)
        when = datetime.fromtimestamp(self.now, timezone.utc)
        # The signal handler polls immediately; use the same clock as the explicit poll.
        with patch('trading_helper.remote_notifications.time', SimpleNamespace(time=lambda: self.now+6)):
            self.calendar.announcements.emit([
                Announcement(when, '香港電台國際', '美軍突然空襲伊朗基地'),
                Announcement(when, '香港電台財經', '金價收市上升1%'),
                Announcement(when, '測試', '美軍突然空襲伊朗基地'),
                Announcement(when-timedelta(hours=1), '香港電台國際', '美軍突然空襲伊朗基地'),
                Announcement(when+timedelta(hours=1), '香港電台國際', '美軍突然空襲伊朗基地')])
            self.service.poll(self.calendar, self.origin, self.now+6)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(json.loads(self.rows()[0][1])['kind'], 'breaking')

    def test_revoke_disable_different_origin_and_stopped_connection_do_not_queue(self):
        event = CalendarEvent(datetime.fromtimestamp(self.now+500, timezone.utc), 'USD', 'CPI')
        self.calendar.events = [event]
        self.service.poll(self.calendar, 'https://another.example', self.now)
        self.assertEqual(self.rows(), [])
        self.service.subscription(self.device, self.origin, None)
        self.service.poll(self.calendar, self.origin, self.now+6)
        self.assertEqual(self.rows(), [])
        self.service.subscription(self.device, self.origin, self.sub)
        self.store.revoke(self.device)
        self.service.poll(self.calendar, self.origin, self.now+12)
        self.assertEqual(self.rows(), [])
        self.service.stop()
        self.assertFalse(self.service.enabled)

    def test_failed_endpoint_removed_only_if_subscription_has_not_changed(self):
        raw = json.dumps(validated_subscription(self.sub))
        self.service._complete([(self.device, 'event', raw, 410, 'release')])
        self.assertFalse(self.service.subscribed(self.device, self.origin))
        self.service.subscription(self.device, self.origin, self.sub)
        self.service._complete([(self.device, 'event', 'obsolete', 410, 'release')])
        self.assertTrue(self.service.subscribed(self.device, self.origin))
        log = (Path(self.temp.name)/'diagnostics'/'mobile-notifications.json').read_text()
        for private in (self.device, self.token, self.sub['endpoint'], self.sub['keys']['auth']):
            self.assertNotIn(private, log)

    def test_test_notification_is_rate_limited_and_targets_only_requesting_phone(self):
        other, _ = self.store.pair('另一支手機', self.origin)
        self.service.subscription(other, self.origin, self.sub)
        with patch('trading_helper.remote_notifications.time.time', return_value=self.now):
            first = self.service.test(self.device, self.origin)
        with patch('trading_helper.remote_notifications.time.time', return_value=self.now+2):
            second = self.service.test(self.device, self.origin)
        self.assertEqual(first, dict(queued=True,cooldown=10))
        self.assertEqual(second, dict(queued=False,cooldown=8))
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(self.store.db.execute('SELECT device FROM push_deliveries').fetchone()[0], self.device)
        with patch('trading_helper.remote_notifications.time.time', return_value=self.now+10):
            again = self.service.test(self.device, self.origin)
        self.assertTrue(again['queued'])
        self.assertEqual(len(self.rows()), 2)
        self.assertEqual(len({json.loads(r[1])['tag'] for r in self.rows()}),2)

    def test_test_and_new_headline_dispatch_without_waiting_for_next_poll(self):
        with patch.object(self.service, '_dispatch') as dispatch:
            self.service.test(self.device,self.origin)
            dispatch.assert_called_once()
            dispatch.reset_mock()
            self.service.poll(self.calendar,self.origin,self.now)
            dispatch.reset_mock()
            self.calendar.announcements.emit([Announcement(datetime.now(timezone.utc),
                                             '香港電台國際','美軍突然空襲伊朗基地')])
            dispatch.assert_called_once()

    def test_worker_sends_off_ui_thread_marks_success_and_does_not_repeat(self):
        from PySide6.QtTest import QTest
        from test_mobile_remote import wait_for
        self.service.test(self.device, self.origin)
        with patch('trading_helper.remote_notifications.send_notification', return_value=201) as send:
            MobileNotifications._dispatch(self.service, self.now)
            self.assertTrue(wait_for(lambda: not self.service._busy))
            self.assertEqual(send.call_count, 1)
            self.assertEqual(self.rows()[0][2], 'sent')
            log = json.loads((Path(self.temp.name)/'diagnostics'/'mobile-notifications.json').read_text())[-1]
            self.assertEqual(log['attempts'],1)
            self.assertGreaterEqual(log['queue_ms'],0)
            self.assertGreaterEqual(log['completion_ms'],0)
            MobileNotifications._dispatch(self.service, self.now+65)
            QTest.qWait(20)
            self.assertEqual(send.call_count, 1)
        self.assertEqual(self.store.db.execute('SELECT count(*) FROM operations').fetchone()[0], 0)

    def test_worker_checks_revoke_before_send_and_retries_transient_failure_bounded(self):
        from test_mobile_remote import wait_for
        self.service.test(self.device, self.origin)
        with patch('trading_helper.remote_notifications.send_notification', side_effect=OSError('offline')) as send:
            MobileNotifications._dispatch(self.service, self.now)
            self.assertTrue(wait_for(lambda: not self.service._busy))
            self.assertEqual(send.call_count, 1)
            MobileNotifications._dispatch(self.service, self.now+2)
            self.assertEqual(send.call_count, 1)
            self.store.revoke(self.device)
            MobileNotifications._dispatch(self.service, self.now+10)
            self.assertEqual(send.call_count, 1)

    def test_worker_drops_subscription_changed_between_queue_and_send(self):
        self.service.test(self.device, self.origin)
        raw = self.store.db.execute('SELECT device,event,payload,expires FROM push_deliveries').fetchone()
        self.service.subscription(self.device, self.origin, None)
        with patch('trading_helper.remote_notifications.send_notification') as send:
            self.service._send_batch([(*raw, json.dumps(self.sub))], self.store.setting('push_private_key'))
            self.assertFalse(send.called)

    def test_pending_worker_from_stopped_connection_cannot_send_after_restart(self):
        self.service.test(self.device, self.origin)
        raw = self.store.db.execute('SELECT device,event,payload,expires FROM push_deliveries').fetchone()
        generation = self.service._generation
        self.service.stop()
        self.service.enabled = True
        with patch('trading_helper.remote_notifications.send_notification') as send:
            self.service._send_batch([(*raw, json.dumps(self.sub))],
                                    self.store.setting('push_private_key'), generation, self.origin)
            self.assertFalse(send.called)

    def test_retry_stops_after_three_attempts_and_does_not_block_ui(self):
        from test_mobile_remote import wait_for
        self.calendar.events = [CalendarEvent(datetime.fromtimestamp(self.now+590, timezone.utc),
                                              'USD', 'CPI')]
        self.service.poll(self.calendar, self.origin, self.now)
        with patch('trading_helper.remote_notifications.send_notification', return_value=429) as send:
            for attempt in range(3):
                MobileNotifications._dispatch(self.service, self.now+attempt*61)
                self.assertTrue(wait_for(lambda: not self.service._busy))
            MobileNotifications._dispatch(self.service, self.now+190)
            self.assertEqual(send.call_count, 3)
            self.assertEqual(self.rows()[0][2], 'failed')

    def test_desktop_schedule_signal_is_not_resent_as_breaking_news(self):
        from trading_helper.calendar_events import EconomicCalendar
        actual = EconomicCalendar(Path(self.temp.name)/'calendar.json')
        self.addCleanup(actual.close)
        actual.events = [CalendarEvent(datetime.fromtimestamp(self.now+590, timezone.utc),
                                      'USD', 'Interest Rate Decision')]
        actual.source_times = self.calendar.source_times
        actual.fetched_at = self.calendar.source_times['ff']
        self.service.poll(actual, self.origin, self.now)
        actual._check_reminders(datetime.fromtimestamp(self.now, timezone.utc))
        self.service.poll(actual, self.origin, self.now+6)
        self.assertEqual(len(self.rows()), 1)
        self.assertEqual(json.loads(self.rows()[0][1])['kind'], 'before')

    def test_real_encryption_vapid_and_no_redirect_with_fake_network(self):
        import requests
        import http_ece
        from cryptography.hazmat.primitives.asymmetric import ec, utils
        from cryptography.hazmat.primitives import hashes
        public = self.service.public_key()
        payload = {'title': '測試消息', 'body': 'CPI 即將公布'}
        captured = {}

        def fake_post(session, url, **kwargs):
            captured.update(url=url, **kwargs)
            return SimpleNamespace(status_code=201, text='', headers={})

        with patch.object(requests.Session, 'post', fake_post):
            self.assertEqual(send_notification(self.sub, payload, self.store.setting('push_private_key'), 90), 201)
        self.assertFalse(captured['allow_redirects'])
        clear = http_ece.decrypt(captured['data'], private_key=self.key,
                                 auth_secret=b'0123456789abcdef', version='aes128gcm')
        self.assertEqual(json.loads(clear), payload)
        auth = captured['headers']['Authorization']
        token = auth.split('t=')[1].split(',')[0]
        header, claims, signature = token.split('.')
        decode = lambda value: base64.urlsafe_b64decode(value+'='*(-len(value)%4))
        self.assertEqual(json.loads(decode(claims))['aud'], 'https://web.push.apple.com')
        sig = decode(signature)
        verifier = ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), decode(public))
        verifier.verify(utils.encode_dss_signature(int.from_bytes(sig[:32]), int.from_bytes(sig[32:])),
                        (header+'.'+claims).encode(), ec.ECDSA(hashes.SHA256()))
