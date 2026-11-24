"""Minimal WebAuthn (passkey) verification for re-linking a paired phone.

Only what this app needs: ES256 (P-256) credentials, attestation "none",
user verification required. A passkey lives in the phone's keychain, so the
same phone can reconnect with Face ID after its home-screen app was deleted,
keeping ONE device entry instead of adding a new one.
"""
from __future__ import annotations

import base64
import hashlib
import json
import struct

FLAG_USER_PRESENT = 0x01
FLAG_USER_VERIFIED = 0x04
FLAG_ATTESTED_DATA = 0x40


class PasskeyError(ValueError):
    pass


def b64url_encode(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_decode(text: str) -> bytes:
    if not isinstance(text, str) or len(text) > 4096:
        raise PasskeyError("通行密鑰資料格式不正確。")
    try:
        return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))
    except (ValueError, TypeError) as exc:
        raise PasskeyError("通行密鑰資料格式不正確。") from exc


def cbor_decode(data: bytes):
    """Decode one CBOR item (the subset WebAuthn uses); returns (value, rest)."""
    def read(offset):
        if offset >= len(data):
            raise PasskeyError("通行密鑰資料不完整。")
        initial = data[offset]
        major, info = initial >> 5, initial & 0x1F
        offset += 1
        if info < 24:
            value = info
        elif info in (24, 25, 26, 27):
            size = 1 << (info - 24)
            if offset + size > len(data):
                raise PasskeyError("通行密鑰資料不完整。")
            value = int.from_bytes(data[offset:offset + size], "big")
            offset += size
        else:
            raise PasskeyError("不支援的通行密鑰資料。")
        if major == 0:
            return value, offset
        if major == 1:
            return -1 - value, offset
        if major in (2, 3):
            if offset + value > len(data):
                raise PasskeyError("通行密鑰資料不完整。")
            chunk = data[offset:offset + value]
            return (chunk if major == 2 else chunk.decode("utf-8")), offset + value
        if major == 4:
            items = []
            for _ in range(value):
                item, offset = read(offset)
                items.append(item)
            return items, offset
        if major == 5:
            mapping = {}
            for _ in range(value):
                key, offset = read(offset)
                item, offset = read(offset)
                mapping[key] = item
            return mapping, offset
        if major == 7 and info in (20, 21, 22):
            return {20: False, 21: True, 22: None}[info], offset
        raise PasskeyError("不支援的通行密鑰資料。")

    value, end = read(0)
    return value, data[end:]


def _client_data(client_data_b64: str, expected_type: str, challenge: str, origin: str) -> bytes:
    raw = b64url_decode(client_data_b64)
    try:
        client = json.loads(raw)
    except ValueError as exc:
        raise PasskeyError("通行密鑰資料格式不正確。") from exc
    if client.get("type") != expected_type:
        raise PasskeyError("通行密鑰用途不符。")
    if client.get("challenge") != challenge:
        raise PasskeyError("通行密鑰驗證已過期，請再試一次。")
    if client.get("origin") != origin:
        raise PasskeyError("通行密鑰來源網址不符。")
    return raw


def _check_flags_and_rp(auth_data: bytes, rp_id: str) -> tuple[int, int]:
    if len(auth_data) < 37:
        raise PasskeyError("通行密鑰資料不完整。")
    if auth_data[:32] != hashlib.sha256(rp_id.encode("utf-8")).digest():
        raise PasskeyError("通行密鑰不屬於這個網址。")
    flags = auth_data[32]
    if not flags & FLAG_USER_PRESENT or not flags & FLAG_USER_VERIFIED:
        raise PasskeyError("需要 Face ID／指紋驗證才能使用通行密鑰。")
    sign_count = struct.unpack(">I", auth_data[33:37])[0]
    return flags, sign_count


def verify_registration(client_data_b64: str, attestation_b64: str, *,
                        challenge: str, origin: str, rp_id: str) -> dict:
    """Validate a new passkey; returns its id, P-256 key and sign count."""
    _client_data(client_data_b64, "webauthn.create", challenge, origin)
    attestation, _ = cbor_decode(b64url_decode(attestation_b64))
    if not isinstance(attestation, dict) or not isinstance(attestation.get("authData"), bytes):
        raise PasskeyError("通行密鑰資料格式不正確。")
    auth_data = attestation["authData"]
    flags, sign_count = _check_flags_and_rp(auth_data, rp_id)
    if not flags & FLAG_ATTESTED_DATA or len(auth_data) < 55:
        raise PasskeyError("通行密鑰資料不完整。")
    id_length = struct.unpack(">H", auth_data[53:55])[0]
    credential_id = auth_data[55:55 + id_length]
    if len(credential_id) != id_length or not credential_id:
        raise PasskeyError("通行密鑰資料不完整。")
    key, _ = cbor_decode(auth_data[55 + id_length:])
    # COSE EC2 key: kty 2, alg -7 (ES256), crv 1 (P-256), x, y.
    if (not isinstance(key, dict) or key.get(1) != 2 or key.get(3) != -7 or key.get(-1) != 1
            or not isinstance(key.get(-2), bytes) or not isinstance(key.get(-3), bytes)
            or len(key[-2]) != 32 or len(key[-3]) != 32):
        raise PasskeyError("這支手機的通行密鑰類型不支援。")
    return {"id": b64url_encode(credential_id), "x": key[-2], "y": key[-3], "sign_count": sign_count}


