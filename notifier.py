"""
notifier.py
-----------
Sends internal stakeholder notifications (supervisor alerts, routing
notifications). Follows the same resilience pattern as the classifier:

  1. If SMTP credentials are configured (env vars below), send a real email.
  2. If not configured, or if sending fails, the email is written to a
     simulated Outbox table in SQLite instead, so the workflow always
     completes and the demo always has something to show.

Environment variables for live sending (Gmail example):
  SMTP_USER      = your.address@gmail.com
  SMTP_PASSWORD  = 16-character Google App Password (requires 2FA)
  SMTP_HOST      = smtp.gmail.com   (default)
  SMTP_PORT      = 465              (default, SSL)

Only INTERNAL notifications are ever sent. Customer-facing drafts are never
auto-emailed; they remain draft-and-hold artifacts by design.
"""

import os
import smtplib
import sqlite3
from datetime import datetime
from email.mime.text import MIMEText
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "case_log.db"


def _ensure_outbox(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS outbox (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT,
            recipient_name TEXT,
            recipient_email TEXT,
            subject TEXT,
            body TEXT,
            delivery TEXT   -- 'sent' (real email) or 'simulated' (fallback)
        )
    """)
    conn.commit()
    conn.close()


def _log_outbox(name: str, email: str, subject: str, body: str, delivery: str,
                db_path: Path = DB_PATH):
    _ensure_outbox(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute(
        "INSERT INTO outbox (timestamp, recipient_name, recipient_email, subject, body, delivery) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (datetime.now().isoformat(timespec="seconds"), name, email, subject, body, delivery),
    )
    conn.commit()
    conn.close()


def notify(recipient_name: str, recipient_email: str, subject: str, body: str) -> dict:
    """
    Send an internal notification. Returns a dict describing what happened:
      {"delivery": "sent" | "simulated", "detail": "..."}
    Every notification (real or simulated) is also logged to the outbox table.
    """
    smtp_user = os.environ.get("SMTP_USER")
    smtp_password = os.environ.get("SMTP_PASSWORD")

    if smtp_user and smtp_password and recipient_email:
        try:
            host = os.environ.get("SMTP_HOST", "smtp.gmail.com")
            port = int(os.environ.get("SMTP_PORT", "465"))
            msg = MIMEText(body)
            msg["Subject"] = subject
            msg["From"] = smtp_user
            msg["To"] = recipient_email
            with smtplib.SMTP_SSL(host, port, timeout=15) as server:
                server.login(smtp_user, smtp_password)
                server.sendmail(smtp_user, [recipient_email], msg.as_string())
            _log_outbox(recipient_name, recipient_email, subject, body, "sent")
            return {"delivery": "sent",
                    "detail": f"Email sent to {recipient_name} <{recipient_email}>."}
        except Exception as e:
            _log_outbox(recipient_name, recipient_email, subject, body,
                        f"simulated (SMTP error: {type(e).__name__})")
            return {"delivery": "simulated",
                    "detail": f"SMTP failed ({type(e).__name__}); notification logged to simulated outbox for {recipient_name}."}

    _log_outbox(recipient_name, recipient_email or "-", subject, body, "simulated")
    return {"delivery": "simulated",
            "detail": f"No SMTP configured; notification logged to simulated outbox for {recipient_name}."}


def fetch_outbox(db_path: Path = DB_PATH):
    _ensure_outbox(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM outbox ORDER BY id DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]
