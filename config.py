import os
from pathlib import Path

BASE_DIR = Path(__file__).parent

class Config:
    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    DATABASE = os.environ.get("DATABASE", str(BASE_DIR / "database.db"))
    VAPID_PRIVATE_KEY = os.environ.get("VAPID_PRIVATE_KEY", str(BASE_DIR / "vapid_private.pem"))
    VAPID_PUBLIC_KEY = os.environ.get("VAPID_PUBLIC_KEY", str(BASE_DIR / "vapid_public.txt"))
    VAPID_SUBJECT = os.environ.get("VAPID_SUBJECT", "mailto:admin@example.com")
    TIMEZONE = os.environ.get("TIMEZONE", "Asia/Kolkata")