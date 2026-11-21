import os
import sqlite3
from datetime import datetime

DEFAULT_SETTINGS = {
    "shift_start": "09:00",
    "shift_end": "18:00",
    "grace_minutes": "15",
    "full_day_hours": "8.0",
    "half_day_hours": "4.0",
    "overtime_after_hours": "8.5",
    "weekly_off_days": "6",  # 0=Mon ... 6=Sun (Sunday off by default)
    "debounce_seconds": "60",
}


def get_db_path() -> str:
    return os.environ.get("ATTENDANCE_DB", "attendance.db")


def get_conn(db_path: str | None = None) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path or get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def init_db(db_path: str | None = None) -> None:
    with get_conn(db_path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS employees (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                emp_code TEXT UNIQUE NOT NULL,
                name TEXT NOT NULL,
                department TEXT DEFAULT '',
                card_uid TEXT UNIQUE NOT NULL,
                active INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS punches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                employee_id INTEGER NOT NULL,
                card_uid TEXT NOT NULL,
                device_id TEXT DEFAULT '',
                punch_type TEXT NOT NULL CHECK(punch_type IN ('IN', 'OUT')),
                timestamp TEXT NOT NULL,
                FOREIGN KEY (employee_id) REFERENCES employees(id)
            );

            CREATE TABLE IF NOT EXISTS unknown_taps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                card_uid TEXT NOT NULL,
                device_id TEXT DEFAULT '',
                timestamp TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            );
            """
        )
        for k, v in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)", (k, v)
            )


def get_settings(db_path: str | None = None) -> dict[str, str]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT key, value FROM settings").fetchall()
    result = dict(DEFAULT_SETTINGS)
    for r in rows:
        result[r["key"]] = r["value"]
    return result


def update_settings(updates: dict[str, str], db_path: str | None = None) -> None:
    init_db(db_path)
    with get_conn(db_path) as conn:
        for k, v in updates.items():
            if k in DEFAULT_SETTINGS:
                conn.execute(
                    "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
                    (k, str(v).strip()),
                )


def add_employee(
    emp_code: str,
    name: str,
    card_uid: str,
    department: str = "",
    db_path: str | None = None,
) -> int:
    init_db(db_path)
    uid = card_uid.strip().upper()
    with get_conn(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO employees (emp_code, name, department, card_uid) VALUES (?, ?, ?, ?)",
            (emp_code.strip(), name.strip(), department.strip(), uid),
        )
        return cur.lastrowid


def list_employees(db_path: str | None = None) -> list[dict]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute("SELECT * FROM employees ORDER BY emp_code").fetchall()
    return [dict(r) for r in rows]


def get_employee_by_uid(card_uid: str, db_path: str | None = None) -> dict | None:
    init_db(db_path)
    uid = card_uid.strip().upper()
    with get_conn(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM employees WHERE card_uid = ? AND active = 1", (uid,)
        ).fetchone()
    return dict(row) if row else None


def get_employee(emp_id: int, db_path: str | None = None) -> dict | None:
    init_db(db_path)
    with get_conn(db_path) as conn:
        row = conn.execute("SELECT * FROM employees WHERE id = ?", (emp_id,)).fetchone()
    return dict(row) if row else None


def add_unknown_tap(
    card_uid: str,
    device_id: str = "",
    timestamp: str | None = None,
    db_path: str | None = None,
) -> None:
    init_db(db_path)
    ts = timestamp or datetime.now().isoformat(timespec="seconds")
    with get_conn(db_path) as conn:
        conn.execute(
            "INSERT INTO unknown_taps (card_uid, device_id, timestamp) VALUES (?, ?, ?)",
            (card_uid.strip().upper(), device_id.strip(), ts),
        )


def list_unknown_taps(limit: int = 50, db_path: str | None = None) -> list[dict]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM unknown_taps ORDER BY timestamp DESC LIMIT ?", (limit,)
        ).fetchall()
    return [dict(r) for r in rows]


def record_punch(
    card_uid: str,
    device_id: str = "",
    timestamp: str | None = None,
    db_path: str | None = None,
) -> dict:
    init_db(db_path)
    uid = card_uid.strip().upper()
    ts_str = timestamp or datetime.now().isoformat(timespec="seconds")
    ts_dt = datetime.fromisoformat(ts_str)

    emp = get_employee_by_uid(uid, db_path)
    if not emp:
        add_unknown_tap(uid, device_id, ts_str, db_path)
        return {"status": "unknown", "card_uid": uid}

    settings = get_settings(db_path)
    debounce = int(settings.get("debounce_seconds", 60))
    day_prefix = ts_dt.strftime("%Y-%m-%d")

    with get_conn(db_path) as conn:
        last = conn.execute(
            """
            SELECT * FROM punches
            WHERE employee_id = ? AND timestamp LIKE ?
            ORDER BY timestamp DESC LIMIT 1
            """,
            (emp["id"], f"{day_prefix}%"),
        ).fetchone()

        if last:
            last_dt = datetime.fromisoformat(last["timestamp"])
            if abs((ts_dt - last_dt).total_seconds()) < debounce:
                return {
                    "status": "duplicate",
                    "employee": emp["name"],
                    "punch_type": last["punch_type"],
                    "timestamp": ts_str,
                }
            next_type = "OUT" if last["punch_type"] == "IN" else "IN"
        else:
            next_type = "IN"

        conn.execute(
            """
            INSERT INTO punches (employee_id, card_uid, device_id, punch_type, timestamp)
            VALUES (?, ?, ?, ?, ?)
            """,
            (emp["id"], uid, device_id.strip(), next_type, ts_str),
        )

    return {
        "status": "ok",
        "employee": emp["name"],
        "emp_code": emp["emp_code"],
        "punch_type": next_type,
        "timestamp": ts_str,
    }


def get_punches_for_range(
    start_date: str, end_date: str, db_path: str | None = None
) -> list[dict]:
    init_db(db_path)
    with get_conn(db_path) as conn:
        rows = conn.execute(
            """
            SELECT p.*, e.name AS employee_name, e.emp_code, e.department
            FROM punches p
            JOIN employees e ON e.id = p.employee_id
            WHERE substr(p.timestamp, 1, 10) BETWEEN ? AND ?
            ORDER BY p.timestamp ASC
            """,
            (start_date, end_date),
        ).fetchall()
    return [dict(r) for r in rows]