import calendar
import csv
import io
import os
from datetime import date, datetime
from flask import Flask, flash, jsonify, redirect, render_template, request, send_file, url_for
from openpyxl import Workbook

import db
import rules

app = Flask(__name__)
app.secret_key = os.environ.get("ATTENDANCE_SECRET", "dev-secret-change-me")


def _api_key_valid() -> bool:
    expected = os.environ.get("ATTENDANCE_API_KEY", "")
    provided = request.headers.get("X-API-Key", "")
    return bool(expected) and provided == expected


@app.route("/")
def dashboard():
    db_path = db.get_db_path()
    settings = db.get_settings(db_path)
    employees = db.list_employees(db_path)
    today_str = date.today().isoformat()
    punches = db.get_punches_for_range(today_str, today_str, db_path)

    by_emp: dict[int, list[dict]] = {e["id"]: [] for e in employees}
    for p in punches:
        by_emp.setdefault(p["employee_id"], []).append(p)

    rows = []
    present_count = 0
    late_count = 0
    incomplete_count = 0

    for emp in employees:
        ev = rules.evaluate_day(today_str, by_emp.get(emp["id"], []), settings)
        if ev["status"] in ("PRESENT", "HALF_DAY", "SHORT_DAY", "INCOMPLETE"):
            present_count += 1
        if ev["late"]:
            late_count += 1
        if ev["status"] == "INCOMPLETE":
            incomplete_count += 1
        rows.append(
            {
                "emp_code": emp["emp_code"],
                "name": emp["name"],
                "department": emp["department"],
                "status": ev["status"],
                "first_in": ev["first_in"] or "-",
                "last_out": ev["last_out"] or "-",
                "worked_hours": ev["worked_hours"],
                "late": ev["late"],
            }
        )

    unknown_taps = db.list_unknown_taps(limit=15, db_path=db_path)
    recent_punches = list(reversed(punches[-15:]))

    return render_template(
        "dashboard.html",
        today_str=today_str,
        rows=rows,
        total_employees=len(employees),
        present_count=present_count,
        late_count=late_count,
        incomplete_count=incomplete_count,
        recent_punches=recent_punches,
        unknown_taps=unknown_taps,
    )


@app.route("/api/punch", methods=["POST"])
def api_punch():
    if not _api_key_valid():
        return jsonify({"status": "error", "message": "Invalid or missing X-API-Key"}), 401

    payload = request.get_json(silent=True) or {}
    card_uid = str(payload.get("card_uid", "")).strip()
    device_id = str(payload.get("device_id", "")).strip()
    timestamp = payload.get("timestamp")

    if not card_uid:
        return jsonify({"status": "error", "message": "card_uid is required"}), 400

    if timestamp:
        try:
            datetime.fromisoformat(str(timestamp))
        except ValueError:
            return jsonify({"status": "error", "message": "Invalid timestamp format"}), 400

    res = db.record_punch(
        card_uid=card_uid,
        device_id=device_id,
        timestamp=str(timestamp) if timestamp else None,
    )
    code = 404 if res["status"] == "unknown" else 200
    return jsonify(res), code


def _get_year_month() -> tuple[int, int]:
    now = date.today()
    ym = request.args.get("month", "")
    if ym:
        try:
            parts = ym.split("-")
            y, m = int(parts[0]), int(parts[1])
            if 1 <= m <= 12:
                return y, m
        except (ValueError, IndexError):
            pass
    return now.year, now.month


@app.route("/report")
def report():
    db_path = db.get_db_path()
    year, month = _get_year_month()
    _, last_day = calendar.monthrange(year, month)
    start_str = f"{year:04d}-{month:02d}-01"
    end_str = f"{year:04d}-{month:02d}-{last_day:02d}"

    settings = db.get_settings(db_path)
    employees = db.list_employees(db_path)
    punches = db.get_punches_for_range(start_str, end_str, db_path)
    summaries, _, _ = rules.build_monthly_report(year, month, employees, punches, settings)

    return render_template(
        "report.html",
        summaries=summaries,
        year=year,
        month=month,
        month_value=f"{year:04d}-{month:02d}",
    )


@app.route("/report/<int:emp_id>")
def report_detail(emp_id: int):
    db_path = db.get_db_path()
    year, month = _get_year_month()
    _, last_day = calendar.monthrange(year, month)
    start_str = f"{year:04d}-{month:02d}-01"
    end_str = f"{year:04d}-{month:02d}-{last_day:02d}"

    emp = db.get_employee(emp_id, db_path)
    if not emp:
        flash("Employee not found.", "error")
        return redirect(url_for("report"))

    settings = db.get_settings(db_path)
    punches = db.get_punches_for_range(start_str, end_str, db_path)
    _, daily_map, _ = rules.build_monthly_report(year, month, [emp], punches, settings)

    return render_template(
        "detail.html",
        employee=emp,
        days=daily_map.get(emp_id, []),
        month_value=f"{year:04d}-{month:02d}",
    )


