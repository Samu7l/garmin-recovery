"""
Pull recent Garmin Connect activities and daily wellness data, and save
them as plain-English markdown notes plus a data.json file.

Never asks for a password. It only ever reads the session token saved by
garmin_login.py. If that token has expired or doesn't exist, it stops and
tells you to run garmin_login.py again. This script never writes anything
back to your Garmin account - every call it makes is a read.
"""

import argparse
import json
import sys
from datetime import date, timedelta
from pathlib import Path

from garminconnect import Garmin

BASE_DIR = Path(__file__).resolve().parent
TOKEN_DIR = BASE_DIR / ".garmintokens"
OUT_DIR = BASE_DIR / "garmin"
WELLNESS_DIR = OUT_DIR / "wellness"
WORKOUTS_DIR = OUT_DIR / "workouts"
DATA_FILE = OUT_DIR / "data.json"


def load_client():
    if not TOKEN_DIR.exists() or not any(TOKEN_DIR.iterdir()):
        print("No saved login found. Run garmin_login.py first.", file=sys.stderr)
        sys.exit(1)
    client = Garmin()
    try:
        client.login(str(TOKEN_DIR))
    except Exception as exc:
        print(
            f"Saved login has expired or is invalid ({exc}). Run garmin_login.py again.",
            file=sys.stderr,
        )
        sys.exit(1)
    return client


def dig(d, *path, default=None):
    cur = d
    for key in path:
        if cur is None:
            return default
        if isinstance(key, int):
            if not isinstance(cur, list) or key >= len(cur):
                return default
            cur = cur[key]
        else:
            if not isinstance(cur, dict) or key not in cur:
                return default
            cur = cur[key]
    return cur if cur is not None else default


