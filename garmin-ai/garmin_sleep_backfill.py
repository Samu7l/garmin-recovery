"""
One-time (re-runnable) backfill of historical sleep duration only, reaching
back years before the rolling wellness window that garmin_sync.py maintains.

Sleep is the only thing fetched here - no steps, HR, stress, or activities -
and results are merged into garmin/data.json under a separate "sleep_history"
key (date -> total sleep seconds), not into "wellness". Keeping it separate
means years of otherwise-empty months don't leak into the month-by-month
dashboard view, which only ever reads "wellness".

Run garmin_sync.py at least once first to be logged in.
"""

import argparse
from datetime import date, timedelta

from garmin_sync import load_client, load_data_json, save_data_json


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2015-01-01", help="Earliest date to look for sleep data")
    args = parser.parse_args()

    client = load_client()
    data = load_data_json()

    existing_dates = sorted(data.get("wellness", {}).keys())
    end = (date.fromisoformat(existing_dates[0]) - timedelta(days=1)) if existing_dates else date.today()
    end_s = end.isoformat()

    print(f"Fetching historical sleep {args.start} .. {end_s} ...")
    rows = client.get_sleep_daily(args.start, end_s) or []

    history = data.setdefault("sleep_history", {})
    before = len(history)
    for row in rows:
        day_str = row.get("calendarDate")
        secs = (row.get("values") or {}).get("totalSleepTimeInSeconds")
        if day_str and secs:
            history[day_str] = secs

    save_data_json(data)
    print(f"sleep_history: {len(history)} day(s) total ({len(history) - before} new)")


if __name__ == "__main__":
    main()
