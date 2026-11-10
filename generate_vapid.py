"""Generate VAPID keys ONCE. Do not commit vapid_private.pem to git."""

import base64
from pathlib import Path
from py_vapid import Vapid01
from cryptography.hazmat.primitives.serialization import (
    load_pem_private_key, Encoding, PublicFormat,
)

BASE = Path(__file__).parent
PRIV = BASE / "vapid_private.pem"
PUB = BASE / "vapid_public.txt"

if PRIV.exists() and PUB.exists():
    print("VAPID keys already exist — nothing to do.")
    raise SystemExit(0)

vapid = Vapid01()
vapid.generate_keys()
vapid.save_key(str(PRIV))

# Derive public key from the private PEM (uncompressed point, base64url)
with open(PRIV, "rb") as f:
    priv = load_pem_private_key(f.read(), password=None)

raw_pub = priv.public_key().public_bytes(Encoding.X962, PublicFormat.UncompressedPoint)
b64 = base64.urlsafe_b64encode(raw_pub).rstrip(b"=").decode()
PUB.write_text(b64)

print("VAPID keys generated:")
print("  vapid_private.pem  (keep secret)")
print("  vapid_public.txt   (public, base64url)")