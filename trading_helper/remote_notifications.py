"""Opt-in Web Push for news only; never accepts or dispatches trading commands."""
from __future__ import annotations

import base64
import hashlib
import json
import re
import sqlite3
import sys
import threading
import time
from math import ceil
from uuid import uuid4
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from PySide6.QtCore import QObject, Signal

PUSH_HOSTS = {'web.push.apple.com', 'fcm.googleapis.com', 'updates.push.services.mozilla.com'}


def delivery_groups(rows):
    """Group one phone's same-time alerts, retaining individual queue receipts."""
    groups = {}
    for row in rows:
        device, event, raw, _expires, subscription = row
        payload = json.loads(raw)
        when = datetime.fromisoformat(payload['when']) if payload.get('when') else event
        key = (device, subscription, payload['kind'], when)
        groups.setdefault(key, []).append(row)
    return list(groups.values())


def combined_payload(rows):
    payload = json.loads(rows[0][2])
    if len(rows) > 1:
        from .calendar_events import format_event_time
        prefix = payload['body'].split(' · ',1)[0] if payload['kind'] != 'breaking' else '突發重大消息'
        heading = f'{prefix} · {format_event_time(datetime.fromisoformat(payload["when"]))} · {len(rows)} 則'
        names = list(dict.fromkeys(json.loads(row[2])['headline'] for row in rows))
        body = heading+'\n'+'\n'.join('• '+name for name in names)
        payload.update(body=body if len(body)<=300 else body[:299]+'…',
                       tag=hashlib.sha256('\n'.join(sorted(row[1] for row in rows)).encode()).hexdigest(),
                       expires=min(row[3] for row in rows))
    payload.pop('when',None)
    payload.pop('headline',None)
    return payload


def load_webpush():
    # Source installs may keep optional dependencies in LAB's private vendor
    # directory. Portable releases install the pinned requirements normally.
    vendor = Path(__file__).resolve().parent.parent / 'vendor' / 'webpush'
    if vendor.is_dir() and str(vendor) not in sys.path:
        sys.path.append(str(vendor))
    import pywebpush
    return pywebpush


def validated_subscription(value):
    if not isinstance(value, dict):
        raise ValueError('通知設定格式不正確。')
    endpoint = value.get('endpoint')
    if not isinstance(endpoint, str) or not 1 <= len(endpoint) <= 2048:
        raise ValueError('通知網址格式不正確。')
    url = urlsplit(endpoint)
    if (url.scheme != 'https' or url.hostname not in PUSH_HOSTS or url.port not in (None, 443)
            or url.username or url.password or url.fragment or not url.path.startswith('/')):
        raise ValueError('不支援此瀏覽器的通知服務，請使用 Safari、Chrome 或 Firefox。')
    keys = value.get('keys')
    if not isinstance(keys, dict):
        raise ValueError('缺少通知金鑰。')
    clean = {}
    for key, length in (('p256dh', 65), ('auth', 16)):
        raw = keys.get(key)
        if not isinstance(raw, str) or not re.fullmatch(r'[A-Za-z0-9_-]{20,90}', raw):
            raise ValueError('通知金鑰格式不正確。')
        decoded = base64.urlsafe_b64decode(raw + '=' * (-len(raw) % 4))
        if len(decoded) != length or (key == 'p256dh' and decoded[0] != 4):
            raise ValueError('通知金鑰格式不正確。')
        clean[key] = raw
    # A real P-256 point, not just a string with the right size.
    load_webpush()
    from cryptography.hazmat.primitives.asymmetric import ec
    ec.EllipticCurvePublicKey.from_encoded_point(
        ec.SECP256R1(), base64.urlsafe_b64decode(clean['p256dh'] + '=' * (-len(clean['p256dh']) % 4)))
    return {'endpoint': endpoint, 'keys': clean}


