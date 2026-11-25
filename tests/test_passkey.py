"""Passkey (Face ID) re-linking: crypto checks, store, and HTTPS endpoints.

Offline only: keys are generated in the test; no phone or network needed.
"""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
import hashlib
import json
import secrets
import struct
import unittest

from trading_helper import passkey
from trading_helper.passkey import (
    PasskeyError, b64url_decode, b64url_encode, verify_assertion, verify_es256,
    verify_registration,
)

ORIGIN = "https://phone.example"
RP_ID = "phone.example"


# ---- test-only P-256 signer (uses the module's own curve arithmetic) -------
def keypair():
    private = secrets.randbelow(passkey._N - 1) + 1
    x, y = passkey._multiply(private, passkey._G)
    return private, x.to_bytes(32, "big"), y.to_bytes(32, "big")


def der(r: int, s: int) -> bytes:
    def integer(value):
        raw = value.to_bytes((value.bit_length() + 8) // 8, "big")
        return b"\x02" + bytes([len(raw)]) + raw
    body = integer(r) + integer(s)
    return b"\x30" + bytes([len(body)]) + body


def sign(private: int, message: bytes) -> bytes:
    digest = int.from_bytes(hashlib.sha256(message).digest(), "big")
    while True:
        k = secrets.randbelow(passkey._N - 1) + 1
        r = passkey._multiply(k, passkey._G)[0] % passkey._N
        s = pow(k, -1, passkey._N) * (digest + r * private) % passkey._N
        if r and s:
            return der(r, s)


# ---- minimal CBOR encoder for building test attestation objects ------------
def cbor(value) -> bytes:
    def head(major, length):
        if length < 24:
            return bytes([major << 5 | length])
        if length < 256:
            return bytes([major << 5 | 24, length])
        return bytes([major << 5 | 25]) + struct.pack(">H", length)
    if isinstance(value, bool):
        return bytes([0xF5 if value else 0xF4])
    if isinstance(value, int):
        return head(0, value) if value >= 0 else head(1, -1 - value)
    if isinstance(value, bytes):
        return head(2, len(value)) + value
    if isinstance(value, str):
        raw = value.encode()
        return head(3, len(raw)) + raw
    if isinstance(value, dict):
        return head(5, len(value)) + b"".join(cbor(k) + cbor(v) for k, v in value.items())
    raise TypeError(value)


def client_data(kind: str, challenge: str, origin: str = ORIGIN) -> str:
    return b64url_encode(json.dumps({"type": kind, "challenge": challenge, "origin": origin}).encode())


def auth_data(flags=0x05, count=0, rp_id=RP_ID, attested=b"") -> bytes:
    return hashlib.sha256(rp_id.encode()).digest() + bytes([flags]) + struct.pack(">I", count) + attested


def registration(x, y, challenge, credential_id=b"cred-1", origin=ORIGIN, rp_id=RP_ID, flags=0x45):
    cose = cbor({1: 2, 3: -7, -1: 1, -2: x, -3: y})
    attested = b"\x00" * 16 + struct.pack(">H", len(credential_id)) + credential_id + cose
    obj = cbor({"fmt": "none", "attStmt": {}, "authData": auth_data(flags, 0, rp_id, attested)})
    return client_data("webauthn.create", challenge, origin), b64url_encode(obj)


def assertion(private, challenge, count=0, origin=ORIGIN, flags=0x05):
    data = auth_data(flags, count)
    client = client_data("webauthn.get", challenge, origin)
    signature = sign(private, data + hashlib.sha256(b64url_decode(client)).digest())
    return client, b64url_encode(data), b64url_encode(signature)


class Es256Tests(unittest.TestCase):
    def test_rfc6979_p256_sha256_vector(self):
        # RFC 6979 A.2.5, P-256 / SHA-256 / message "sample".
        x = bytes.fromhex("60FED4BA255A9D31C961EB74C6356D68C049B8923B61FA6CE669622E60F29FB6")
        y = bytes.fromhex("7903FE1008B8BC99A41AE9E95628BC64F2F1B20C2D7E9F5177A3C294D4462299")
        r = int("EFD48B2AACB6A8FD1140DD9CD45E81D69D2C877B56AAF991C34D0EA84EAF3716", 16)
        s = int("F7CB1C942D657C41D436C7A1B6E29F65F3E900DBB9AFF4064DC4AB2F843ACDA8", 16)
        self.assertTrue(verify_es256(x, y, b"sample", der(r, s)))
        self.assertFalse(verify_es256(x, y, b"sampl3", der(r, s)))
        self.assertFalse(verify_es256(x, y, b"sample", der(r, (s + 1) % passkey._N)))

    def test_off_curve_key_is_rejected(self):
        self.assertFalse(verify_es256(b"\x01" * 32, b"\x02" * 32, b"m", der(1, 1)))


class RegistrationAndAssertionTests(unittest.TestCase):
    def setUp(self):
        self.private, self.x, self.y = keypair()

    def test_round_trip(self):
        client, attestation = registration(self.x, self.y, "c1")
        credential = verify_registration(client, attestation, challenge="c1", origin=ORIGIN, rp_id=RP_ID)
        self.assertEqual(b64url_decode(credential["id"]), b"cred-1")
        client, data, signature = assertion(self.private, "c2")
        self.assertEqual(verify_assertion(client, data, signature, challenge="c2", origin=ORIGIN,
                                          rp_id=RP_ID, x=credential["x"], y=credential["y"],
                                          stored_count=0), 0)

    def test_rejections(self):
        client, attestation = registration(self.x, self.y, "c1")
        cases = {
            "challenge": dict(challenge="other", origin=ORIGIN, rp_id=RP_ID),
            "origin": dict(challenge="c1", origin="https://evil.example", rp_id=RP_ID),
            "rp": dict(challenge="c1", origin=ORIGIN, rp_id="evil.example"),
        }
        for name, kwargs in cases.items():
            with self.subTest(name), self.assertRaises(PasskeyError):
                verify_registration(client, attestation, **kwargs)
        no_uv = registration(self.x, self.y, "c1", flags=0x41)
        with self.assertRaises(PasskeyError):
            verify_registration(*no_uv, challenge="c1", origin=ORIGIN, rp_id=RP_ID)
        other_private, _, _ = keypair()
        client, data, signature = assertion(other_private, "c2")
        with self.assertRaises(PasskeyError):  # signed by a different key
            verify_assertion(client, data, signature, challenge="c2", origin=ORIGIN, rp_id=RP_ID,
                             x=self.x, y=self.y, stored_count=0)
        client, data, signature = assertion(self.private, "c3", count=5)
        with self.assertRaises(PasskeyError):  # counter went backwards -> cloned key
            verify_assertion(client, data, signature, challenge="c3", origin=ORIGIN, rp_id=RP_ID,
                             x=self.x, y=self.y, stored_count=9)


class StoreTests(unittest.TestCase):
    def setUp(self):
        import tempfile
        from pathlib import Path
        from trading_helper.remote_control import RemoteStore
        self.temp = tempfile.TemporaryDirectory()
        self.store = RemoteStore(Path(self.temp.name) / "remote.db")

    def tearDown(self):
        self.store.db.close()
        self.temp.cleanup()

    def test_relink_keeps_one_device_and_the_other_sign_in(self):
        """Face ID in Safari must not sign the home-screen app out (and back)."""
        device, old = self.store.pair("我的手機", ORIGIN)
        self.store.add_passkey(device, {"id": "cid", "x": b"x" * 32, "y": b"y" * 32, "sign_count": 0}, ORIGIN)
        self.assertTrue(self.store.has_passkey(device))
        new = self.store.relink(device, "cid", 0)
        self.assertEqual(len(self.store.devices()), 1)
        self.assertEqual(self.store.authenticate(new, ORIGIN), device)
        self.assertEqual(self.store.authenticate(old, ORIGIN), device)
        newer = self.store.relink(device, "cid", 1)
        self.assertEqual(self.store.authenticate(new, ORIGIN), device)   # both stay
        self.assertEqual(self.store.authenticate(newer, ORIGIN), device)
        for count in range(2, 8):                                        # only a few kept
            self.store.relink(device, "cid", count)
        self.assertIsNone(self.store.authenticate(new, ORIGIN))
        self.store.revoke(device)                                        # removal ends all
        self.assertIsNone(self.store.authenticate(old, ORIGIN))

    def test_removed_device_cannot_come_back_with_face_id(self):
        device, _ = self.store.pair("我的手機", ORIGIN)
        self.store.add_passkey(device, {"id": "cid", "x": b"x" * 32, "y": b"y" * 32, "sign_count": 0}, ORIGIN)
        self.store.revoke(device)
        self.assertIsNone(self.store.passkey("cid"))
        with self.assertRaises(ValueError):
            self.store.relink(device, "cid", 0)


class PasskeyEndpointTests(unittest.TestCase):
    """Full HTTPS-origin flow through the real MobileServer request handler."""

    @classmethod
    def setUpClass(cls):
        from PySide6.QtWidgets import QApplication
        cls.qtapp = QApplication.instance() or QApplication([])

    def setUp(self):
        import test_mobile_remote as fixtures
        self.case = fixtures.MobileTransportTests("test_listener_is_loopback_and_static_assets_have_security_headers")
        self.case.qtapp = self.qtapp
        self.case.setUp()
        self.addCleanup(self.case.tearDown)
        self.server, self.store = self.case.server, self.case.store
        self.server.public_origin = ORIGIN
        self.headers = {"Host": RP_ID, "Origin": ORIGIN, "Content-Type": "application/json"}

    def post(self, path, body=None, cookie=None):
        headers = dict(self.headers, **({"Cookie": cookie} if cookie else {}))
        return self.case.http("POST", path, json.dumps(body or {}), headers)

    def test_pair_register_then_face_id_relinks_same_device(self):
        status, headers, _ = self.case.http(
            "POST", "/api/pair", json.dumps({"code": self.server.arm_pairing(), "name": "我的手機"}), self.headers)
        self.assertEqual(status, 200)
        cookie = headers["Set-Cookie"].split(";")[0]
        status, _, body = self.case.http("GET", "/api/session", headers={"Host": RP_ID, "Cookie": cookie})
        self.assertEqual(json.loads(body), {"paired": True, "passkey": False})

        status, _, body = self.post("/api/passkey/register/options", cookie=cookie)
        self.assertEqual(status, 200)
        options = json.loads(body)
        self.assertEqual(options["rpId"], RP_ID)
        private, x, y = keypair()
        client, attestation = registration(x, y, options["challenge"], credential_id=b"phone-key")
        status, _, body = self.post("/api/passkey/register",
                                    {"clientDataJSON": client, "attestationObject": attestation}, cookie)
        self.assertEqual(status, 200, body)

        # Home-screen app deleted: no cookie any more. Face ID instead of a code.
        status, _, body = self.post("/api/passkey/login/options")
        challenge = json.loads(body)["challenge"]
        client, data, signature = assertion(private, challenge)
        status, headers, body = self.post("/api/passkey/login", {
            "id": b64url_encode(b"phone-key"), "clientDataJSON": client,
            "authenticatorData": data, "signature": signature})
        self.assertEqual(status, 200, body)
        self.assertIn("; Secure", headers["Set-Cookie"])
        new_cookie = headers["Set-Cookie"].split(";")[0]
        status, _, body = self.case.http("GET", "/api/session", headers={"Host": RP_ID, "Cookie": new_cookie})
        self.assertEqual(json.loads(body), {"paired": True, "passkey": True})
        self.assertEqual(len(self.store.devices()), 1)  # no duplicate device

        # The same challenge cannot be replayed.
        status, _, _ = self.post("/api/passkey/login", {
            "id": b64url_encode(b"phone-key"), "clientDataJSON": client,
            "authenticatorData": data, "signature": signature})
        self.assertEqual(status, 400)

    def test_registration_requires_a_paired_session_and_https(self):
        self.assertEqual(self.post("/api/passkey/register/options")[0], 401)
        self.server.public_origin = ""
        status, _, _ = self.case.http("POST", "/api/passkey/login/options", "{}",
                                      {"Origin": self.server.local_origin, "Content-Type": "application/json"})
        self.assertEqual(status, 400)


if __name__ == "__main__":
    unittest.main()