# --- ECDSA P-256 (secp256r1) verification, standard curve constants. -------
# Pure Python so LAB needs no extra package; verification uses public data only.
_P = 0xffffffff00000001000000000000000000000000ffffffffffffffffffffffff
_A = _P - 3
_B = 0x5ac635d8aa3a93e7b3ebbd55769886bc651d06b0cc53b0f63bce3c3e27d2604b
_N = 0xffffffff00000000ffffffffffffffffbce6faada7179e84f3b9cac2fc632551
_G = (0x6b17d1f2e12c4247f8bce6e563a440f277037d812deb33a0f4a13945d898c296,
      0x4fe342e2fe1a7f9b8ee7eb4a7c0f9e162bce33576b315ececbb6406837bf51f5)


def _on_curve(point) -> bool:
    x, y = point
    return 0 <= x < _P and 0 <= y < _P and (y * y - (x * x * x + _A * x + _B)) % _P == 0


def _add(p1, p2):
    if p1 is None:
        return p2
    if p2 is None:
        return p1
    (x1, y1), (x2, y2) = p1, p2
    if x1 == x2 and (y1 + y2) % _P == 0:
        return None
    if p1 == p2:
        slope = (3 * x1 * x1 + _A) * pow(2 * y1, -1, _P) % _P
    else:
        slope = (y2 - y1) * pow(x2 - x1, -1, _P) % _P
    x3 = (slope * slope - x1 - x2) % _P
    return x3, (slope * (x1 - x3) - y1) % _P


def _multiply(k: int, point):
    result = None
    while k:
        if k & 1:
            result = _add(result, point)
        point = _add(point, point)
        k >>= 1
    return result


def _der_signature(signature: bytes) -> tuple[int, int]:
    """Parse an ASN.1 DER ECDSA signature: SEQUENCE { INTEGER r, INTEGER s }."""
    def integer(offset):
        if offset + 2 > len(signature) or signature[offset] != 0x02:
            raise PasskeyError("通行密鑰簽章格式不正確。")
        length = signature[offset + 1]
        start = offset + 2
        if not 0 < length <= 33 or start + length > len(signature):
            raise PasskeyError("通行密鑰簽章格式不正確。")
        return int.from_bytes(signature[start:start + length], "big"), start + length

    if len(signature) < 8 or signature[0] != 0x30 or signature[1] != len(signature) - 2:
        raise PasskeyError("通行密鑰簽章格式不正確。")
    r, offset = integer(2)
    s, offset = integer(offset)
    if offset != len(signature):
        raise PasskeyError("通行密鑰簽章格式不正確。")
    return r, s


def verify_es256(x: bytes, y: bytes, message: bytes, signature: bytes) -> bool:
    public = (int.from_bytes(x, "big"), int.from_bytes(y, "big"))
    if not _on_curve(public):
        return False
    r, s = _der_signature(signature)
    if not (1 <= r < _N and 1 <= s < _N):
        return False
    digest = int.from_bytes(hashlib.sha256(message).digest(), "big")
    w = pow(s, -1, _N)
    point = _add(_multiply(digest * w % _N, _G), _multiply(r * w % _N, public))
    return point is not None and point[0] % _N == r


def verify_assertion(client_data_b64: str, auth_data_b64: str, signature_b64: str, *,
                     challenge: str, origin: str, rp_id: str,
                     x: bytes, y: bytes, stored_count: int) -> int:
    """Check a Face ID sign-in against the stored key; returns the new count."""
    client_raw = _client_data(client_data_b64, "webauthn.get", challenge, origin)
    auth_data = b64url_decode(auth_data_b64)
    _, sign_count = _check_flags_and_rp(auth_data, rp_id)
    if (sign_count or stored_count) and sign_count <= stored_count:
        raise PasskeyError("通行密鑰可能被複製使用，已拒絕。")
    signed = auth_data + hashlib.sha256(client_raw).digest()
    if not verify_es256(x, y, signed, b64url_decode(signature_b64)):
        raise PasskeyError("通行密鑰驗證失敗。")
    return sign_count