def send_notification(subscription, payload, private_key, ttl):
    package = load_webpush()
    from py_vapid import Vapid
    import requests

    vapid = Vapid.from_string(private_key)
    # RFC 8292 permits an HTTPS contact URI including a path. py-vapid's
    # optional email-oriented regex rejects that path; the contact below is
    # a fixed, public project URL, never user input. Signing is unchanged.
    vapid.conf['no-strict'] = True

    class NoRedirectSession(requests.Session):
        def post(self, url, **kwargs):
            kwargs['allow_redirects'] = False
            return super().post(url, **kwargs)

    with NoRedirectSession() as session:
        response = package.webpush(
            subscription_info=validated_subscription(subscription),
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=vapid,
            vapid_claims={'sub': 'https://github.com/xunnnn0417/AUTO-TRADING'},
            ttl=max(1, min(int(ttl), 600)), timeout=6,
            headers={'Urgency': 'high'}, requests_session=session)
        return response.status_code


class MobileNotifications(QObject):
    completed = Signal(object)

    def __init__(self, store, parent=None):
        super().__init__(parent)
        self.store = store
        self.db_path = Path(store.db.execute('PRAGMA database_list').fetchone()[2])
        store.db.executescript('''
            CREATE TABLE IF NOT EXISTS push_subscriptions (
                device TEXT PRIMARY KEY, origin TEXT NOT NULL, subscription TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS push_deliveries (
                device TEXT NOT NULL, event TEXT NOT NULL, origin TEXT NOT NULL,
                payload TEXT NOT NULL, expires REAL NOT NULL, attempts INTEGER NOT NULL DEFAULT 0,
                retry REAL NOT NULL DEFAULT 0, status TEXT NOT NULL DEFAULT 'pending',
                PRIMARY KEY(device,event));
        ''')
        columns = {row[1] for row in store.db.execute('PRAGMA table_info(push_deliveries)')}
        for name in ('created','started'):
            if name not in columns:
                store.db.execute(f'ALTER TABLE push_deliveries ADD COLUMN {name} REAL NOT NULL DEFAULT 0')
        store.db.commit()
        self.completed.connect(self._complete)
        self.calendar = None
        self.origin = ''
        self.enabled = False
        self._busy = False
        self._news = []
        self._last_poll = 0.0
        self._generation = 0

    def public_key(self):
        load_webpush()
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import ec
        private = self.store.setting('push_private_key')
        if private:
            key = serialization.load_der_private_key(base64.b64decode(private), password=None)
        else:
            key = ec.generate_private_key(ec.SECP256R1())
            self.store.set_setting('push_private_key', base64.b64encode(key.private_bytes(
                serialization.Encoding.DER, serialization.PrivateFormat.PKCS8,
                serialization.NoEncryption())).decode())
        return base64.urlsafe_b64encode(key.public_key().public_bytes(
            serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)).decode().rstrip('=')

    def subscription(self, device, origin, value):
        if not self.store.authorized(device):
            raise ValueError('請重新配對手機。')
        with self.store.db:
            if value is None:
                self.store.db.execute('DELETE FROM push_subscriptions WHERE device=?', (device,))
                self.store.db.execute('DELETE FROM push_deliveries WHERE device=? AND status=?', (device, 'pending'))
            else:
                clean = validated_subscription(value)
                self.public_key()
                self.store.db.execute('INSERT OR REPLACE INTO push_subscriptions VALUES (?,?,?)',
                                      (device, origin, json.dumps(clean)))

    def subscribed(self, device, origin):
        return bool(self.store.authorized(device) and self.store.db.execute(
            'SELECT 1 FROM push_subscriptions WHERE device=? AND origin=?', (device, origin)).fetchone())

    def stop(self):
        self.enabled = False
        self._generation += 1
        self._news.clear()

    def test(self, device, origin):
        if not self.subscribed(device, origin):
            raise ValueError('請先啟用通知。')
        now = time.time()
        last = self.store.db.execute('''SELECT MAX(created) FROM push_deliveries
            WHERE device=? AND event LIKE 'test-%' ''', (device,)).fetchone()[0]
        if last and now-last < 10:
            return dict(queued=False, cooldown=ceil(10-(now-last)))
        identity = 'test-'+uuid4().hex
        payload = dict(title='對沖小幫手測試通知', body='手機通知已接通。',
                       tag=identity, kind='test', expires=now+60)
        with self.store.db:
            self.store.db.execute('''INSERT OR IGNORE INTO push_deliveries
                (device,event,origin,payload,expires,created) VALUES (?,?,?,?,?,?)''',
                (device, identity, origin, json.dumps(payload, ensure_ascii=False), now+60,now))
        self.origin = origin
        self._dispatch(now)
        return dict(queued=True, cooldown=10)

    def _receive_news(self, items):
        if self.enabled:
            self._news = (self._news + [item for item in items if not item.scheduled])[-20:]
            if self._news:
                self.poll(self.calendar,self.origin)

    def _enqueue(self, kind, item, title, body, now, expires):
        identity = hashlib.sha256(f'{kind}\n{item.source}\n{item.when.isoformat()}\n{item.title}'.encode()).hexdigest()
        payload = json.dumps(dict(title=title, body=body[:300], tag=identity, kind=kind,
                                  expires=expires, when=item.when.isoformat(),
                                  headline=self.calendar.title(item.title)), ensure_ascii=False)
        with self.store.db:
            self.store.db.execute('''INSERT OR IGNORE INTO push_deliveries
                (device,event,origin,payload,expires,created)
                SELECT p.device,?,p.origin,?,?,? FROM push_subscriptions p
                JOIN devices d ON d.id=p.device WHERE p.origin=? AND d.revoked=0 AND d.expires>?''',
                (identity, payload, expires, now, self.origin, now))

    def poll(self, calendar, origin, now=None):
        if not self.enabled or not origin.startswith('https://'):
            return
        if calendar is not self.calendar:
            if self.calendar is not None:
                self.calendar.announcements.disconnect(self._receive_news)
            self.calendar = calendar
            if calendar is not None:
                calendar.announcements.connect(self._receive_news)
        self.origin = origin
        if calendar is None:
            self._dispatch(time.time() if now is None else now)
            return
        now = time.time() if now is None else now
        # A disabled/edited local schedule must not send queued retries from its old settings.
        from .rest_reminders import normalize_settings
        try:
            rest = normalize_settings(getattr(calendar, 'rest_settings', lambda: {})())
        except ValueError:
            rest = {'enabled': False}
        with self.store.db:
            pending = self.store.db.execute("SELECT device,event,payload FROM push_deliveries WHERE status='pending'").fetchall()
            for device, event, raw in pending:
                payload = json.loads(raw)
                if not payload['kind'].startswith('rest:'):
                    continue
                from .calendar_events import TAIPEI
                when = datetime.fromisoformat(payload['when']).astimezone(TAIPEI)
                if (not rest['enabled'] or when.strftime('%H:%M') != rest['time']
                        or when.weekday() not in rest['days']
                        or payload['kind'] not in {f'rest:{n}' for n in rest['minutes']}):
                    self.store.db.execute("UPDATE push_deliveries SET status='cancelled' WHERE device=? AND event=?",
                                          (device, event))
        if now-self._last_poll < 5 and not self._news:
            self._dispatch(now)
            return
        self._last_poll = now
        from .calendar_events import SOURCE_NAMES, scheduled_reminders
        from .news_relevance import assess_headline
        for kind, item, title, body, expires in scheduled_reminders(calendar, datetime.fromtimestamp(now, timezone.utc)):
            self._enqueue(kind, item, title, body, now, expires)
        news, self._news = self._news, []
        for item in news:
            if (item.source in SOURCE_NAMES.values() and 0 <= now-item.when.timestamp() <= 900
                    and assess_headline(item.title).notify):
                self._enqueue('breaking', item, '突發重大消息', calendar.title(item.title), now, now+180)
        self._dispatch(now)

    def _dispatch(self, now):
        if self._busy or not self.enabled:
            return
        with self.store.db:
            self.store.db.execute('DELETE FROM push_deliveries WHERE expires<?', (now-86400,))
            rows = self.store.db.execute('''SELECT q.device,q.event,q.payload,q.expires,p.subscription
                FROM push_deliveries q JOIN push_subscriptions p ON p.device=q.device AND p.origin=q.origin
                JOIN devices d ON d.id=q.device WHERE q.status='pending' AND q.expires>?
                AND q.retry<=? AND q.attempts<3 AND q.origin=? AND d.revoked=0 AND d.expires>?
                ORDER BY q.created,q.rowid''', (now, now, self.origin, now)).fetchall()
            # Limit deliveries, not members: a simultaneous release must not
            # split simply because its thirteenth item crosses a batch limit.
            rows = [row for group in delivery_groups(rows)[:12] for row in group]
            for device, event, *_ in rows:
                self.store.db.execute('UPDATE push_deliveries SET attempts=attempts+1,retry=?,started=? WHERE device=? AND event=?',
                                      (now+60, now, device, event))
        if not rows:
            return
        self._busy = True
        private = self.store.setting('push_private_key')
        threading.Thread(target=self._send_batch,
                         args=(rows, private, self._generation, self.origin), daemon=True).start()

    def _send_batch(self, rows, private, generation=None, origin=None):
        generation = self._generation if generation is None else generation
        origin = self.origin if origin is None else origin
        results = []
        for group in delivery_groups(rows):
            if not self.enabled or generation != self._generation or origin != self.origin:
                break
            group = [row for row in group if row[3] > time.time()]
            if not group:
                continue
            device, _event, _raw, _expires, subscription = group[0]
            # Recheck revocation and subscription changes immediately before delivery.
            code = 0
            try:
                with closing(sqlite3.connect(self.db_path)) as db:
                    allowed = db.execute('''SELECT 1 FROM push_subscriptions p JOIN devices d ON d.id=p.device
                        WHERE p.device=? AND p.subscription=? AND p.origin=?
                        AND d.revoked=0 AND d.expires>?''',
                        (device, subscription, origin, time.time())).fetchone()
                if not allowed:
                    continue
                payload = combined_payload(group)
                code = send_notification(json.loads(subscription), payload, private,
                                         min(row[3] for row in group)-time.time())
            except Exception as exc:
                response = getattr(exc, 'response', None)
                code = int(getattr(response, 'status_code', 0) or 0)
            results.extend((device,event,subscription,code,json.loads(raw)['kind'])
                           for _device,event,raw,_expires,_sub in group)
        try:
            self.completed.emit(results)
        except RuntimeError:
            pass  # Application already exited; pending deliveries expire locally.

    def _complete(self, results):
        self._busy = False
        with self.store.db:
            for device, event, subscription, code, kind in results:
                status = 'sent' if 200 <= code < 300 else 'pending' if code in (0, 429, 500, 502, 503, 504) else 'failed'
                attempts = self.store.db.execute('SELECT attempts FROM push_deliveries WHERE device=? AND event=?',
                                                (device, event)).fetchone()
                if status == 'pending' and attempts and attempts[0] >= 3:
                    status = 'failed'
                self.store.db.execute('UPDATE push_deliveries SET status=? WHERE device=? AND event=?',
                                      (status, device, event))
                if code in (404, 410):
                    self.store.db.execute('DELETE FROM push_subscriptions WHERE device=? AND subscription=?',
                                          (device, subscription))
                timing = self.store.db.execute('SELECT created,started,attempts FROM push_deliveries WHERE device=? AND event=?',
                                               (device,event)).fetchone()
                self._diagnostic(kind, status, code, timing)

    def _diagnostic(self, kind, status, code, timing=None):
        path = self.db_path.parent / 'diagnostics' / 'mobile-notifications.json'
        try:
            rows = json.loads(path.read_text(encoding='utf-8')) if path.exists() else []
            rows = rows if isinstance(rows, list) else []
            record = dict(time=datetime.now(timezone.utc).isoformat(), kind=kind, status=status, http=code)
            if timing and timing[0] and timing[1]:
                record.update(queue_ms=max(0,round((timing[1]-timing[0])*1000)),
                              completion_ms=max(0,round((time.time()-timing[1])*1000)), attempts=timing[2])
            rows.append(record)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(rows[-100:]), encoding='utf-8')
        except (OSError, ValueError):
            pass
