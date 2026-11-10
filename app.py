"""
StickyMind — Flask backend
Run: python app.py
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
    """Yield a SQLite connection, commit on success, close always."""
    db_path = app.config["DATABASE"]
    
    # FIX: Only try to create the directory if it's a path and doesn't exist.
    # This prevents permission errors on Render's read-only filesystems.
    db_dir = os.path.dirname(db_path)
    if db_dir and not os.path.exists(db_dir):
        try:
            os.makedirs(db_dir, exist_ok=True)
        except PermissionError:
            # If we can't create the dir, fail gracefully
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
    """Parse any ISO-ish string → Asia/Kolkata ISO string (or None)."""
    if not value:
        return None
    try:
        v = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(v)
    except Exception:
        return None
    tz = ZoneInfo(app.config["TIMEZONE"])
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=tz)
    else:
        dt = dt.astimezone(tz)
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
def index():
    return render_template("index.html")


@app.route("/service-worker.js")
def service_worker():
    """Serve SW from root so its scope covers the whole app."""
    return send_from_directory(
        app.static_folder,
        "service-worker.js",
        mimetype="application/javascript",
    )


@app.route("/api/health")
def health():
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# Notes CRUD
# ---------------------------------------------------------------------------
@app.route("/api/notes", methods=["GET"])
def list_notes():
    q = request.args.get("q", "").strip()
    category = request.args.get("category", "").strip()
    pinned = request.args.get("pinned")

    sql = "SELECT * FROM notes WHERE 1=1"
    params = []

    if q:
        sql += " AND (title LIKE ? OR content LIKE ?)"
        params += [f"%{q}%", f"%{q}%"]
    if category and category != "all":
        sql += " AND category = ?"
        params.append(category)
    if pinned == "1":
        sql += " AND pinned = 1"

    sql += " ORDER BY pinned DESC, created_at DESC"

    with get_db() as conn:
        rows = conn.execute(sql, params).fetchall()

    return jsonify([row_to_note(r) for r in rows])


@app.route("/api/notes/<int:note_id>", methods=["GET"])
def get_note(note_id):
    with get_db() as conn:
        row = conn.execute("SELECT * FROM notes WHERE id=?", (note_id,)).fetchone()
    if not row:
        return jsonify({"error": "Note not found"}), 404
    return jsonify(row_to_note(row))


@app.route("/api/notes", methods=["POST"])
def create_note():
    data = request.get_json(silent=True) or {}
    title = (data.get("title") or "").strip()[:100]
    content = (data.get("content") or "").strip()[:5000]

    if not title and not content:
        return jsonify({"error": "Title or content is required"}), 400

    category = data.get("category")
    if category not in VALID_CATEGORIES:
        category = "Personal"

    color = data.get("color")
    if color not in VALID_COLORS:
        color = "yellow"

    reminder_at = normalize_datetime(data.get("reminder_at"))
    ts = now_iso()

    with get_db() as conn:
        cur = conn.execute(
            """INSERT INTO notes
               (title, content, category, color, pinned,
                reminder_at, reminder_sent, created_at, updated_at)
               VALUES (?, ?, ?, ?, 0, ?, 0, ?, ?)""",
            (title, content, category, color, reminder_at, ts, ts),
        )
        new_id = cur.lastrowid

    return get_note(new_id), 201


@app.route("/api/notes/<int:note_id>", methods=["PUT"])
def update_note(note_id):
    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM notes WHERE id=?", (note_id,)
        ).fetchone()

    if not existing:
        return jsonify({"error": "Note not found"}), 404

    data = request.get_json(silent=True) or {}
    note = dict(existing)

    if "title" in data:
        note["title"] = (data["title"] or "").strip()[:100]
    if "content" in data:
        note["content"] = (data["content"] or "").strip()[:5000]
    if data.get("category") in VALID_CATEGORIES:
        note["category"] = data["category"]
    if data.get("color") in VALID_COLORS:
        note["color"] = data["color"]
    if "pinned" in data:
        note["pinned"] = 1 if data["pinned"] else 0

    if "reminder_at" in data:
        new_reminder = normalize_datetime(data.get("reminder_at"))
        if new_reminder != note["reminder_at"]:
            note["reminder_sent"] = 0  # reset so it fires again
        note["reminder_at"] = new_reminder

    note["updated_at"] = now_iso()

    with get_db() as conn:
        conn.execute(
            """UPDATE notes
               SET title=?, content=?, category=?, color=?,
                   pinned=?, reminder_at=?, reminder_sent=?, updated_at=?
               WHERE id=?""",
            (
                note["title"], note["content"], note["category"], note["color"],
                note["pinned"], note["reminder_at"], note["reminder_sent"],
                note["updated_at"], note_id,
            ),
        )

    return get_note(note_id)


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    with get_db() as conn:
        cur = conn.execute("DELETE FROM notes WHERE id=?", (note_id,))
    if cur.rowcount == 0:
        return jsonify({"error": "Note not found"}), 404
    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Web Push
# ---------------------------------------------------------------------------
@app.route("/api/vapid-public-key")
def vapid_public_key():
    path = app.config["VAPID_PUBLIC_KEY"]
    if not os.path.exists(path):
        app.logger.error(f"VAPID public key missing at: {path}")
        return jsonify({
            "error": "VAPID public key missing on server. Check Render Secret Files."
        }), 500
    with open(path) as f:
        return jsonify({"publicKey": f.read().strip()})


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
            """INSERT OR REPLACE INTO push_subscriptions
               (endpoint, p256dh, auth, created_at)
               VALUES (?, ?, ?, ?)""",
            (endpoint, p256dh, auth, now_iso()),
        )

    return jsonify({"ok": True})


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    data = request.get_json(silent=True) or {}
    endpoint = (data.get("subscription") or {}).get("endpoint") or data.get("endpoint")
    if not endpoint:
        return jsonify({"error": "Missing endpoint"}), 400

    with get_db() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint=?", (endpoint,))

    return jsonify({"ok": True})


# ---------------------------------------------------------------------------
# Push sender + reminder scheduler
# ---------------------------------------------------------------------------
def send_push_to_all(payload: dict) -> int:
    """Send a push payload to all subscriptions. Returns success count."""
    priv = app.config["VAPID_PRIVATE_KEY"]
    if not os.path.exists(priv):
        app.logger.warning(f"VAPID private key missing at: {priv}")
        return 0

    with get_db() as conn:
        subs = conn.execute("SELECT * FROM push_subscriptions").fetchall()

    if not subs:
        return 0

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
                vapid_claims={
                    "sub": app.config["VAPID_SUBJECT"],
                    "aud": audience
                },
                ttl=86400,  # 24 hours
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
        app.logger.info("Removed %d invalid subscription(s).", len(expired))

    return sent


def check_reminders():
    """Runs every 30s. Fires each due reminder exactly once."""
    tz = ZoneInfo(app.config["TIMEZONE"])
    now_dt = datetime.now(tz)

    with get_db() as conn:
        rows = conn.execute(
            "SELECT * FROM notes WHERE reminder_at IS NOT NULL AND reminder_sent = 0"
        ).fetchall()

        for row in rows:
            note = dict(row)
            try:
                reminder_dt = datetime.fromisoformat(
                    note["reminder_at"].replace("Z", "+00:00")
                )
            except Exception:
                continue

            if reminder_dt.tzinfo is None:
                reminder_dt = reminder_dt.replace(tzinfo=tz)

            if reminder_dt > now_dt:
                continue

            body = (note["content"] or "").strip()
            send_push_to_all({
                "title": note["title"] or "StickyMind Reminder",
                "body": body[:140] if body else "You have a reminder",
                "note_id": note["id"],
            })
            conn.execute(
                "UPDATE notes SET reminder_sent = 1 WHERE id=?", (note["id"],)
            )


_scheduler = None

def start_scheduler():
    global _scheduler
    if _scheduler is not None:
        return _scheduler
    _scheduler = BackgroundScheduler(timezone=app.config["TIMEZONE"])
    _scheduler.add_job(check_reminders, "interval", seconds=30, id="reminders")
    _scheduler.start()
    app.logger.info("Reminder scheduler started (every 30s).")
    return _scheduler


start_scheduler()


# ---------------------------------------------------------------------------
# JSON error handlers for API
# ---------------------------------------------------------------------------
@app.errorhandler(404)
def not_found(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Not found"}), 404
    return e


@app.errorhandler(500)
def server_error(e):
    if request.path.startswith("/api/"):
        return jsonify({"error": "Server error"}), 500
    return e


# ---------------------------------------------------------------------------
# Dev entrypoint
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    app.run(debug=True, port=5000)
  