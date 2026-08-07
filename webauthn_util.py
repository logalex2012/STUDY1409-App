"""WebAuthn (FIDO2) helpers for STUDENT1409.

Supports login via platform authenticator: Face ID / Touch ID / screen
lock (Windows Hello etc.). Uses `cbor2` for COSE/CBOR and `cryptography`
for P-256 signature verification.
"""
import base64
import hashlib
import json
import os
from datetime import datetime, timedelta, timezone

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec


# ── base64url ──────────────────────────────────────────────────
def b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def b64url_bytes(s: str) -> bytes:
    pad = "=" * ((4 - len(s) % 4) % 4)
    return base64.urlsafe_b64decode(s + pad)


# ── challenges ────────────────────────────────────────────────
def new_challenge() -> str:
    """Generate a fresh 32-byte WebAuthn challenge (base64url)."""
    return b64url(os.urandom(32))


# ── COSE → P-256 public key ────────────────────────────────────
def decode_cose_pubkey(cose: dict):
    """Convert a COSE_Key (EC2 P-256, alg -7) into an EC public key object."""
    kty = cose.get(1)   # 2 = EC2
    alg = cose.get(3)   # -7 = ES256
    if kty != 2 or alg != -7:
        raise ValueError(f"unsupported COSE key: kty={kty} alg={alg}")
    x = cose.get(-1)
    y = cose.get(-2)
    if not x or not y:
        raise ValueError("missing x/y in COSE key")
    numbers = ec.EllipticCurvePublicNumbers(
        int.from_bytes(bytes(x), "big"),
        int.from_bytes(bytes(y), "big"),
        ec.SECP256R1(),
    )
    return numbers.public_key()


# ── clientDataJSON ─────────────────────────────────────────────
def parse_client_data(raw: bytes) -> dict:
    """clientDataJSON is raw JSON (NOT CBOR) in WebAuthn."""
    return json.loads(raw.decode("utf-8"))


def client_data_hash(client_raw: bytes) -> bytes:
    return hashlib.sha256(client_raw).digest()


# ── authenticatorData ──────────────────────────────────────────
def parse_auth_data(auth: bytes):
    """Return (flags, sign_count, attested_cred_id, cose_key).

    attested fields are None when the AT flag (0x40) is not set.
    """
    if len(auth) < 37:
        raise ValueError("authenticatorData too short")
    flags = auth[32]
    sign_count = int.from_bytes(auth[33:37], "big")
    cred_id = None
    cose = None
    if flags & 0x40:  # Attested Credential Data present
        pos = 37
        # aaguid (16 bytes) -> skip
        pos += 16
        cred_len = int.from_bytes(auth[pos:pos + 2], "big")
        pos += 2
        cred_id = auth[pos:pos + cred_len]
        pos += cred_len
        import cbor2
        cose, _ = cbor2.loads(auth[pos:])
    return flags, sign_count, cred_id, cose


# ── signature ──────────────────────────────────────────────────
def verify_signature(pubkey, auth_data: bytes, client_data_hash_bytes: bytes,
                     signature_b64url: str) -> bool:
    """Verify ES256 signature over SHA-256(authData || clientDataHash)."""
    try:
        sig = b64url_bytes(signature_b64url)
        signed_bytes = auth_data + client_data_hash_bytes
        pubkey.verify(sig, signed_bytes, ec.ECDSA(hashes.SHA256()))
        return True
    except Exception:
        return False


# ── session / challenge helpers ────────────────────────────────
def expiry_pass(ts: float, ttl: int = 300) -> bool:
    """True if ts is older than ttl seconds."""
    return time.time() - ts > ttl


def dt_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")