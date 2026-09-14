"""
Efficiently backfills up to a year of wellness data and the full activity
list into garmin/data.json, using Garmin's bulk date-range endpoints instead
of one API call per day. Read-only against Garmin.

Steps, calories, resting heart rate, and sleep each come from a single bulk
call (the library auto-chunks into <=28-day requests internally). Stress has
no daily-range endpoint: a day already covered by the regular daily sync
(garmin_sync.py, real per-day values) is left alone (skipped below); any
other day falls back to the weekly stress average for that week (the
closest available granularity) regardless of how recent it is - a day
missing here won't retroactively get picked up by garmin_sync.py, whose
window is normally just the last few days, so there's no "it'll be covered
later" case to special-case. Body battery, HRV, and training readiness are
skipped entirely for the backfill: confirmed empty for this account against
the real API, and not worth the extra calls (body battery's range endpoint
isn't auto-chunked and errors past ~28 days regardless).

VO2 max also comes from a single bulk range call, stored separately under
data["vo2max_history"] (date -> {vo2max, fitness_age}) rather than inside
"wellness", since it's unrelated to the day's steps/sleep/stress and updates
independently. Always overwritten on every run (cheap single call, unlike
the day-by-day wellness skip logic above) so revised estimates stay current.

Run garmin_sync.py at least once first to be logged in.
"""

import argparse
import sys
from datetime import date, timedelta

from garmin_sync import DATA_FILE, load_client, load_data_json, save_data_json


def index_by_date(rows):
    return {r["calendarDate"]: r for r in (rows or []) if r.get("calendarDate")}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=365, help="How many days back to backfill")
    args = parser.parse_args()

    client = load_client()
    data = load_data_json()

    today = date.today()
    start = today - timedelta(days=args.days)
    start_s, end_s = start.isoformat(), today.isoformat()

    print(f"Fetching bulk wellness {start_s} .. {end_s} ...")

    def safe_call(label, fn):
        try:
            return fn()
        except Exception as exc:
            print(f"  {label} failed: {exc}", file=sys.stderr)
            return []

    steps_by_date = index_by_date(safe_call("steps", lambda: client.get_daily_steps(start_s, end_s)))
    cal_by_date = index_by_date(safe_call("calories", lambda: client.get_calories_daily(start_s, end_s)))
    rhr_by_date = index_by_date(safe_call("resting HR", lambda: client.get_rhr_daily(start_s, end_s)))
    sleep_by_date = index_by_date(safe_call("sleep", lambda: client.get_sleep_daily(start_s, end_s)))
    weekly_stress = sorted(
        safe_call("weekly stress", lambda: client.get_weekly_stress(end_s, weeks=min(52, args.days // 7 + 4))),
        key=lambda r: r["calendarDate"],
    )

    def stress_for_week(day_str):
        val = None
        for w in weekly_stress:
            if w["calendarDate"] <= day_str:
                val = w.get("value")
            else:
                break
        return val

    vo2max_rows = safe_call("VO2 max", lambda: client.get_max_metrics_range(start_s, end_s))
    vo2max_added = 0
    vo2max_history = data.setdefault("vo2max_history", {})
    for row in (vo2max_rows or []):
        generic = row.get("generic") or {}
        cal_date = generic.get("calendarDate")
        vo2max_value = generic.get("vo2MaxValue")
        if cal_date and vo2max_value is not None:
            vo2max_history[cal_date] = {"vo2max": vo2max_value, "fitness_age": generic.get("fitnessAge")}
            vo2max_added += 1
    print(f"VO2 max: {vo2max_added} day(s) with a value (of {len(vo2max_rows or [])} fetched)")

    all_dates = [(start + timedelta(days=i)).isoformat() for i in range((today - start).days + 1)]

    added, skipped = 0, 0
    for day_str in all_dates:
        existing = data["wellness"].get(day_str)
        if existing and (existing.get("summary") or {}).get("totalSteps") is not None:
            skipped += 1
            continue

        steps_row = steps_by_date.get(day_str)
        cal_row = cal_by_date.get(day_str)
        rhr_row = rhr_by_date.get(day_str)
        sleep_row = sleep_by_date.get(day_str)
        sleep_vals = (sleep_row or {}).get("values") or {}

        resting_hr = rhr_row.get("value") if rhr_row else sleep_vals.get("restingHeartRate")
        avg_stress = stress_for_week(day_str)

        data["wellness"][day_str] = {
            "summary": {
                "totalSteps": steps_row.get("totalSteps") if steps_row else None,
                "totalKilocalories": cal_row.get("total") if cal_row else None,
                "restingHeartRate": resting_hr,
                "averageStressLevel": avg_stress,
                "maxStressLevel": None,
            },
            "sleep_bulk": {
                "total_sleep_s": sleep_vals.get("totalSleepTimeInSeconds"),
                "deep_s": sleep_vals.get("deepTime"),
                "light_s": sleep_vals.get("lightTime"),
                "rem_s": sleep_vals.get("remTime"),
                "awake_s": sleep_vals.get("awakeTime"),
            } if sleep_row else None,
            "hrv": {},
            "resting_hr": {
                "allMetrics": {"metricsMap": {"WELLNESS_RESTING_HEART_RATE": [
                    {"value": resting_hr, "calendarDate": day_str}
                ]}}
            },
            "body_battery": [],
            "training_readiness": [],
            "source": "bulk_backfill",
        }
        added += 1

    print(f"wellness: added {added} new day(s), left {skipped} already-complete day(s) untouched")

    print("Fetching activity list...")
    activities = safe_call("activities", lambda: client.get_activities(0, max(400, args.days // 2)))
    pulled = 0
    for activity in activities:
        start_time = activity.get("startTimeLocal") or ""
        activity_day = start_time.split(" ")[0] if start_time else None
        if not activity_day or activity_day < start_s:
            continue
        activity_id = str(activity.get("activityId"))
        data["activities"][activity_id] = activity
        pulled += 1
    print(f"activities: {pulled} within range (of {len(activities)} fetched)")

    save_data_json(data)
    print("done")


if __name__ == "__main__":
    main()
