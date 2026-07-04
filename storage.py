"""
storage.py
----------
SQLite persistence for the prototype:
  - cases:        the audit trail, now with a lifecycle status per case
  - stakeholders: the admin-editable routing directory (who gets notified)
  - (outbox lives in notifier.py, same database file)

Case status lifecycle:
  RESOLVED         auto-resolved by the workflow (e.g. General Enquiry)
  IN_PROGRESS      routed to a team / handler, awaiting action
  HELD_FOR_REVIEW  escalations and low-confidence overrides awaiting a human
  APPROVED         a human reviewed the held case and approved the handling
"""

import json
import sqlite3
from datetime import datetime
from pathlib import Path

DB_PATH = Path(__file__).parent / "data" / "case_log.db"

# Default status assigned per branch when a case is first processed
BRANCH_DEFAULT_STATUS = {
    "General Enquiry": "RESOLVED",
    "Service Request": "IN_PROGRESS",
    "Complaint": "IN_PROGRESS",
    "Escalation": "HELD_FOR_REVIEW",
}

DEFAULT_STAKEHOLDERS = [
    ("On-Duty Supervisor", "Supervisor", ""),
    ("Senior Complaints Handler", "Senior Handler", ""),
    ("Billing & Payments Team", "Department Owner - Billing", ""),
    ("Technical Support Team", "Department Owner - Technical", ""),
    ("Account Management Team", "Department Owner - Account", ""),
    ("Logistics & Fulfilment Team", "Department Owner - Shipping", ""),
    ("Customer Care Team", "Department Owner - General", ""),
]


def init_db(db_path: Path = DB_PATH):
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS cases (
            request_id TEXT PRIMARY KEY,
            timestamp TEXT,
            raw_text TEXT,
            request_type TEXT,
            urgency TEXT,
            sub_topic TEXT,
            confidence TEXT,
            engine TEXT,
            branch TEXT,
            override_applied INTEGER,
            override_reason TEXT,
            steps_json TEXT,
            outputs_json TEXT,
            status TEXT DEFAULT 'IN_PROGRESS'
        )
    """)
    # Migration for databases created before the status column existed
    cols = [r[1] for r in conn.execute("PRAGMA table_info(cases)").fetchall()]
    if "status" not in cols:
        conn.execute("ALTER TABLE cases ADD COLUMN status TEXT DEFAULT 'IN_PROGRESS'")

    conn.execute("""
        CREATE TABLE IF NOT EXISTS stakeholders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            position TEXT NOT NULL,
            email TEXT DEFAULT ''
        )
    """)
    # Seed defaults once, so the admin always has a directory to edit
    count = conn.execute("SELECT COUNT(*) FROM stakeholders").fetchone()[0]
    if count == 0:
        conn.executemany(
            "INSERT INTO stakeholders (name, position, email) VALUES (?, ?, ?)",
            DEFAULT_STAKEHOLDERS,
        )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Cases
# ---------------------------------------------------------------------------

def log_case(request_id: str, text: str, classification: dict, workflow_result: dict,
             db_path: Path = DB_PATH):
    init_db(db_path)
    status = BRANCH_DEFAULT_STATUS.get(workflow_result.get("branch"), "IN_PROGRESS")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """INSERT OR REPLACE INTO cases
           (request_id, timestamp, raw_text, request_type, urgency, sub_topic,
            confidence, engine, branch, override_applied, override_reason,
            steps_json, outputs_json, status)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            request_id,
            datetime.now().isoformat(timespec="seconds"),
            text,
            classification.get("request_type"),
            classification.get("urgency"),
            classification.get("sub_topic"),
            classification.get("confidence"),
            classification.get("engine"),
            workflow_result.get("branch"),
            1 if workflow_result.get("override_applied") else 0,
            workflow_result.get("override_reason"),
            json.dumps(workflow_result.get("steps", [])),
            json.dumps(workflow_result.get("outputs", {})),
            status,
        ),
    )
    conn.commit()
    conn.close()


def fetch_all_cases(db_path: Path = DB_PATH):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM cases ORDER BY timestamp DESC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def fetch_review_queue(db_path: Path = DB_PATH):
    """Cases awaiting a human decision."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM cases WHERE status = 'HELD_FOR_REVIEW' ORDER BY timestamp ASC"
    ).fetchall()
    conn.close()
    return [dict(r) for r in rows]


def update_case_status(request_id: str, status: str, db_path: Path = DB_PATH):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE cases SET status = ? WHERE request_id = ?", (status, request_id))
    conn.commit()
    conn.close()


def update_case_after_reclassify(request_id: str, classification: dict,
                                 workflow_result: dict, db_path: Path = DB_PATH):
    """Overwrite a case's classification/branch/steps after a human reclassifies it."""
    init_db(db_path)
    status = BRANCH_DEFAULT_STATUS.get(workflow_result.get("branch"), "IN_PROGRESS")
    conn = sqlite3.connect(db_path)
    conn.execute(
        """UPDATE cases SET request_type=?, urgency=?, sub_topic=?, confidence=?,
           engine=?, branch=?, override_applied=?, override_reason=?,
           steps_json=?, outputs_json=?, status=?
           WHERE request_id=?""",
        (
            classification.get("request_type"),
            classification.get("urgency"),
            classification.get("sub_topic"),
            classification.get("confidence"),
            classification.get("engine"),
            workflow_result.get("branch"),
            1 if workflow_result.get("override_applied") else 0,
            workflow_result.get("override_reason"),
            json.dumps(workflow_result.get("steps", [])),
            json.dumps(workflow_result.get("outputs", {})),
            status,
            request_id,
        ),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Stakeholders
# ---------------------------------------------------------------------------

def fetch_stakeholders(db_path: Path = DB_PATH):
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    rows = conn.execute("SELECT * FROM stakeholders ORDER BY id").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def replace_stakeholders(records, db_path: Path = DB_PATH):
    """Replace the whole directory with the admin-edited version."""
    init_db(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("DELETE FROM stakeholders")
    conn.executemany(
        "INSERT INTO stakeholders (name, position, email) VALUES (?, ?, ?)",
        [(r.get("name", ""), r.get("position", ""), r.get("email", "")) for r in records
         if r.get("name") and r.get("position")],
    )
    conn.commit()
    conn.close()


def find_stakeholder(position_contains: str, db_path: Path = DB_PATH):
    """First stakeholder whose position contains the given text (case-insensitive)."""
    for s in fetch_stakeholders(db_path):
        if position_contains.lower() in (s.get("position") or "").lower():
            return s
    return None


# ---------------------------------------------------------------------------
# Dashboard summary
# ---------------------------------------------------------------------------

def summary_counts(db_path: Path = DB_PATH):
    cases = fetch_all_cases(db_path)
    by_type, by_urgency, by_status = {}, {}, {}
    by_override = {"overridden": 0, "normal": 0}
    human_needed = 0
    for c in cases:
        by_type[c["request_type"]] = by_type.get(c["request_type"], 0) + 1
        by_urgency[c["urgency"]] = by_urgency.get(c["urgency"], 0) + 1
        by_status[c["status"]] = by_status.get(c["status"], 0) + 1
        if c["override_applied"]:
            by_override["overridden"] += 1
        else:
            by_override["normal"] += 1
        if c["branch"] == "Escalation" or c["override_applied"]:
            human_needed += 1
    total = len(cases)
    deflection_pct = round(100 * (total - human_needed) / total) if total else 0
    return {
        "by_type": by_type, "by_urgency": by_urgency, "by_status": by_status,
        "by_override": by_override, "total": total,
        "human_needed": human_needed, "deflection_pct": deflection_pct,
    }