def hms(total_seconds):
    if total_seconds is None:
        return "n/a"
    total_seconds = int(total_seconds)
    h, rem = divmod(total_seconds, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h {m:02d}m"
    return f"{m}m {s:02d}s"


def load_data_json():
    if DATA_FILE.exists():
        try:
            return json.loads(DATA_FILE.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            pass
    return {"wellness": {}, "activities": {}}


def save_data_json(data):
    DATA_FILE.write_text(json.dumps(data, indent=2, default=str, ensure_ascii=False), encoding="utf-8")


def fetch_wellness_day(client, day_str):
    raw = {}
    for key, fetch in {
        "summary": lambda: client.get_user_summary(day_str),
        "sleep": lambda: client.get_sleep_data(day_str),
        "hrv": lambda: client.get_hrv_data(day_str),
        "resting_hr": lambda: client.get_rhr_day(day_str),
        "body_battery": lambda: client.get_body_battery(day_str, day_str),
        "stress": lambda: client.get_stress_data(day_str),
        "training_readiness": lambda: client.get_training_readiness(day_str),
        "training_status": lambda: client.get_training_status(day_str),
        "fitness_age": lambda: client.get_fitnessage_data(day_str),
    }.items():
        try:
            raw[key] = fetch()
        except Exception as exc:
            raw[key] = {"error": str(exc)}
    return raw


def wellness_markdown(day_str, raw):
    lines = [f"# Wellness — {day_str}", ""]

    sleep = raw.get("sleep") or {}
    dto = dig(sleep, "dailySleepDTO", default={}) or {}
    total_sleep = dig(dto, "sleepTimeSeconds") or dig(sleep, "sleepTimeSeconds")
    deep = dig(dto, "deepSleepSeconds")
    light = dig(dto, "lightSleepSeconds")
    rem = dig(dto, "remSleepSeconds")
    awake = dig(dto, "awakeSleepSeconds")
    score = dig(dto, "sleepScores", "overall", "value") or dig(sleep, "sleepScores", "overall", "value")
    qualifier = dig(dto, "sleepScores", "overall", "qualifierKey") or dig(sleep, "sleepScores", "overall", "qualifierKey")
    lines.append("## Sleep")
    if total_sleep:
        lines.append(f"- Total sleep: {hms(total_sleep)}")
        lines.append(f"- Deep / Light / REM / Awake: {hms(deep)} / {hms(light)} / {hms(rem)} / {hms(awake)}")
        if score is not None:
            qualifier_txt = f" ({qualifier})" if qualifier else ""
            lines.append(f"- Sleep score: {score}{qualifier_txt}")
    else:
        lines.append("- Not available for this day")
    lines.append("")

    hrv = raw.get("hrv") or {}
    hrv_summary = dig(hrv, "hrvSummary", default={}) or {}
    last_night_avg = dig(hrv_summary, "lastNightAvg")
    hrv_status = dig(hrv_summary, "status")
    weekly_avg = dig(hrv_summary, "weeklyAvg")
    lines.append("## HRV")
    if last_night_avg is not None:
        lines.append(f"- Last night average: {last_night_avg} ms")
        if hrv_status:
            lines.append(f"- Status: {hrv_status}")
        if weekly_avg is not None:
            lines.append(f"- 7-day average: {weekly_avg} ms")
    else:
        lines.append("- Not available for this day")
    lines.append("")

    rhr = raw.get("resting_hr") or {}
    rhr_value = dig(
        rhr, "allMetrics", "metricsMap", "WELLNESS_RESTING_HEART_RATE", 0, "value"
    )
    if rhr_value is None:
        summary = raw.get("summary") or {}
        rhr_value = dig(summary, "restingHeartRate")
    lines.append("## Resting heart rate")
    lines.append(f"- {rhr_value} bpm" if rhr_value is not None else "- Not available for this day")
    lines.append("")

    bb = raw.get("body_battery") or []
    bb_day = bb[0] if isinstance(bb, list) and bb else (bb if isinstance(bb, dict) else {})
    charged = dig(bb_day, "charged")
    drained = dig(bb_day, "drained")
    values = dig(bb_day, "bodyBatteryValuesArray") or []
    start_val = values[0][1] if values else None
    end_val = values[-1][1] if values else None
    lines.append("## Body Battery")
    if charged is not None or start_val is not None:
        if start_val is not None and end_val is not None:
            lines.append(f"- Start of day: {start_val} / End of day: {end_val}")
        if charged is not None or drained is not None:
            lines.append(f"- Charged: {charged} / Drained: {drained}")
    else:
        lines.append("- Not available for this day")
    lines.append("")

    stress = raw.get("stress") or {}
    avg_stress = dig(stress, "avgStressLevel") or dig(stress, "overallStressLevel")
    max_stress = dig(stress, "maxStressLevel")
    lines.append("## Stress")
    if avg_stress is not None and avg_stress != -1:
        line = f"- Average: {avg_stress}"
        if max_stress is not None:
            line += f" / Max: {max_stress}"
        lines.append(line)
    else:
        lines.append("- Not available for this day")
    lines.append("")

    tr = raw.get("training_readiness") or []
    tr_day = tr[0] if isinstance(tr, list) and tr else (tr if isinstance(tr, dict) else {})
    tr_score = dig(tr_day, "score")
    tr_level = dig(tr_day, "level")
    tr_feedback = dig(tr_day, "feedbackLong") or dig(tr_day, "feedbackShort")
    lines.append("## Training readiness")
    if tr_score is not None:
        line = f"- Score: {tr_score}"
        if tr_level:
            line += f" ({tr_level})"
        lines.append(line)
        if tr_feedback:
            lines.append(f"- {tr_feedback}")
    else:
        lines.append("- Not available for this day")
    lines.append("")

    summary = raw.get("summary") or {}
    steps = dig(summary, "totalSteps")
    calories = dig(summary, "totalKilocalories")
    lines.append("## Steps & calories")
    if steps is not None or calories is not None:
        if steps is not None:
            lines.append(f"- Steps: {steps:,}")
        if calories is not None:
            lines.append(f"- Calories: {calories:,.0f}" if isinstance(calories, float) else f"- Calories: {calories:,}")
    else:
        lines.append("- Not available for this day")
    lines.append("")

    lines.append("---")
    lines.append(f'Full raw data for this day is in `data.json` under `wellness["{day_str}"]`.')
    return "\n".join(lines) + "\n"


def activity_markdown(activity):
    activity_id = activity.get("activityId")
    name = activity.get("activityName") or "Activity"
    start = activity.get("startTimeLocal") or ""
    day_str = start.split(" ")[0] if start else "unknown-date"
    activity_type = dig(activity, "activityType", "typeKey") or "unknown"
    duration = activity.get("duration")
    distance_m = activity.get("distance")
    avg_hr = activity.get("averageHR")
    max_hr = activity.get("maxHR")
    calories = activity.get("calories")
    elevation_gain = activity.get("elevationGain")
    aerobic_te = activity.get("aerobicTrainingEffect")
    anaerobic_te = activity.get("anaerobicTrainingEffect")

    lines = [f"# {name} — {day_str}", ""]
    lines.append(f"- Type: {activity_type}")
    if start:
        lines.append(f"- Start time: {start}")
    if duration is not None:
        lines.append(f"- Duration: {hms(duration)}")
    if distance_m is not None:
        lines.append(f"- Distance: {distance_m / 1000:.2f} km")
    if avg_hr is not None or max_hr is not None:
        avg_hr_txt = f"{avg_hr:.0f}" if avg_hr is not None else "n/a"
        max_hr_txt = f"{max_hr:.0f}" if max_hr is not None else "n/a"
        lines.append(f"- Avg HR / Max HR: {avg_hr_txt} / {max_hr_txt} bpm")
    if calories is not None:
        lines.append(f"- Calories: {calories:,.0f}" if isinstance(calories, float) else f"- Calories: {calories:,}")
    if elevation_gain is not None:
        lines.append(f"- Elevation gain: {elevation_gain:.0f} m")
    if aerobic_te is not None or anaerobic_te is not None:
        aerobic_txt = f"{aerobic_te:.1f}" if aerobic_te is not None else "n/a"
        anaerobic_txt = f"{anaerobic_te:.1f}" if anaerobic_te is not None else "n/a"
        lines.append(f"- Training effect (aerobic / anaerobic): {aerobic_txt} / {anaerobic_txt}")
    lines.append("")
    lines.append("---")
    lines.append(f'Full raw data for this activity is in `data.json` under `activities["{activity_id}"]`.')
    return "\n".join(lines) + "\n"


def safe_filename(text):
    keep = [c if c.isalnum() or c in "-_" else "-" for c in text.lower().replace(" ", "-")]
    slug = "".join(keep)
    while "--" in slug:
        slug = slug.replace("--", "-")
    return slug.strip("-")[:60]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=3, help="How many recent days to pull")
    args = parser.parse_args()

    OUT_DIR.mkdir(exist_ok=True)
    WELLNESS_DIR.mkdir(exist_ok=True)
    WORKOUTS_DIR.mkdir(exist_ok=True)

    client = load_client()
    data = load_data_json()

    today = date.today()
    days = [today - timedelta(days=i) for i in range(args.days)]

    print(f"Pulling wellness data for {len(days)} day(s)...")
    for d in days:
        day_str = d.isoformat()
        raw = fetch_wellness_day(client, day_str)
        data["wellness"][day_str] = raw
        (WELLNESS_DIR / f"{day_str}.md").write_text(wellness_markdown(day_str, raw), encoding="utf-8")
        print(f"  wellness: {day_str}")

    earliest = days[-1].isoformat()
    print(f"Pulling activities since {earliest}...")
    try:
        activities = client.get_activities(0, max(20, args.days * 5))
    except Exception as exc:
        print(f"  could not fetch activities: {exc}", file=sys.stderr)
        activities = []

    pulled = 0
    for activity in activities:
        start = activity.get("startTimeLocal") or ""
        activity_day = start.split(" ")[0] if start else None
        if not activity_day or activity_day < earliest:
            continue
        activity_id = str(activity.get("activityId"))
        data["activities"][activity_id] = activity
        name_slug = safe_filename(activity.get("activityName") or "activity")
        filename = f"{activity_day}_{name_slug}_{activity_id}.md"
        (WORKOUTS_DIR / filename).write_text(activity_markdown(activity), encoding="utf-8")
        pulled += 1
        print(f"  workout: {activity_day} - {activity.get('activityName')}")

    save_data_json(data)
    print(f"Done. {len(days)} wellness day(s), {pulled} workout(s) written to {OUT_DIR}")


if __name__ == "__main__":
    main()
