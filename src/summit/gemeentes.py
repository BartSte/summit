"""Find Dutch municipalities crossed by cached Garmin track points."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import requests

PDOK_WFS_URL = (
    "https://service.pdok.nl/kadaster/bestuurlijkegebieden/wfs/v1_0"
    "?service=WFS&version=2.0.0&request=GetFeature"
    "&typeNames=bestuurlijkegebieden:Gemeentegebied"
    "&outputFormat=application/json&srsName=EPSG:4326"
)


def _on_segment(point: tuple[float, float], a: list[float], b: list[float]) -> bool:
    """Return whether point lies on the closed line segment a-b."""
    x, y = point
    cross = (x - a[0]) * (b[1] - a[1]) - (y - a[1]) * (b[0] - a[0])
    if abs(cross) > 1e-10:
        return False
    return (
        min(a[0], b[0]) - 1e-10 <= x <= max(a[0], b[0]) + 1e-10
        and min(a[1], b[1]) - 1e-10 <= y <= max(a[1], b[1]) + 1e-10
    )


def _ring_relation(point: tuple[float, float], ring: list[list[float]]) -> int:
    """Return 1 inside, 0 outside, or 2 on the boundary of a linear ring."""
    inside = False
    x, y = point
    for index in range(len(ring) - 1):
        a, b = ring[index], ring[index + 1]
        if _on_segment(point, a, b):
            return 2
        if (a[1] > y) != (b[1] > y):
            intersection_x = (b[0] - a[0]) * (y - a[1]) / (b[1] - a[1]) + a[0]
            if x < intersection_x:
                inside = not inside
    return 1 if inside else 0


def point_in_geometry(point: tuple[float, float], geometry: dict[str, Any]) -> bool:
    """Test GeoJSON Polygon/MultiPolygon containment, including boundaries.

    Polygon holes exclude their interiors, while all polygon boundaries
    (including hole boundaries) count as crossed.
    """
    geometry_type = geometry.get("type")
    coordinates = geometry.get("coordinates", [])
    polygons = [coordinates] if geometry_type == "Polygon" else coordinates
    if geometry_type not in {"Polygon", "MultiPolygon"}:
        return False
    for polygon in polygons:
        if not polygon:
            continue
        outer = _ring_relation(point, polygon[0])
        if outer == 2:
            return True
        if outer != 1:
            continue
        excluded = False
        for hole in polygon[1:]:
            relation = _ring_relation(point, hole)
            if relation == 2:
                return True
            if relation == 1:
                excluded = True
                break
        if not excluded:
            return True
    return False


def load_boundaries(cache_file: Path, refresh: bool = False) -> dict[str, Any]:
    """Load municipality GeoJSON from cache, downloading PDOK data as needed."""
    if cache_file.exists() and not refresh:
        return json.loads(cache_file.read_text())
    response = requests.get(PDOK_WFS_URL, timeout=60)
    response.raise_for_status()
    data = response.json()
    if data.get("type") != "FeatureCollection" or not isinstance(data.get("features"), list):
        raise ValueError("PDOK response is not a GeoJSON FeatureCollection")
    cache_file.parent.mkdir(parents=True, exist_ok=True)
    cache_file.write_text(json.dumps(data, ensure_ascii=False))
    return data


def _track_points(path: Path) -> list[tuple[float, float]]:
    try:
        data = json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    points = []
    for item in data:
        if (
            isinstance(item, list)
            and len(item) >= 2
            and isinstance(item[0], (int, float))
            and isinstance(item[1], (int, float))
        ):
            points.append((float(item[1]), float(item[0])))  # GeoJSON: lon, lat
    return points


def _geometry_bbox(geometry: dict[str, Any]) -> tuple[float, float, float, float] | None:
    """Return the lon/lat bounding box for a Polygon or MultiPolygon."""
    coordinates = geometry.get("coordinates")
    points: list[list[float]] = []

    def collect(value: Any) -> None:
        if (
            isinstance(value, list)
            and len(value) >= 2
            and isinstance(value[0], (int, float))
            and isinstance(value[1], (int, float))
        ):
            points.append(value)
        elif isinstance(value, list):
            for child in value:
                collect(child)

    collect(coordinates)
    if not points:
        return None
    return (
        min(point[0] for point in points),
        min(point[1] for point in points),
        max(point[0] for point in points),
        max(point[1] for point in points),
    )


def _display_geometry(geometry: Any) -> Any:
    """Return a topology-preserving, map-sized copy of a boundary geometry."""
    if not isinstance(geometry, dict):
        return geometry
    try:
        from shapely.geometry import mapping, shape

        simplified = shape(geometry).simplify(0.0002, preserve_topology=True)
        # Normalize tuples from ``mapping`` back to JSON-compatible lists.
        return json.loads(json.dumps(mapping(simplified)))
    except (ImportError, ValueError, TypeError):
        return geometry


def _province_display_geometries(features: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Dissolve exact municipality borders before simplifying province outlines."""
    try:
        from shapely.geometry import mapping, shape
        from shapely.ops import unary_union
    except ImportError:
        return []

    grouped: dict[tuple[str, str], list[Any]] = {}
    for feature in features:
        properties = feature.get("properties", {})
        code = str(properties.get("ligtInProvincieCode") or "")
        name = str(properties.get("ligtInProvincieNaam") or "")
        geometry = feature.get("geometry")
        if not name or not isinstance(geometry, dict):
            continue
        try:
            candidate = shape(geometry)
            if not candidate.is_valid:
                candidate = candidate.buffer(0)
            if not candidate.is_empty:
                grouped.setdefault((code, name), []).append(candidate)
        except (TypeError, ValueError):
            continue

    provinces = []
    for (code, name), geometries in sorted(grouped.items(), key=lambda item: item[0][1]):
        dissolved = unary_union(geometries).simplify(0.0002, preserve_topology=True)
        provinces.append({
            "code": code,
            "name": name,
            "geometry": json.loads(json.dumps(mapping(dissolved))),
        })
    return provinces


