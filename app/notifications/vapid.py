from __future__ import annotations

import base64

from cryptography.hazmat.primitives import serialization
from py_vapid import Vapid02


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def generate_vapid_keypair() -> tuple[str, str]:
    """Returns (public_key, private_key) as raw base64url strings.

    The public key is handed to the browser as `applicationServerKey`; the
    private key is passed straight to `pywebpush.webpush()`, which accepts
    this raw base64url form directly.
    """
    v = Vapid02()
    v.generate_keys()
    private_raw = v.private_key.private_numbers().private_value.to_bytes(32, "big")
    public_raw = v.public_key.public_bytes(
        serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
    )
    return _b64url(public_raw), _b64url(private_raw)