@app.route("/report.xlsx")
def report_xlsx():
    db_path = db.get_db_path()
    year, month = _get_year_month()
    _, last_day = calendar.monthrange(year, month)
    start_str = f"{year:04d}-{month:02d}-01"
    end_str = f"{year:04d}-{month:02d}-{last_day:02d}"

    settings = db.get_settings(db_path)
    employees = db.list_employees(db_path)
    punches = db.get_punches_for_range(start_str, end_str, db_path)
    summaries, daily_map, anomalies = rules.build_monthly_report(
        year, month, employees, punches, settings
    )

    wb = Workbook()
    ws_sum = wb.active
    ws_sum.title = "Summary"
    ws_sum.append(
        [
            "Emp Code",
            "Name",
            "Department",
            "Present",
            "Half Day",
            "Absent",
            "Incomplete",
            "Late",
            "Early Exit",
            "Worked Hours",
            "Overtime Hours",
        ]
    )
    for s in summaries:
        ws_sum.append(
            [
                s["emp_code"],
                s["name"],
                s["department"],
                s["present"],
                s["half_day"],
                s["absent"],
                s["incomplete"],
                s["late"],
                s["early_exit"],
                s["worked_hours"],
                s["overtime_hours"],
            ]
        )

    ws_daily = wb.create_sheet("Daily")
    ws_daily.append(
        [
            "Emp Code",
            "Name",
            "Date",
            "Status",
            "First In",
            "Last Out",
            "Worked Hours",
            "Overtime Hours",
            "Late",
            "Early Exit",
            "Flags",
        ]
    )
    for emp in employees:
        for d in daily_map.get(emp["id"], []):
            ws_daily.append(
                [
                    emp["emp_code"],
                    emp["name"],
                    d["date"],
                    d["status"],
                    d["first_in"] or "",
                    d["last_out"] or "",
                    d["worked_hours"],
                    d["overtime_hours"],
                    "Yes" if d["late"] else "No",
                    "Yes" if d["early_exit"] else "No",
                    ", ".join(d["flags"]),
                ]
            )

    ws_anom = wb.create_sheet("Anomalies")
    ws_anom.append(["Date", "Emp Code", "Name", "Issue"])
    for a in anomalies:
        ws_anom.append([a["date"], a["emp_code"], a["name"], a["issue"]])

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    filename = f"attendance_{year:04d}_{month:02d}.xlsx"
    return send_file(
        buf,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route("/anomalies")
def anomalies_view():
    db_path = db.get_db_path()
    year, month = _get_year_month()
    _, last_day = calendar.monthrange(year, month)
    start_str = f"{year:04d}-{month:02d}-01"
    end_str = f"{year:04d}-{month:02d}-{last_day:02d}"

    settings = db.get_settings(db_path)
    employees = db.list_employees(db_path)
    punches = db.get_punches_for_range(start_str, end_str, db_path)
    _, _, anomalies = rules.build_monthly_report(year, month, employees, punches, settings)
    unknown_taps = db.list_unknown_taps(limit=50, db_path=db_path)

    return render_template(
        "anomalies.html",
        anomalies=anomalies,
        unknown_taps=unknown_taps,
        month_value=f"{year:04d}-{month:02d}",
    )


@app.route("/employees", methods=["GET", "POST"])
def employees_view():
    db_path = db.get_db_path()
    if request.method == "POST":
        emp_code = request.form.get("emp_code", "").strip()
        name = request.form.get("name", "").strip()
        department = request.form.get("department", "").strip()
        card_uid = request.form.get("card_uid", "").strip()
        if not emp_code or not name or not card_uid:
            flash("Employee code, name, and card UID are required.", "error")
        else:
            try:
                db.add_employee(emp_code, name, card_uid, department, db_path)
                flash(f"Added employee {name} ({card_uid.upper()}).", "success")
            except Exception as exc:
                flash(f"Could not add employee: {exc}", "error")
        return redirect(url_for("employees_view"))

    employees = db.list_employees(db_path)
    return render_template("employees.html", employees=employees)


@app.route("/import", methods=["GET", "POST"])
def import_csv():
    db_path = db.get_db_path()
    imported = 0
    errors = []

    if request.method == "POST":
        file = request.files.get("csv_file")
        if not file or not file.filename:
            flash("Please choose a CSV file.", "error")
        else:
            content = file.stream.read().decode("utf-8-sig", errors="replace")
            reader = csv.DictReader(io.StringIO(content))
            for idx, row in enumerate(reader, start=2):
                uid = (row.get("card_uid") or "").strip()
                ts = (row.get("timestamp") or "").strip() or None
                dev = (row.get("device_id") or "csv-import").strip()
                if not uid:
                    errors.append(f"Row {idx}: missing card_uid")
                    continue
                if ts:
                    try:
                        datetime.fromisoformat(ts)
                    except ValueError:
                        errors.append(f"Row {idx} ({uid}): invalid timestamp")
                        continue
                res = db.record_punch(uid, dev, ts, db_path)
                if res["status"] == "ok":
                    imported += 1
                else:
                    errors.append(f"Row {idx} ({uid}): {res['status']}")
            flash(f"Imported {imported} punch(es).", "success")

    return render_template("import.html", imported=imported, errors=errors)


@app.route("/settings", methods=["GET", "POST"])
def settings_view():
    db_path = db.get_db_path()
    if request.method == "POST":
        updates = {
            key: request.form.get(key, val)
            for key, val in db.DEFAULT_SETTINGS.items()
        }
        db.update_settings(updates, db_path)
        flash("Settings updated.", "success")
        return redirect(url_for("settings_view"))

    current = db.get_settings(db_path)
    return render_template("settings.html", settings=current)


if __name__ == "__main__":
    debug_mode = os.environ.get("FLASK_DEBUG", "0") == "1"
    app.run(host="127.0.0.1", port=5000, debug=debug_mode)