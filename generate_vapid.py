"""
Одноразовый скрипт для генерации VAPID-ключей.
Запусти: python generate_vapid.py
Скопируй результат в .env
"""
try:
    from py_vapid import Vapid
except ImportError:
    print("Установи: pip install py-vapid")
    raise SystemExit(1)

v = Vapid()
v.generate_keys()

pub = v.public_key.public_bytes(
    __import__("cryptography.hazmat.primitives.serialization", fromlist=["Encoding", "PublicFormat"])
        .Encoding.X962,
    __import__("cryptography.hazmat.primitives.serialization", fromlist=["PublicFormat"])
        .PublicFormat.UncompressedPoint
)

import base64
pub_b64 = base64.urlsafe_b64encode(pub).rstrip(b"=").decode()
priv_pem = v.private_key_pem.decode().strip()

print("\n── Скопируй в .env ──────────────────────────────────")
print(f"VAPID_PUBLIC_KEY={pub_b64}")
print(f"VAPID_PRIVATE_KEY={priv_pem}")
print(f"VAPID_CLAIMS_EMAIL=admin@study1409.ru")
print("─────────────────────────────────────────────────────\n")
