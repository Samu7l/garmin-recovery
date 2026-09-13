"""
Assembles the dashboard HTML from garmin/data.json (wellness + activity
summaries) and garmin/activity_details/*.json + *_map.jpg (per-activity GPS
route, HR/pace/elevation/cadence streams, laps), using dashboard_template.html
as the shell.

Run garmin_sync.py and garmin_activity_detail.py first to make sure the data
this reads from is current, then run this to produce the file that gets
published as the artifact.
"""

import argparse
import base64
import json
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
DATA_FILE = BASE_DIR / "garmin" / "data.json"
DETAIL_DIR = BASE_DIR / "garmin" / "activity_details"
TEMPLATE_FILE = BASE_DIR / "dashboard_template.html"


def safe_json(obj):
    return json.dumps(obj, ensure_ascii=False, default=str).replace("</", "<\\/")


def build_days(data):
    days = []
    for date_str, raw in sorted(data["wellness"].items()):
        summary = raw.get("summary") or {}
        resting_hr = None
        rhr_raw = raw.get("resting_hr") or {}
        metrics = (rhr_raw.get("allMetrics") or {}).get("metricsMap") or {}
        rhr_list = metrics.get("WELLNESS_RESTING_HEART_RATE") or []
        if rhr_list and rhr_list[0].get("value") is not None:
            resting_hr = rhr_list[0]["value"]
        elif summary.get("restingHeartRate") is not None:
            resting_hr = summary.get("restingHeartRate")

        avg_stress = summary.get("averageStressLevel")
        if avg_stress == -1:
            avg_stress = None
        max_stress = summary.get("maxStressLevel")

        days.append({
            "date": date_str,
            "steps": summary.get("totalSteps"),
            "calories": summary.get("totalKilocalories"),
            "resting_hr": resting_hr,
            "avg_stress": avg_stress,
            "max_stress": max_stress,
        })
    return days


def build_workouts(data):
    workouts = []
    for act_id, act in data["activities"].items():
        start = act.get("startTimeLocal") or ""
        workouts.append({
            "id": act_id,
            "name": act.get("activityName"),
            "type": (act.get("activityType") or {}).get("typeKey"),
            "date": start.split(" ")[0] if start else None,
            "start": start,
            "duration_s": act.get("duration"),
            "distance_m": act.get("distance"),
            "avg_hr": act.get("averageHR"),
            "max_hr": act.get("maxHR"),
            "calories": act.get("calories"),
            "aerobic_te": act.get("aerobicTrainingEffect"),
            "anaerobic_te": act.get("anaerobicTrainingEffect"),
            "elevation_gain": act.get("elevationGain"),
        })
    workouts.sort(key=lambda w: w["date"] or "")
    return workouts


def build_activity_details():
    details = {}
    if not DETAIL_DIR.exists():
        return details
    for json_path in DETAIL_DIR.glob("*.json"):
        activity_id = json_path.stem
        detail = json.loads(json_path.read_text(encoding="utf-8"))
        map_data_uri = None
        if detail.get("has_map"):
            map_path = DETAIL_DIR / f"{activity_id}_map.jpg"
            if map_path.exists():
                encoded = base64.b64encode(map_path.read_bytes()).decode("ascii")
                map_data_uri = f"data:image/jpeg;base64,{encoded}"
        details[activity_id] = {
            "series": detail.get("series"),
            "laps": detail.get("laps") or [],
            "has_map": bool(map_data_uri),
            "map_data_uri": map_data_uri,
        }
    return details


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, help="Path to write the assembled dashboard HTML to")
    args = parser.parse_args()

    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    days = build_days(data)
    workouts = build_workouts(data)
    activity_details = build_activity_details()

    html = TEMPLATE_FILE.read_text(encoding="utf-8")
    html = html.replace("__DAYS_JSON__", safe_json(days))
    html = html.replace("__WORKOUTS_JSON__", safe_json(workouts))
    html = html.replace("__ACTIVITY_DETAILS_JSON__", safe_json(activity_details))

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(html, encoding="utf-8")
    print(f"wrote {out_path} ({len(html):,} bytes), {len(days)} days, {len(workouts)} workouts, {len(activity_details)} activity details")


if __name__ == "__main__":
    main()
