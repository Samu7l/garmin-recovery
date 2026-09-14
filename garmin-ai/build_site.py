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

        sleep_dto = (raw.get("sleep") or {}).get("dailySleepDTO") or {}
        sleep_seconds = sleep_dto.get("sleepTimeSeconds") or (raw.get("sleep_bulk") or {}).get("total_sleep_s")

        days.append({
            "date": date_str,
            "steps": summary.get("totalSteps"),
            "calories": summary.get("totalKilocalories"),
            "resting_hr": resting_hr,
            "avg_stress": avg_stress,
            "max_stress": max_stress,
            "sleep_seconds": sleep_seconds,
            # bulk_backfill's avg_stress is a flat weekly average, not a real
            # per-day reading - the frontend needs to know which is which so
            # it doesn't feed repeated placeholder values into correlations.
            "stress_is_daily": raw.get("source") != "bulk_backfill",
        })
    return days


def build_vo2max(data):
    """Merge the one-off range backfill (data["vo2max_history"]) with whatever
    daily sync has picked up more recently via each day's training_status."""
    points = dict(data.get("vo2max_history") or {})
    for date_str, raw in data["wellness"].items():
        generic = ((raw.get("training_status") or {}).get("mostRecentVO2Max") or {}).get("generic") or {}
        cal_date = generic.get("calendarDate")
        value = generic.get("vo2MaxValue")
        if cal_date and value is not None:
            points[cal_date] = {"vo2max": value, "fitness_age": generic.get("fitnessAge")}
    return [
        {"date": d, "vo2max": v.get("vo2max"), "fitness_age": v.get("fitness_age")}
        for d, v in sorted(points.items()) if v.get("vo2max") is not None
    ]


def build_training_status(data):
    """Only daily sync fetches this, so scan back from today for the most
    recent day that actually has it (bulk-backfilled days won't)."""
    for date_str, raw in sorted(data["wellness"].items(), reverse=True):
        latest = ((raw.get("training_status") or {}).get("mostRecentTrainingStatus") or {}).get("latestTrainingStatusData") or {}
        entry = next(iter(latest.values()), None)
        if not entry:
            continue
        return {
            "date": entry.get("calendarDate") or date_str,
            "status_code": entry.get("trainingStatus"),
            "weekly_load": entry.get("weeklyTrainingLoad"),
            "load_min": entry.get("loadTunnelMin"),
            "load_max": entry.get("loadTunnelMax"),
            "load_trend": entry.get("loadLevelTrend"),
            "sport": entry.get("sport"),
        }
    return None


def build_fitness_age(data):
    for date_str, raw in sorted(data["wellness"].items(), reverse=True):
        fa = raw.get("fitness_age") or {}
        if fa.get("fitnessAge") is not None:
            return {
                "date": date_str,
                "chronological_age": fa.get("chronologicalAge"),
                "fitness_age": fa.get("fitnessAge"),
                "achievable_fitness_age": fa.get("achievableFitnessAge"),
            }
    return None


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
    sleep_history = data.get("sleep_history") or {}
    vo2max = build_vo2max(data)
    training_status = build_training_status(data)
    fitness_age = build_fitness_age(data)

    DOCS_ACTIVITIES_DIR.mkdir(parents=True, exist_ok=True)

    (DOCS_DATA_DIR / "overview.json").write_text(
        json.dumps(
            {
                "days": days,
                "workouts": workouts,
                "sleep_history": sleep_history,
                "vo2max": vo2max,
                "training_status": training_status,
                "fitness_age": fitness_age,
            },
            ensure_ascii=False, default=str,
        ),
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

    print(f"wrote {DOCS_DIR} : {len(days)} days, {len(workouts)} workouts, "
          f"{n_activities} activity detail files, {len(sleep_history)} historical sleep day(s)")


if __name__ == "__main__":
    main()
