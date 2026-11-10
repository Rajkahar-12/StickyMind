
"""
StickyMind — Flask Backend
Notes API, SQLite, reminders, PWA and Web Push
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


# ============================================================
# DATABASE
# ============================================================

@contextmanager
def get_db():
    db_path = app.config["DATABASE"]
    db_dir = os.path.dirname(db_path)

    if db_dir:
        os.makedirs(db_dir, exist_ok=True)

    conn = sqlite3.connect(db_path, timeout=20)
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
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL DEFAULT '',
                content TEXT NOT NULL DEFAULT '',
                category TEXT NOT NULL DEFAULT 'Personal',
                color TEXT NOT NULL DEFAULT 'yellow',
                pinned INTEGER NOT NULL DEFAULT 0,
                reminder_at TEXT,
                reminder_sent INTEGER NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS push_subscriptions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                endpoint TEXT UNIQUE NOT NULL,
                p256dh TEXT NOT NULL,
                auth TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
        """)


init_db()


# ============================================================
# CONSTANTS AND HELPERS
# ============================================================

VALID_COLORS = {"yellow", "pink", "blue", "green", "purple"}
VALID_CATEGORIES = {"Study", "Work", "Personal"}


def now_iso():
    return datetime.now(
        ZoneInfo(app.config["TIMEZONE"])
    ).isoformat()


def normalize_datetime(value):
    if not value:
        return None

    try:
        value = str(value).replace("Z", "+00:00")
        dt = datetime.fromisoformat(value)
        tz = ZoneInfo(app.config["TIMEZONE"])

        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=tz)
        else:
            dt = dt.astimezone(tz)

        return dt.isoformat()

    except (ValueError, TypeError):
        return None


def row_to_note(row):
    note = dict(row)
    note["pinned"] = bool(note["pinned"])
    note["reminder_sent"] = bool(note["reminder_sent"])
    return note


def error_response(message, status=400):
    return jsonify({"error": message}), status


def get_json_data():
    return request.get_json(silent=True) or {}


def validate_note_data(data, partial=False):
    """
    Validate incoming note fields.
    Returns (clean_data, error_message).
    """

    allowed = {
        "title",
        "content",
        "category",
        "color",
        "pinned",
        "reminder_at",
    }

    if not isinstance(data, dict):
        return None, "Invalid JSON data"

    if not partial and not any(key in data for key in ("title", "content")):
        return None, "Add a title or some content"

    clean = {}

    if "title" in data:
        title = str(data["title"] or "").strip()

        if len(title) > 100:
            return None, "Title must be 100 characters or less"

        clean["title"] = title

    if "content" in data:
        content = str(data["content"] or "")

        if len(content) > 5000:
            return None, "Content must be 5000 characters or less"

        clean["content"] = content

    if "category" in data:
        category = str(data["category"])

        if category not in VALID_CATEGORIES:
            return None, "Invalid category"

        clean["category"] = category

    if "color" in data:
        color = str(data["color"])

        if color not in VALID_COLORS:
            return None, "Invalid note color"

        clean["color"] = color

    if "pinned" in data:
        clean["pinned"] = 1 if bool(data["pinned"]) else 0

    if "reminder_at" in data:
        value = data["reminder_at"]

        if value in (None, ""):
            clean["reminder_at"] = None
        else:
            normalized = normalize_datetime(value)

            if normalized is None:
                return None, "Invalid reminder date or time"

            clean["reminder_at"] = normalized

    invalid = set(data.keys()) - allowed

    if invalid:
        return None, "Unknown note field"

    return clean, None


# ============================================================
# PAGES AND HEALTH CHECK
# ============================================================

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/health")
def health():
    return jsonify({
        "status": "ok",
        "app": "StickyMind"
    })


@app.route("/service-worker.js")
def service_worker():
    return send_from_directory(
        app.static_folder,
        "service-worker.js",
        mimetype="application/javascript"
    )


# ============================================================
# NOTES API
# ============================================================

@app.route("/api/notes", methods=["GET"])
def get_notes():
    with get_db() as conn:
        rows = conn.execute("""
            SELECT *
            FROM notes
            ORDER BY pinned DESC, updated_at DESC, id DESC
        """).fetchall()

    return jsonify([row_to_note(row) for row in rows])


