# RFID Attendance System (Flask + SQLite)

A Flask web application and REST API (`POST /api/punch`) for logging card taps, applying shift rules, viewing monthly attendance reports, checking rule-based anomalies, and exporting Excel workbooks.

> **Current status:** The Flask backend, rule engine, test suite, and demo data seeder are ready to run locally without hardware. ESP32 + RC522 hardware terminal integration is planned as a future phase.

## Features

- **Punch ingestion API (`POST /api/punch`)**: Accepts card UIDs and device IDs with `X-API-Key` authentication, normalizes UIDs, deduplicates accidental double-taps, and alternates `IN` / `OUT` punches.
- **Live dashboard (`/`)**: Shows today's attendance status, late arrivals, missing punch-outs, and recent taps.
- **Configurable shift rules (`/settings`)**: Customize shift start/end times, grace period, full-day and half-day hours, overtime threshold, weekly off days, and duplicate-tap debounce window.
- **Monthly reports & Excel export (`/report`, `/report/<id>`, `/report.xlsx`)**: Summarizes present, half-day, absent, incomplete, late, early-exit, worked hours, and overtime per employee, with per-day drill-down and a multi-sheet Excel export (`Summary`, `Daily`, `Anomalies`).
- **Anomaly review (`/anomalies`)**: Highlights rule-based patterns for human review (such as missing punch-outs, duplicate taps, identical punch-in times, odd-hour punches, short days, repeated lateness, and unregistered card taps).
- **CSV import (`/import`) & Employee management (`/employees`)**: Register employee cards and import punch logs from CSV files.
- **Demo database generator (`seed_demo.py`)**: Populates a local SQLite database with sample employees, realistic punch patterns, and intentional edge cases for testing without hardware.

## Project Structure

```text
rfid-attendance/
├── .gitignore
├── README.md
├── backend/
│   ├── app.py
│   ├── db.py
│   ├── rules.py
│   ├── seed_demo.py
│   ├── requirements.txt
│   ├── static/
│   │   └── style.css
│   ├── templates/
│   │   ├── anomalies.html
│   │   ├── base.html
│   │   ├── dashboard.html
│   │   ├── detail.html
│   │   ├── employees.html
│   │   ├── import.html
│   │   ├── report.html
│   │   └── settings.html
│   └── tests/
│       ├── test_api.py
│       └── test_rules.py
└── firmware/
    └── attendance_esp32/
        ├── attendance_esp32.ino
        └── secrets.h.example