def generate(
    boundaries: dict[str, Any], tracks_dir: Path, output_file: Path
) -> dict[str, Any]:
    """Generate municipality visit data from exact points in Garmin tracks."""
    previous_visited: set[str] = set()
    previous: dict[str, Any] = {}
    if output_file.exists():
        try:
            previous = json.loads(output_file.read_text())
            previous_visited = {
                str(item["code"])
                for item in previous.get("municipalities", [])
                if item.get("visited")
            }
        except (OSError, json.JSONDecodeError, KeyError, TypeError):
            previous = {}

    features = boundaries.get("features", [])
    # Shapely's spatial index performs the historical scan in bulk. The pure
    # Python grid below remains as a defensive fallback for malformed geometry.
    indexed_features: list[dict[str, Any]] = []
    indexed_geometries: list[Any] = []
    try:
        from shapely.geometry import shape
        from shapely.strtree import STRtree

        for feature in features:
            geometry = feature.get("geometry")
            if not isinstance(geometry, dict):
                continue
            candidate = shape(geometry)
            if not candidate.is_empty:
                indexed_features.append(feature)
                indexed_geometries.append(candidate)
        spatial_tree = STRtree(indexed_geometries) if indexed_geometries else None
    except (ImportError, ValueError, TypeError):
        spatial_tree = None

    grid_size = 0.1
    spatial_grid: dict[tuple[int, int], list[dict[str, Any]]] = {}
    for feature in features:
        geometry = feature.get("geometry")
        bbox = _geometry_bbox(geometry) if isinstance(geometry, dict) else None
        if bbox is None:
            continue
        min_x, min_y, max_x, max_y = bbox
        for cell_x in range(int(min_x // grid_size), int(max_x // grid_size) + 1):
            for cell_y in range(int(min_y // grid_size), int(max_y // grid_size) + 1):
                spatial_grid.setdefault((cell_x, cell_y), []).append(feature)

    current_track_files = {
        path.stem: path
        for path in (sorted(tracks_dir.glob("*.json")) if tracks_dir.exists() else [])
        if not path.stem.endswith(".meta")
    }
    previous_mtimes = previous.get("track_mtimes", {})
    previous_activities = previous.get("activities", {})
    activity_codes: dict[str, list[str]] = {}
    municipality_activities: dict[str, list[str]] = {}
    track_mtimes: dict[str, int] = {}
    for activity, track_file in current_track_files.items():
        mtime = track_file.stat().st_mtime_ns
        track_mtimes[activity] = mtime
        cached = previous_activities.get(activity, {})
        if previous_mtimes.get(activity) == mtime and isinstance(cached, dict):
            cached_codes = sorted(str(code) for code in cached.get("municipality_codes", []))
            if cached_codes:
                activity_codes[activity] = cached_codes
                for code in cached_codes:
                    municipality_activities.setdefault(code, []).append(activity)
            continue

        points = _track_points(track_file)
        if not points:
            continue
        codes: set[str] = set()
        if spatial_tree is not None:
            from shapely import points as shapely_points

            point_array = shapely_points(
                [point[0] for point in points], [point[1] for point in points]
            )
            matches = spatial_tree.query(point_array, predicate="intersects")
            for feature_index in set(int(index) for index in matches[1]):
                feature = indexed_features[feature_index]
                code = str(feature.get("properties", {}).get("code", ""))
                if code:
                    codes.add(code)
                    municipality_activities.setdefault(code, []).append(track_file.stem)
        else:
            for point in points:
                candidates = spatial_grid.get(
                    (int(point[0] // grid_size), int(point[1] // grid_size)), []
                )
                for feature in candidates:
                    properties = feature.get("properties", {})
                    code = str(properties.get("code", ""))
                    geometry = feature.get("geometry")
                    if (
                        code
                        and code not in codes
                        and isinstance(geometry, dict)
                        and point_in_geometry(point, geometry)
                    ):
                        codes.add(code)
                        municipality_activities.setdefault(code, []).append(track_file.stem)
        if codes:
            activity_codes[track_file.stem] = sorted(codes)

    municipalities = []
    for feature in features:
        properties = feature.get("properties", {})
        code = str(properties.get("code", ""))
        if not code:
            continue
        activities = sorted(set(municipality_activities.get(code, [])))
        municipalities.append({
            "code": code,
            "name": properties.get("naam"),
            "province_code": properties.get("ligtInProvincieCode"),
            "province": properties.get("ligtInProvincieNaam"),
            "geometry": _display_geometry(feature.get("geometry")),
            "visited": bool(activities),
            "activity_count": len(activities),
            "activities": activities,
        })
    municipalities.sort(key=lambda item: item["code"])
    visited = [item for item in municipalities if item["visited"]]
    new_codes = {item["code"] for item in visited} - previous_visited
    result = {
        "source": PDOK_WFS_URL,
        "counts": {
            "total": len(municipalities),
            "visited": len(visited),
            "unvisited": len(municipalities) - len(visited),
        },
        "municipalities": municipalities,
        "provinces": _province_display_geometries(features),
        "activities": {
            activity: {"municipality_codes": codes, "count": len(codes)}
            for activity, codes in sorted(activity_codes.items())
        },
        "track_mtimes": track_mtimes,
        "new_gemeentes": [
            {"code": item["code"], "name": item["name"], "province": item["province"]}
            for item in visited
            if item["code"] in new_codes
        ],
    }
    output_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = output_file.with_suffix(output_file.suffix + ".tmp")
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    temporary.replace(output_file)
    return result


def main() -> None:
    """CLI entry point for municipality crossing generation."""
    cache_root = Path.home() / ".cache" / "garmin"
    parser = argparse.ArgumentParser(description="Generate visited Dutch municipalities")
    parser.add_argument("--refresh-boundaries", action="store_true")
    args = parser.parse_args()
    boundary_file = cache_root / "gemeentegebieden.geojson"
    result = generate(
        load_boundaries(boundary_file, refresh=args.refresh_boundaries),
        cache_root / "tracks",
        cache_root / "gemeentes.json",
    )
    print(
        f"Visited {result['counts']['visited']} of {result['counts']['total']} municipalities; "
        f"{len(result['new_gemeentes'])} new"
    )


if __name__ == "__main__":
    main()
