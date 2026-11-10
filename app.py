"""
StickyMind — Flask backend (Render Fixed)
"""

import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from apscheduler.schedulers.background import BackgroundScheduler
from flask import Flask, jsonify, render_template, request, send_from_directory
from pywebpush import WebPushException, webpush

from config import Config

app = Flask(__name__)
app.config.from_object(Config)


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
@contextmanager
def get_db():
    db_path = app.config["DATABASE"]
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except PermissionError:
            app.logger.error(f"Permission denied creating database directory: {db_dir}")
            raise

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS notes (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                title         TEXT NOT NULL DEFAULT '',
                content       TEXT NOT NULL DEFAULT '',
                category      TEXT NOT NULL DEFAULT 'Personal',
                color         TEXT NOT NULL DEFAULT 'yellow',
                pinned        INTEGER NOT NULL DEFAULT 0,
                reminder_at   TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                created_at    TEXT NOT NULL,
                updated_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint   TEXT UNIQUE NOT NULL,
                p256dh     TEXT NOT NULL,
                auth       TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            """
        )

init_db()

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
VALID_COLORS = {"yellow", "pink", "blue", "green", "purple"}
VALID_CATEGORIES = {"Study", "Work", "Personal"}

def now_iso():
    return datetime.now(ZoneInfo(app.config["TIMEZONE"])).isoformat()

def normalize_datetime(value):
    if not value: return None
    try:
        v = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
    except Exception: return None
    tz = ZoneInfo(app.config["TIMEZONE"])
    if dt.tzinfo is None: dt = dt.replace(tzinfo=tz)
    else: dt = dt.astimezone(tz)
    return dt.isoformat()

def row_to_note(row):
    n = dict(row)
    n["pinned"] = bool(n["pinned"])
    n["reminder_sent"] = bool(n["reminder_sent"])
    return n

# ---------------------------------------------------------------------------
# Pages & PWA
# ---------------------------------------------------------------------------
@app.route("/")
def index(): return render_template("index.html")

@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(app.static_folder, "service-worker.js", mimetype="application/javascript")

# ---------------------------------------------------------------------------
# Web Push - FIXED FOR RENDER
# ---------------------------------------------------------------------------
@app.route("/api/vapid-public-key")
def vapid_public_key():
    # Try to read from env var first (Render), then file (Local)
    key_content = os.environ.get("VAPID_PUBLIC_KEY_CONTENT")
    if key_content:
        return jsonify({"publicKey": key_content.strip()})
        
    path = app.config["VAPID_PUBLIC_KEY"]
    if os.path.exists(path):
        with open(path) as f:
            return jsonify({"publicKey": f.read().strip()})
            
    app.logger.error("VAPID public key missing entirely!")
    return jsonify({"error": "VAPID public key missing. Check Render Environment Variables."}), 500

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    data = request.get_json(silent=True) or {}
    sub = data.get("subscription") or {}
    endpoint = sub.get("endpoint")
    keys = sub.get("keys") or {}
    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not (endpoint and p256dh and auth):
        return jsonify({"error": "Invalid subscription payload"}), 400

    with get_db() as conn:
        conn.execute(
            """INSERT OR REPLACE INTO push_subscriptions (endpoint, p256dh, auth, created_at) VALUES (?, ?, ?, ?)""",
            (endpoint, p256dh, auth, now_iso()),
        )
    return jsonify({"ok": True})

@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("subscription") or {}).get("endpoint") or data.get("endpoint")
    if not endpoint: return jsonify({"error": "Missing endpoint"}), 400
    with get_db() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))
    return jsonify({"ok": True})

def send_push_to_all(payload: dict) -> int:
    # Try env var first (Render), then file (Local)
    priv = os.environ.get("VAPID_PRIVATE_KEY_CONTENT")
    
    if not priv:
        priv_path = app.config["VAPID_PRIVATE_KEY"]
        if os.path.exists(priv_path):
            with open(priv_path) as f:
                priv = f.read()
        else:
            app.logger.warning("VAPID private key missing.")
            return 0

    with get_db() as conn:
        subs = conn.execute("SELECT * FROM push_subscriptions").fetchall()

    if not subs: return 0

    sent = 0
    expired = []

    for sub in subs:
        info = {
            "endpoint": sub["endpoint"],
            "keys": {"p256dh": sub["p256dh"], "auth": sub["auth"]},
        }
        parsed_endpoint = urlparse(sub["endpoint"])
        audience = f"{parsed_endpoint.scheme}://{parsed_endpoint.netloc}"
        
        try:
            webpush(
                subscription_info=info,
                data=json.dumps(payload),
                vapid_private_key=priv,
                vapid_claims={"sub": app.config["VAPID_SUBJECT"], "aud": audience},
                ttl=86400,
            )
            sent += 1
        except WebPushException as e:
            status = getattr(e.response, "status_code", None)
            if status in (400, 404, 410):
                expired.append(sub["endpoint"])
                app.logger.warning(f"Removing invalid subscription: {sub['endpoint']}")
            app.logger.warning("push failed (%s): %s", status, e)

    if expired:
        with get_db() as conn:
            for ep in expired:
                conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (ep,))
    return sent

def check_reminders():
    tz = ZoneInfo(app.config["TIMEZONE"])
    now_dt = datetime.now(tz)
    with get_db() as conn:
        rows = conn.execute("SELECT * FROM notes WHERE reminder_at IS NOT NULL AND reminder_sent = 0").fetchall()
        for row in rows:
            note = dict(row)
            try:
                reminder_dt = datetime.fromisoformat(note["reminder_at"].replace("Z", "+00:00"))
            except Exception: continue
            if reminder_dt.tzinfo is None: reminder_dt = reminder_dt.replace(tzinfo=tz)
            if reminder_dt > now_dt: continue
            
            body = (note["content"] or "").strip()
            send_push_to_all({
                "title": note["title"] or "StickyMind Reminder",
                "body": body[:140] if body else "You have a reminder",
                "note_id": note["id"],
            })
            conn.execute("UPDATE notes SET reminder_sent = 1 WHERE id=?", (note["id"],))

_scheduler = None
def start_scheduler():
    global _scheduler
    if _scheduler is not None: return _scheduler
    _scheduler = BackgroundScheduler(timezone=app.config["TIMEZONE"])
    _scheduler.add_job(check_reminders, "interval", seconds=30, id="reminders")
    _scheduler.start()
    return _scheduler

start_scheduler()

# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)