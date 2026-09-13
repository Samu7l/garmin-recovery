"""
Efficiently backfills up to a year of wellness data and the full activity
list into garmin/data.json, using Garmin's bulk date-range endpoints instead
of one API call per day. Read-only against Garmin.

Steps, calories, resting heart rate, and sleep each come from a single bulk
call (the library auto-chunks into <=28-day requests internally). Stress has
no daily-range endpoint, so days already covered by the regular daily sync
(garmin_sync.py, real per-day values) are left alone; anything older falls
back to the weekly stress average for that week (the closest available
granularity for the deep past). Body battery, HRV, and training readiness
are skipped entirely for the backfill: confirmed empty for this account
against the real API, and not worth the extra calls (body battery's range
endpoint isn't auto-chunked and errors past ~28 days regardless).

Run garmin_sync.py at least once first to be logged in.
"""

import argparse
import sys
from datetime import date, timedelta

from garmin_sync import DATA_FILE, load_client, load_data_json, save_data_json

DAILY_STRESS_WINDOW_DAYS = 60


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
    recent_cutoff = (today - timedelta(days=DAILY_STRESS_WINDOW_DAYS)).isoformat()

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
        avg_stress = None if day_str >= recent_cutoff else stress_for_week(day_str)

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
