"""
Fetches GPS track, heart rate / speed / elevation / cadence streams, and lap
(circuit) data for each workout already known in garmin/data.json, and
renders a real-map image with the pace-colored route drawn on it.

Read-only against Garmin. Each activity is cached forever once fetched
(garmin/activity_details/<id>.json + <id>_map.png) since a completed
activity's data never changes - re-running only fetches new activities.
"""

import json
import sys
from pathlib import Path

from garmin_sync import load_client, DATA_FILE
from map_render import render_route_map

BASE_DIR = Path(__file__).resolve().parent
DETAIL_DIR = BASE_DIR / "garmin" / "activity_details"

TARGET_POINTS = 200
SMOOTH_WINDOW = 5


def smooth(values, window=SMOOTH_WINDOW):
    n = len(values)
    out = []
    half = window // 2
    for i in range(n):
        lo, hi = max(0, i - half), min(n, i + half + 1)
        chunk = [v for v in values[lo:hi] if v is not None]
        out.append(sum(chunk) / len(chunk) if chunk else None)
    return out


def build_indexed_samples(details):
    descs = details.get("metricDescriptors") or []
    idx = {d["key"]: d["metricsIndex"] for d in descs}
    adm = details.get("activityDetailMetrics") or []

    def val(m, key):
        i = idx.get(key)
        if i is None:
            return None
        v = m["metrics"][i]
        return v

    samples = []
    for m in adm:
        samples.append({
            "lat": val(m, "directLatitude"),
            "lon": val(m, "directLongitude"),
            "distance_m": val(m, "sumDistance"),
            "speed_mps": val(m, "directSpeed"),
            "hr": val(m, "directHeartRate"),
            "elevation_m": val(m, "directElevation"),
            "cadence": val(m, "directRunCadence") or val(m, "directDoubleCadence"),
        })
    return samples


def filter_pace_outliers(speed_series, min_ratio=0.35, abs_floor=0.3):
    """Null out samples far slower than the activity's own typical pace.

    A brief full stop (warmup stretch, traffic light) reads as a near-zero
    speed sample, which turns into an enormous pace spike (pace = 1/speed)
    that dwarfs the rest of the chart. Real pace variation (surges, hills,
    fatigue) stays well within a fraction of the activity's median moving
    speed, so anything below that band is a stop, not a slow point, and
    gets treated as missing data (a gap) rather than plotted.
    """
    valid = sorted(s for s in speed_series if s is not None and s > 0.05)
    if len(valid) < 5:
        return speed_series
    median = valid[len(valid) // 2]
    floor = max(abs_floor, median * min_ratio)
    return [s if (s is not None and s >= floor) else None for s in speed_series]


def resample_by_distance(samples, target_points=TARGET_POINTS):
    with_dist = [s for s in samples if s["distance_m"] is not None]
    if len(with_dist) < 2:
        return {"distance_km": [], "hr": [], "speed_mps": [], "elevation_m": [], "cadence": []}

    total_dist = with_dist[-1]["distance_m"]
    if total_dist <= 0:
        return {"distance_km": [], "hr": [], "speed_mps": [], "elevation_m": [], "cadence": []}

    hr_s = smooth([s["hr"] for s in with_dist])
    speed_s = smooth([s["speed_mps"] for s in with_dist])
    elev_s = smooth([s["elevation_m"] for s in with_dist])
    cad_s = smooth([s["cadence"] for s in with_dist])

    n_bins = min(target_points, len(with_dist))
    out = {"distance_km": [], "hr": [], "speed_mps": [], "elevation_m": [], "cadence": []}
    j = 0
    for b in range(n_bins):
        target = (b / (n_bins - 1)) * total_dist if n_bins > 1 else 0
        while j < len(with_dist) - 1 and with_dist[j]["distance_m"] < target:
            j += 1
        out["distance_km"].append(round(target / 1000, 3))
        out["hr"].append(round(hr_s[j], 1) if hr_s[j] is not None else None)
        out["speed_mps"].append(round(speed_s[j], 3) if speed_s[j] is not None else None)
        out["elevation_m"].append(round(elev_s[j], 1) if elev_s[j] is not None else None)
        out["cadence"].append(round(cad_s[j], 1) if cad_s[j] is not None else None)
    out["speed_mps"] = filter_pace_outliers(out["speed_mps"])
    return out


def build_laps(splits):
    lap_dtos = (splits or {}).get("lapDTOs") or []
    if len(lap_dtos) < 2:
        return []
    laps = []
    for lap in lap_dtos:
        laps.append({
            "index": lap.get("lapIndex"),
            "distance_m": lap.get("distance"),
            "duration_s": lap.get("duration"),
            "avg_speed_mps": lap.get("averageSpeed"),
            "max_speed_mps": lap.get("maxSpeed"),
            "elevation_gain": lap.get("elevationGain"),
            "elevation_loss": lap.get("elevationLoss"),
            "avg_hr": lap.get("averageHR"),
            "max_hr": lap.get("maxHR"),
            "avg_cadence": lap.get("averageRunCadence"),
        })
    return laps


ROUTE_MAX_POINTS = 600


def downsample_route(gps_points, max_points=ROUTE_MAX_POINTS):
    if len(gps_points) <= max_points:
        return [[round(lat, 6), round(lon, 6), round(spd, 3) if spd is not None else None] for lat, lon, spd in gps_points]
    stride = len(gps_points) / max_points
    out = []
    i = 0.0
    while int(i) < len(gps_points):
        lat, lon, spd = gps_points[int(i)]
        out.append([round(lat, 6), round(lon, 6), round(spd, 3) if spd is not None else None])
        i += stride
    return out


def process_activity(client, activity_id, activity_type):
    detail_json_path = DETAIL_DIR / f"{activity_id}.json"
    map_path = DETAIL_DIR / f"{activity_id}_map.png"
    if detail_json_path.exists():
        return "cached"

    try:
        details = client.get_activity_details(activity_id, maxchart=2000, maxpoly=4000)
        splits = client.get_activity_splits(activity_id)
    except Exception as exc:
        print(f"  [{activity_id}] failed to fetch details: {exc}", file=sys.stderr)
        return "error"

    samples = build_indexed_samples(details)
    series = resample_by_distance(samples)
    laps = build_laps(splits)

    gps_points = [(s["lat"], s["lon"], s["speed_mps"]) for s in samples if s["lat"] is not None and s["lon"] is not None]
    has_map = False
    if len(gps_points) >= 2:
        try:
            has_map = render_route_map(gps_points, map_path)
        except Exception as exc:
            print(f"  [{activity_id}] map render failed: {exc}", file=sys.stderr)
            has_map = False

    out = {
        "activity_id": activity_id,
        "activity_type": activity_type,
        "series": series,
        "laps": laps,
        "has_map": has_map,
        "route": downsample_route(gps_points),
    }
    DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    detail_json_path.write_text(json.dumps(out, indent=2, ensure_ascii=False, default=str), encoding="utf-8")
    return "fetched"


def main():
    data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    activities = data.get("activities", {})
    print(f"{len(activities)} known activities")
    client = load_client()
    for activity_id, activity in activities.items():
        activity_type = (activity.get("activityType") or {}).get("typeKey")
        status = process_activity(client, activity_id, activity_type)
        print(f"  {activity_id} ({activity.get('activityName')}): {status}")


if __name__ == "__main__":
    main()
