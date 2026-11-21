import calendar
from collections import defaultdict
from datetime import date, datetime, time, timedelta


def _parse_hhmm(val: str) -> time:
    hh, mm = map(int, val.split(":"))
    return time(hh, mm)


def evaluate_day(
    day_str: str, punches: list[dict], settings: dict[str, str]
) -> dict:
    d = date.fromisoformat(day_str)
    off_days = {
        int(x.strip())
        for x in settings.get("weekly_off_days", "6").split(",")
        if x.strip().isdigit()
    }
    is_off = d.weekday() in off_days

    if not punches:
        return {
            "date": day_str,
            "status": "OFF" if is_off else "ABSENT",
            "first_in": None,
            "last_out": None,
            "worked_hours": 0.0,
            "overtime_hours": 0.0,
            "late": False,
            "early_exit": False,
            "flags": [],
        }

    sorted_p = sorted(punches, key=lambda x: x["timestamp"])
    times = [datetime.fromisoformat(p["timestamp"]) for p in sorted_p]
    first_in = times[0]
    flags = []

    for dt in times:
        if dt.hour < 5 or dt.hour >= 23:
            flags.append(f"Odd-hour punch at {dt.strftime('%H:%M')}")

    if len(sorted_p) % 2 == 1:
        return {
            "date": day_str,
            "status": "INCOMPLETE",
            "first_in": first_in.strftime("%H:%M"),
            "last_out": None,
            "worked_hours": 0.0,
            "overtime_hours": 0.0,
            "late": False,
            "early_exit": False,
            "flags": flags + ["Missing punch-out"],
        }

    total_seconds = 0.0
    for i in range(0, len(times), 2):
        total_seconds += max(0.0, (times[i + 1] - times[i]).total_seconds())

    worked_hours = round(total_seconds / 3600.0, 2)
    last_out = times[-1]

    shift_start = datetime.combine(d, _parse_hhmm(settings.get("shift_start", "09:00")))
    shift_end = datetime.combine(d, _parse_hhmm(settings.get("shift_end", "18:00")))
    grace = timedelta(minutes=int(settings.get("grace_minutes", 15)))

    late = first_in > (shift_start + grace)
    early_exit = last_out < shift_end

    full_hrs = float(settings.get("full_day_hours", 8.0))
    half_hrs = float(settings.get("half_day_hours", 4.0))
    ot_after = float(settings.get("overtime_after_hours", 8.5))

    if worked_hours >= full_hrs:
        status = "PRESENT"
    elif worked_hours >= half_hrs:
        status = "HALF_DAY"
    else:
        status = "SHORT_DAY"
        flags.append(f"Short duration ({worked_hours}h)")

    overtime = round(max(0.0, worked_hours - ot_after), 2)

    return {
        "date": day_str,
        "status": status,
        "first_in": first_in.strftime("%H:%M"),
        "last_out": last_out.strftime("%H:%M"),
        "worked_hours": worked_hours,
        "overtime_hours": overtime,
        "late": late,
        "early_exit": early_exit,
        "flags": flags,
    }


def build_monthly_report(
    year: int,
    month: int,
    employees: list[dict],
    punches: list[dict],
    settings: dict[str, str],
) -> tuple[list[dict], dict[int, list[dict]], list[dict]]:
    _, num_days = calendar.monthrange(year, month)
    today = date.today()

    by_emp_day: dict[int, dict[str, list[dict]]] = defaultdict(lambda: defaultdict(list))
    for p in punches:
        day_str = p["timestamp"][:10]
        by_emp_day[p["employee_id"]][day_str].append(p)

    summaries = []
    daily_map: dict[int, list[dict]] = {}
    anomalies = []

    for emp in employees:
        emp_days = []
        counts = defaultdict(int)
        total_hrs = 0.0
        total_ot = 0.0
        late_count = 0
        early_count = 0

        for day_num in range(1, num_days + 1):
            d = date(year, month, day_num)
            if d > today:
                continue
            day_str = d.isoformat()
            res = evaluate_day(day_str, by_emp_day[emp["id"]][day_str], settings)
            emp_days.append(res)

            counts[res["status"]] += 1
            total_hrs += res["worked_hours"]
            total_ot += res["overtime_hours"]
            if res["late"]:
                late_count += 1
            if res["early_exit"]:
                early_count += 1

            for flag in res["flags"]:
                anomalies.append(
                    {
                        "date": day_str,
                        "emp_code": emp["emp_code"],
                        "name": emp["name"],
                        "issue": flag,
                    }
                )

        if late_count >= 3:
            anomalies.append(
                {
                    "date": f"{year:04d}-{month:02d}",
                    "emp_code": emp["emp_code"],
                    "name": emp["name"],
                    "issue": f"Repeated lateness ({late_count} times this month)",
                }
            )

        daily_map[emp["id"]] = emp_days
        summaries.append(
            {
                "id": emp["id"],
                "emp_code": emp["emp_code"],
                "name": emp["name"],
                "department": emp["department"],
                "present": counts["PRESENT"],
                "half_day": counts["HALF_DAY"],
                "absent": counts["ABSENT"],
                "incomplete": counts["INCOMPLETE"],
                "late": late_count,
                "early_exit": early_count,
                "worked_hours": round(total_hrs, 2),
                "overtime_hours": round(total_ot, 2),
            }
        )

    return summaries, daily_map, anomalies