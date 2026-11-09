"""Ed25519 signature verification (RFC 8032), standard library only.

Decky does not bundle third-party Python packages into a plugin's runtime, so
the signed plugin manifest has to be verifiable on a stock Steam Deck. When
`cryptography` is importable it is used (fast and widely trusted); otherwise
this module verifies in pure Python. Both paths check the same RFC 8032
equation and never skip it: a manifest that cannot be verified is not used.

The pure-Python path is the classic curve25519 reference arithmetic, written
iteratively so a verification stays fast enough for a once-per-cache-window
check.
"""

import hashlib
import logging

logger = logging.getLogger("assella_shared.ed25519")

_Q = 2 ** 255 - 19
_L = 2 ** 252 + 27742317777372353535851937790883648493
_D = (-121665 * pow(121666, _Q - 2, _Q)) % _Q
_I = pow(2, (_Q - 1) // 4, _Q)


def _inv(x: int) -> int:
    return pow(x, _Q - 2, _Q)


def _sha512(data: bytes) -> bytes:
    return hashlib.sha512(data).digest()


def _x_recover(y: int) -> int:
    xx = (y * y - 1) * _inv(_D * y * y + 1)
    x = pow(xx, (_Q + 3) // 8, _Q)
    if (x * x - xx) % _Q != 0:
        x = (x * _I) % _Q
    if x % 2 != 0:
        x = _Q - x
    return x


_BY = 4 * _inv(5) % _Q
_BX = _x_recover(_BY)
_B = (_BX % _Q, _BY % _Q)
_IDENTITY = (0, 1)


def _add(p, q):
    """Affine Edwards-curve addition."""
    x1, y1 = p
    x2, y2 = q
    k = (_D * x1 * x2 * y1 * y2) % _Q
    x3 = (x1 * y2 + x2 * y1) * _inv(1 + k) % _Q
    y3 = (y1 * y2 + x1 * x2) * _inv(1 - k) % _Q
    return (x3 % _Q, y3 % _Q)


def _mul(point, exponent: int):
    """Scalar multiplication by double-and-add, iterative to avoid recursion."""
    result = _IDENTITY
    addend = point
    while exponent > 0:
        if exponent & 1:
            result = _add(result, addend)
        addend = _add(addend, addend)
        exponent >>= 1
    return result


def _decode_point(data: bytes):
    """Decode a 32-byte compressed point, or None when it is not on the curve."""
    if len(data) != 32:
        return None
    value = int.from_bytes(data, "little")
    y = value & ((1 << 255) - 1)
    x = _x_recover(y)
    if (x & 1) != ((value >> 255) & 1):
        x = _Q - x
    if (-x * x + y * y - 1 - _D * x * x * y * y) % _Q != 0:
        return None
    return (x, y)


def _encode_point(point) -> bytes:
    x, y = point
    bits = [(y >> i) & 1 for i in range(255)] + [x & 1]
    return bytes(sum(bits[8 * i + j] << j for j in range(8)) for i in range(32))


def _verify_pure(public_key: bytes, signature: bytes, message: bytes) -> bool:
    r_bytes = signature[:32]
    s = int.from_bytes(signature[32:], "little")
    # Reject the malleable half of the scalar range (RFC 8032 §5.1.7).
    if s >= _L:
        return False
    a = _decode_point(public_key)
    r = _decode_point(r_bytes)
    if a is None or r is None:
        return False
    h = int.from_bytes(_sha512(r_bytes + public_key + message), "little") % _L
    # [S]B == R + [h]A
    return _encode_point(_mul(_B, s)) == _encode_point(_add(r, _mul(a, h)))


def verify(public_key: bytes, signature: bytes, message: bytes) -> bool:
    """True when `signature` is a valid Ed25519 signature of `message` by `public_key`."""
    if len(public_key) != 32 or len(signature) != 64:
        return False
    try:
        from cryptography.exceptions import InvalidSignature
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    except Exception:  # noqa: BLE001 - no backend, use the stdlib implementation
        return _verify_pure(public_key, signature, message)
    try:
        Ed25519PublicKey.from_public_bytes(public_key).verify(signature, message)
        return True
    except InvalidSignature:
        return False
    except Exception as exc:  # noqa: BLE001 - a broken backend must not fail open
        logger.debug("cryptography Ed25519 verify errored (%s); using pure Python", exc)
        return _verify_pure(public_key, signature, message)