@app.route("/api/notes", methods=["POST"])
def create_note():
    data = get_json_data()
    clean, error = validate_note_data(data)

    if error:
        return error_response(error)

    title = clean.get("title", "")
    content = clean.get("content", "")

    if not title and not content.strip():
        return error_response("Add a title or some content")

    timestamp = now_iso()

    with get_db() as conn:
        cursor = conn.execute("""
            INSERT INTO notes (
                title,
                content,
                category,
                color,
                pinned,
                reminder_at,
                reminder_sent,
                created_at,
                updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
        """, (
            title,
            content,
            clean.get("category", "Personal"),
            clean.get("color", "yellow"),
            clean.get("pinned", 0),
            clean.get("reminder_at"),
            timestamp,
            timestamp,
        ))

        note_id = cursor.lastrowid

        row = conn.execute(
            "SELECT * FROM notes WHERE id = ?",
            (note_id,)
        ).fetchone()

    return jsonify(row_to_note(row)), 201


@app.route("/api/notes/<int:note_id>", methods=["PUT"])
def update_note(note_id):
    data = get_json_data()
    clean, error = validate_note_data(data, partial=True)

    if error:
        return error_response(error)

    if not clean:
        return error_response("No fields provided to update")

    with get_db() as conn:
        existing = conn.execute(
            "SELECT * FROM notes WHERE id = ?",
            (note_id,)
        ).fetchone()

        if existing is None:
            return error_response("Note not found", 404)

        updates = []
        values = []

        for field, value in clean.items():
            updates.append(f"{field} = ?")
            values.append(value)

        # Reset reminder status if the reminder time changes.
        if "reminder_at" in clean:
            if clean["reminder_at"] != existing["reminder_at"]:
                updates.append("reminder_sent = 0")

        updates.append("updated_at = ?")
        values.append(now_iso())
        values.append(note_id)

        conn.execute(
            f"UPDATE notes SET {', '.join(updates)} WHERE id = ?",
            values
        )

        row = conn.execute(
            "SELECT * FROM notes WHERE id = ?",
            (note_id,)
        ).fetchone()

    return jsonify(row_to_note(row))


@app.route("/api/notes/<int:note_id>", methods=["DELETE"])
def delete_note(note_id):
    with get_db() as conn:
        cursor = conn.execute(
            "DELETE FROM notes WHERE id = ?",
            (note_id,)
        )

        if cursor.rowcount == 0:
            return error_response("Note not found", 404)

    return jsonify({
        "ok": True,
        "message": "Note deleted"
    })


# ============================================================
# VAPID PUBLIC KEY
# ============================================================

@app.route("/api/vapid-public-key", methods=["GET"])
def vapid_public_key():
    key_content = os.environ.get("VAPID_PUBLIC_KEY_CONTENT")

    if key_content:
        return jsonify({
            "publicKey": key_content.strip()
        })

    key_path = app.config["VAPID_PUBLIC_KEY"]

    if os.path.exists(key_path):
        with open(key_path, "r", encoding="utf-8") as file:
            return jsonify({
                "publicKey": file.read().strip()
            })

    app.logger.error("VAPID public key is missing")

    return error_response(
        "VAPID public key missing. Check environment variables.",
        500
    )


# ============================================================
# PUSH SUBSCRIPTION API
# ============================================================

@app.route("/api/push/subscribe", methods=["POST"])
def push_subscribe():
    data = get_json_data()
    subscription = data.get("subscription") or {}

    endpoint = subscription.get("endpoint")
    keys = subscription.get("keys") or {}

    p256dh = keys.get("p256dh")
    auth = keys.get("auth")

    if not endpoint or not p256dh or not auth:
        return error_response("Invalid push subscription", 400)

    with get_db() as conn:
        conn.execute("""
            INSERT OR REPLACE INTO push_subscriptions (
                endpoint,
                p256dh,
                auth,
                created_at
            )
            VALUES (?, ?, ?, ?)
        """, (
            endpoint,
            p256dh,
            auth,
            now_iso()
        ))

    return jsonify({"ok": True})


@app.route("/api/push/unsubscribe", methods=["POST"])
def push_unsubscribe():
    data = get_json_data()
    subscription = data.get("subscription") or {}

    endpoint = subscription.get("endpoint") or data.get("endpoint")

    if not endpoint:
        return error_response("Missing subscription endpoint")

    with get_db() as conn:
        conn.execute(
            "DELETE FROM push_subscriptions WHERE endpoint = ?",
            (endpoint,)
        )

    return jsonify({"ok": True})


