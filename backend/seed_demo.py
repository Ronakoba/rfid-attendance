import os
from datetime import date, timedelta
import db

PEOPLE = [
    ("EMP001", "Aarav Sharma", "Engineering", "DEMO0001"),
    ("EMP002", "Priya Patel", "Operations", "DEMO0002"),
    ("EMP003", "Rohan Verma", "Support", "DEMO0003"),
    ("EMP004", "Neha Nair", "HR", "DEMO0004"),
]


def seed(db_path: str = "demo.db") -> None:
    if os.path.exists(db_path):
        os.remove(db_path)

    db.init_db(db_path)
    for code, name, dept, uid in PEOPLE:
        db.add_employee(code, name, uid, dept, db_path)

    today = date.today()
    for offset in range(6, -1, -1):
        d = today - timedelta(days=offset)
        if d.weekday() == 6:  # Skip Sunday
            continue
        ds = d.isoformat()

        # Aarav: punctual full days
        db.record_punch("DEMO0001", "gate-1", f"{ds}T08:58:00", db_path)
        if offset > 0:
            db.record_punch("DEMO0001", "gate-1", f"{ds}T18:10:00", db_path)

        # Priya: late arrivals on recent days
        in_time = "09:28:00" if offset in (1, 2, 3) else "09:05:00"
        db.record_punch("DEMO0002", "gate-1", f"{ds}T{in_time}", db_path)
        if offset > 0:
            db.record_punch("DEMO0002", "gate-1", f"{ds}T18:05:00", db_path)

        # Rohan: forgot to punch out yesterday (creates anomaly)
        db.record_punch("DEMO0003", "gate-2", f"{ds}T09:02:00", db_path)
        if offset not in (0, 1):
            db.record_punch("DEMO0003", "gate-2", f"{ds}T17:30:00", db_path)

        # Neha: half-day on day 2
        db.record_punch("DEMO0004", "gate-1", f"{ds}T09:00:00", db_path)
        if offset > 0:
            out_time = "13:30:00" if offset == 2 else "18:00:00"
            db.record_punch("DEMO0004", "gate-1", f"{ds}T{out_time}", db_path)

    db.add_unknown_tap("UNREG999", "gate-1", f"{today.isoformat()}T10:14:00", db_path)
    print(f"Seeded {db_path} successfully.")


if __name__ == "__main__":
    seed()