"""
Renders a real OpenStreetMap-tile background with a GPS route drawn on top,
colored by pace, as a single flat PNG. Tiles are cached locally so re-runs
don't re-download anything for activities already rendered.

This produces a static image (no live map, no runtime network calls) so it
can be embedded directly into a self-contained dashboard page.
"""

import math
from io import BytesIO
from pathlib import Path

import requests
from PIL import Image, ImageDraw

TILE_SIZE = 256
TILE_CACHE_DIR = Path(__file__).resolve().parent / ".tilecache"
USER_AGENT = "garmin-ai-personal-dashboard/1.0 (single-user local script, low volume)"

# Sequential blue ramp (light -> dark), per the dataviz palette's sequential hue.
SPEED_RAMP = [
    (0.00, (134, 182, 239)),  # step 250 #86b6ef - slowest
    (0.25, (85, 152, 231)),   # step 350 #5598e7
    (0.50, (42, 120, 214)),   # step 450 #2a78d6
    (0.75, (28, 92, 171)),    # step 550 #1c5cab
    (1.00, (16, 66, 129)),    # step 650 #104281 - fastest
]


def _lerp(a, b, t):
    return a + (b - a) * t


def _ramp_color(t):
    t = max(0.0, min(1.0, t))
    for (t0, c0), (t1, c1) in zip(SPEED_RAMP, SPEED_RAMP[1:]):
        if t0 <= t <= t1:
            local_t = (t - t0) / (t1 - t0) if t1 > t0 else 0
            return tuple(int(round(_lerp(c0[i], c1[i], local_t))) for i in range(3))
    return SPEED_RAMP[-1][1]


def latlon_to_pixel(lat, lon, zoom):
    lat_rad = math.radians(lat)
    n = 2.0 ** zoom
    x = (lon + 180.0) / 360.0 * n * TILE_SIZE
    y = (1.0 - math.log(math.tan(lat_rad) + 1 / math.cos(lat_rad)) / math.pi) / 2.0 * n * TILE_SIZE
    return x, y


def _fetch_tile(z, x, y):
    n = 2 ** z
    if x < 0 or y < 0 or x >= n or y >= n:
        return None
    cache_path = TILE_CACHE_DIR / str(z) / str(x) / f"{y}.png"
    if cache_path.exists():
        return Image.open(cache_path).convert("RGB")
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    url = f"https://tile.openstreetmap.org/{z}/{x}/{y}.png"
    resp = requests.get(url, headers={"User-Agent": USER_AGENT}, timeout=15)
    resp.raise_for_status()
    cache_path.write_bytes(resp.content)
    return Image.open(BytesIO(resp.content)).convert("RGB")


def _pick_zoom(min_lat, max_lat, min_lon, max_lon, target_px=760, max_zoom=17, min_zoom=9):
    for zoom in range(max_zoom, min_zoom - 1, -1):
        x0, y0 = latlon_to_pixel(max_lat, min_lon, zoom)
        x1, y1 = latlon_to_pixel(min_lat, max_lon, zoom)
        w, h = abs(x1 - x0), abs(y1 - y0)
        if w <= target_px and h <= target_px:
            return zoom
    return min_zoom


def render_route_map(points, out_path, target_px=760, padding_frac=0.14):
    """points: list of (lat, lon, speed_mps or None). Returns True if rendered."""
    coords = [(p[0], p[1]) for p in points if p[0] is not None and p[1] is not None]
    if len(coords) < 2:
        return False

    lats = [c[0] for c in coords]
    lons = [c[1] for c in coords]
    min_lat, max_lat = min(lats), max(lats)
    min_lon, max_lon = min(lons), max(lons)
    lat_pad = (max_lat - min_lat) * padding_frac or 0.001
    lon_pad = (max_lon - min_lon) * padding_frac or 0.001
    min_lat -= lat_pad; max_lat += lat_pad
    min_lon -= lon_pad; max_lon += lon_pad

    zoom = _pick_zoom(min_lat, max_lat, min_lon, max_lon, target_px=target_px)

    x0, y0 = latlon_to_pixel(max_lat, min_lon, zoom)  # top-left
    x1, y1 = latlon_to_pixel(min_lat, max_lon, zoom)  # bottom-right
    left, top = min(x0, x1), min(y0, y1)
    right, bottom = max(x0, x1), max(y0, y1)

    tile_x0, tile_y0 = int(left // TILE_SIZE), int(top // TILE_SIZE)
    tile_x1, tile_y1 = int(right // TILE_SIZE), int(bottom // TILE_SIZE)

    canvas_w = (tile_x1 - tile_x0 + 1) * TILE_SIZE
    canvas_h = (tile_y1 - tile_y0 + 1) * TILE_SIZE
    canvas = Image.new("RGB", (canvas_w, canvas_h), (225, 224, 217))

    for tx in range(tile_x0, tile_x1 + 1):
        for ty in range(tile_y0, tile_y1 + 1):
            tile = _fetch_tile(zoom, tx, ty)
            if tile is not None:
                canvas.paste(tile, ((tx - tile_x0) * TILE_SIZE, (ty - tile_y0) * TILE_SIZE))

    crop_left = int(left - tile_x0 * TILE_SIZE)
    crop_top = int(top - tile_y0 * TILE_SIZE)
    crop_right = crop_left + int(right - left)
    crop_bottom = crop_top + int(bottom - top)
    canvas = canvas.crop((crop_left, crop_top, crop_right, crop_bottom))

    draw = ImageDraw.Draw(canvas, "RGBA")

    def to_local(lat, lon):
        px, py = latlon_to_pixel(lat, lon, zoom)
        return (px - left, py - top)

    speeds = [p[2] for p in points if p[2] is not None and p[2] > 0.3]
    if speeds:
        speeds_sorted = sorted(speeds)
        lo = speeds_sorted[int(len(speeds_sorted) * 0.05)]
        hi = speeds_sorted[int(len(speeds_sorted) * 0.95)] or lo + 1
    else:
        lo, hi = 0, 1

    pts_local = [(to_local(p[0], p[1]), p[2]) for p in points if p[0] is not None and p[1] is not None]

    # halo pass (dark, underneath) then colored pass on top, for legibility over any tile
    for (a, _), (b, _) in zip(pts_local, pts_local[1:]):
        draw.line([a, b], fill=(20, 20, 20, 130), width=7)
    for (a, sa), (b, sb) in zip(pts_local, pts_local[1:]):
        speed = sb if sb is not None else sa
        t = (speed - lo) / (hi - lo) if speed is not None and hi > lo else 0.5
        color = _ramp_color(t)
        draw.line([a, b], fill=color + (255,), width=4)

    if pts_local:
        start_xy = pts_local[0][0]
        end_xy = pts_local[-1][0]
        r = 7
        draw.ellipse([start_xy[0]-r, start_xy[1]-r, start_xy[0]+r, start_xy[1]+r], fill=(28, 131, 0, 255), outline=(255, 255, 255, 255), width=2)
        draw.ellipse([end_xy[0]-r, end_xy[1]-r, end_xy[0]+r, end_xy[1]+r], fill=(211, 43, 43, 255), outline=(255, 255, 255, 255), width=2)

    # OSM attribution (required by tile usage policy)
    attr = "© OpenStreetMap contributors"
    strip_h = 16
    w, h = canvas.size
    draw.rectangle([0, h - strip_h, w, h], fill=(255, 255, 255, 170))
    draw.text((6, h - strip_h + 2), attr, fill=(30, 30, 30, 255))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path, format="PNG", optimize=True)
    return True
