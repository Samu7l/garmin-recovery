"""
Builds the public GitHub Pages site into ../docs/ (repo root docs/ folder):
  docs/index.html              - static page shell (from site_template.html)
  docs/data/overview.json      - wellness days + workout summaries
  docs/data/activities/<id>.json - per-activity series, laps, GPS route

Unlike the Claude-artifact dashboard, this has no baked map images - the page
renders a real interactive Leaflet map with live OpenStreetMap tiles, using
the "route" points already saved by garmin_activity_detail.py.

This data is intentionally public once pushed to GitHub - it does not include
the full raw Garmin payloads, wellness markdown notes, or auth tokens.
"""

import json
import shutil
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parent
DATA_FILE = BASE_DIR / "garmin" / "data.json"
DETAIL_DIR = BASE_DIR / "garmin" / "activity_details"
TEMPLATE_FILE = BASE_DIR / "site_template.html"

DOCS_DIR = REPO_ROOT / "docs"
DOCS_DATA_DIR = DOCS_DIR / "data"
DOCS_ACTIVITIES_DIR = DOCS_DATA_DIR / "activities"


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


def main():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    days = build_days(data)
    workouts = build_workouts(data)

    DOCS_ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)

    (DOCS_DATA_DIR / "overview.json").write_text(
        json.dumps({"days": days, "workouts": workouts}, ensure_ascii=False, default=str),
        encoding="utf-8",
    )

    n_activities = 0
    for json_path in DETAIL_DIR.glob("*.json"):
        activity_id = json_path.stem
        detail = json.loads(json_path.read_text(encoding="utf-8"))
        out = {
            "series": detail.get("series"),
            "laps": detail.get("laps") or [],
            "route": detail.get("route") or [],
        }
        (DOCS_ACTIVITIES_DIR / f"{activity_id}.json").write_text(
            json.dumps(out, ensure_ascii=False, default=str), encoding="utf-8"
        )
        n_activities += 1

    shutil.copyfile(TEMPLATE_FILE, DOCS_DIR / "index.html")

    print(f"wrote {DOCS_DIR} : {len(days)} days, {len(workouts)} workouts, {n_activities} activity detail files")


if __name__ == "__main__":
    main()