# ============================================================
# SEND PUSH NOTIFICATIONS
# ============================================================

def send_push_to_all(payload):
    private_key = os.environ.get("VAPID_PRIVATE_KEY_CONTENT")

    if not private_key:
        private_path = app.config["VAPID_PRIVATE_KEY"]

        if os.path.exists(private_path):
            with open(private_path, "r", encoding="utf-8") as file:
                private_key = file.read()

    if not private_key:
        app.logger.error("VAPID private key is missing")
        return 0

    # Supports environment variables containing literal \n.
    private_key = private_key.replace("\\n", "\n")

    with get_db() as conn:
        subscriptions = conn.execute(
            "SELECT * FROM push_subscriptions"
        ).fetchall()

    if not subscriptions:
        app.logger.info("No push subscriptions are registered")
        return 0

    sent = 0
    expired = []

    for sub in subscriptions:
        subscription_info = {
            "endpoint": sub["endpoint"],
            "keys": {
                "p256dh": sub["p256dh"],
                "auth": sub["auth"]
            }
        }

        parsed = urlparse(sub["endpoint"])
        audience = f"{parsed.scheme}://{parsed.netloc}"

        try:
            webpush(
                subscription_info=subscription_info,
                data=json.dumps(payload),
                vapid_private_key=private_key,
                vapid_claims={
                    "sub": app.config["VAPID_SUBJECT"],
                    "aud": audience
                },
                ttl=86400
            )

            sent += 1

        except WebPushException as error:
            response = getattr(error, "response", None)
            status = getattr(response, "status_code", None)

            app.logger.warning(
                "Push delivery failed. Status: %s, Error: %s",
                status,
                error
            )

            if status in (404, 410):
                expired.append(sub["endpoint"])

    if expired:
        with get_db() as conn:
            for endpoint in expired:
                conn.execute(
                    "DELETE FROM push_subscriptions WHERE endpoint = ?",
                    (endpoint,)
                )

    return sent


# ============================================================
# REMINDER SCHEDULER
# ============================================================

def check_reminders():
    timezone = ZoneInfo(app.config["TIMEZONE"])
    current_time = datetime.now(timezone)

    with get_db() as conn:
        rows = conn.execute("""
            SELECT *
            FROM notes
            WHERE reminder_at IS NOT NULL
            AND reminder_sent = 0
        """).fetchall()

    for row in rows:
        note = dict(row)

        try:
            reminder_time = datetime.fromisoformat(
                note["reminder_at"].replace("Z", "+00:00")
            )

            if reminder_time.tzinfo is None:
                reminder_time = reminder_time.replace(tzinfo=timezone)

            if reminder_time > current_time:
                continue

            body = (note["content"] or "").strip()

            payload = {
                "title": note["title"] or "StickyMind Reminder",
                "body": body[:140] if body else "You have a reminder",
                "note_id": note["id"]
            }

            sent_count = send_push_to_all(payload)

            # Keep the reminder pending if nobody received the push.
            if sent_count > 0:
                with get_db() as conn:
                    conn.execute("""
                        UPDATE notes
                        SET reminder_sent = 1
                        WHERE id = ?
                    """, (note["id"],))

        except Exception:
            app.logger.exception(
                "Reminder processing failed for note %s",
                note["id"]
            )


# ============================================================
# START SCHEDULER
# ============================================================

_scheduler = None


def start_scheduler():
    global _scheduler

    if _scheduler is not None:
        return _scheduler

    scheduler = BackgroundScheduler(
        timezone=app.config["TIMEZONE"]
    )

    scheduler.add_job(
        check_reminders,
        trigger="interval",
        seconds=30,
        id="stickymind-reminders",
        max_instances=1,
        coalesce=True
    )

    scheduler.start()
    _scheduler = scheduler

    app.logger.info("StickyMind reminder scheduler started")

    return _scheduler


start_scheduler()


# ============================================================
# LOCAL DEVELOPMENT
# ============================================================

if __name__ == "__main__":
    app.run(
        host="127.0.0.1",
        port=5000,
        debug=True
    )
