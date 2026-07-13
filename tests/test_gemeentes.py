"""Tests for Dutch municipality crossing generation."""
import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest


FEATURES = {
    "type": "FeatureCollection",
    "features": [
        {
            "type": "Feature",
            "properties": {
                "identificatie": "GM0001",
                "code": "0001",
                "naam": "Alpha",
                "ligtInProvincieCode": "PV01",
                "ligtInProvincieNaam": "Testland",
            },
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [[[
                    [0, 0], [10, 0], [10, 10], [0, 10], [0, 0]
                ], [
                    [4, 4], [6, 4], [6, 6], [4, 6], [4, 4]
                ]]],
            },
        },
        {
            "type": "Feature",
            "properties": {
                "identificatie": "GM0002",
                "code": "0002",
                "naam": "Beta",
                "ligtInProvincieCode": "PV02",
                "ligtInProvincieNaam": "Elsewhere",
            },
            "geometry": {
                "type": "MultiPolygon",
                "coordinates": [
                    [[[20, 20], [21, 20], [21, 21], [20, 21], [20, 20]]],
                    [[[30, 30], [31, 30], [31, 31], [30, 31], [30, 30]]],
                ],
            },
        },
    ],
}


def test_point_in_multipolygon_handles_holes_components_and_boundaries() -> None:
    from summit.gemeentes import point_in_geometry

    alpha = FEATURES["features"][0]["geometry"]
    beta = FEATURES["features"][1]["geometry"]

    assert point_in_geometry((1, 1), alpha)
    assert not point_in_geometry((5, 5), alpha)  # polygon hole
    assert point_in_geometry((0, 5), alpha)  # boundary counts as crossed
    assert point_in_geometry((30.5, 30.5), beta)  # second component
    assert not point_in_geometry((15, 15), beta)


def test_generate_scans_track_lists_and_preserves_previous_discovery_state(tmp_path: Path) -> None:
    from summit.gemeentes import generate

    tracks = tmp_path / "tracks"
    tracks.mkdir()
    # Track points are [lat, lon, timestamp, elevation, optional power].
    (tracks / "ride-42.json").write_text(json.dumps([
        [1.0, 1.0, 100, 5],       # Alpha (GeoJSON uses lon, lat)
        [5.0, 5.0, 101, 5, 200],  # Alpha's hole: no municipality
        [30.5, 30.5, 102, 5],     # Beta's second polygon
    ]))
    output = tmp_path / "gemeentes.json"

    first = generate(FEATURES, tracks, output)

    assert first["counts"] == {"total": 2, "visited": 2, "unvisited": 0}
    assert first["new_gemeentes"] == [
        {"code": "0001", "name": "Alpha", "province": "Testland"},
        {"code": "0002", "name": "Beta", "province": "Elsewhere"},
    ]
    assert first["activities"] == {
        "ride-42": {"municipality_codes": ["0001", "0002"], "count": 2}
    }
    alpha = first["municipalities"][0]
    assert alpha | {"geometry": None} == {
        "code": "0001",
        "name": "Alpha",
        "province_code": "PV01",
        "province": "Testland",
        "geometry": None,
        "visited": True,
        "activity_count": 1,
        "activities": ["ride-42"],
    }
    assert alpha["geometry"]["type"] in {"Polygon", "MultiPolygon"}
    assert json.loads(output.read_text()) == first

    second = generate(FEATURES, tracks, output)
    assert second["new_gemeentes"] == []


def test_generate_dissolves_shared_municipality_edges_in_province_geometry(tmp_path: Path) -> None:
    from shapely.geometry import LineString, shape
    from summit.gemeentes import generate

    boundaries = {
        "type": "FeatureCollection",
        "features": [
            {
                "properties": {"code": "1", "naam": "West", "ligtInProvincieCode": "P1", "ligtInProvincieNaam": "Noord"},
                "geometry": {"type": "Polygon", "coordinates": [[[0, 0], [1, 0], [1, 1], [0, 1], [0, 0]]]},
            },
            {
                "properties": {"code": "2", "naam": "Oost", "ligtInProvincieCode": "P1", "ligtInProvincieNaam": "Noord"},
                "geometry": {"type": "Polygon", "coordinates": [[[1, 0], [2, 0], [2, 1], [1, 1], [1, 0]]]},
            },
        ],
    }
    tracks = tmp_path / "tracks"
    tracks.mkdir()

    result = generate(boundaries, tracks, tmp_path / "out.json")

    assert [province["name"] for province in result["provinces"]] == ["Noord"]
    province = shape(result["provinces"][0]["geometry"])
    assert province.area == pytest.approx(2.0)
    assert province.boundary.intersection(LineString([(1, 0), (1, 1)])).length == 0


def test_generate_ignores_invalid_cache_files_and_counts_each_activity_once(tmp_path: Path) -> None:
    from summit.gemeentes import generate

    tracks = tmp_path / "tracks"
    tracks.mkdir()
    (tracks / "bad.json").write_text("not json")
    (tracks / "meta.json").write_text(json.dumps({"activityId": 5}))
    (tracks / "repeat.json").write_text(json.dumps([[1, 1, 0, 0], [2, 2, 1, 0]]))

    result = generate(FEATURES, tracks, tmp_path / "out.json")
    alpha = result["municipalities"][0]
    assert alpha["activity_count"] == 1
    assert result["activities"] == {
        "repeat": {"municipality_codes": ["0001"], "count": 1}
    }


def test_generate_uses_spatial_candidates_instead_of_testing_every_polygon(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Historical generation must remain practical with hundreds of boundaries."""
    from summit import gemeentes

    boundaries = {"type": "FeatureCollection", "features": []}
    for index in range(200):
        x = float(index * 2)
        boundaries["features"].append({
            "type": "Feature",
            "properties": {"code": f"{index:04d}", "naam": str(index)},
            "geometry": {
                "type": "Polygon",
                "coordinates": [[[x, 0], [x + 1, 0], [x + 1, 1], [x, 1], [x, 0]]],
            },
        })
    tracks = tmp_path / "tracks"
    tracks.mkdir()
    (tracks / "ride.json").write_text(json.dumps([[0.5, 0.5, 0, 0]] * 100))

    calls = 0
    real = gemeentes.point_in_geometry

    def counted(point: tuple[float, float], geometry: dict) -> bool:
        nonlocal calls
        calls += 1
        return real(point, geometry)

    monkeypatch.setattr(gemeentes, "point_in_geometry", counted)
    result = gemeentes.generate(boundaries, tracks, tmp_path / "out.json")

    assert result["counts"]["visited"] == 1
    assert calls < 10


def test_load_boundaries_downloads_once_then_uses_cache(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from summit import gemeentes

    cache = tmp_path / "boundaries.geojson"
    response = MagicMock()
    response.json.return_value = FEATURES
    response.raise_for_status.return_value = None
    get = MagicMock(return_value=response)
    monkeypatch.setattr(gemeentes.requests, "get", get)

    assert gemeentes.load_boundaries(cache) == FEATURES
    get.assert_called_once_with(gemeentes.PDOK_WFS_URL, timeout=60)
    assert json.loads(cache.read_text()) == FEATURES

    get.reset_mock()
    assert gemeentes.load_boundaries(cache) == FEATURES
    get.assert_not_called()


def test_main_writes_default_garmin_output(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    from summit import gemeentes

    tracks = tmp_path / ".cache" / "garmin" / "tracks"
    tracks.mkdir(parents=True)
    monkeypatch.setattr(gemeentes.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(gemeentes, "load_boundaries", lambda path, **kwargs: FEATURES)
    monkeypatch.setattr("sys.argv", ["summit gemeentes"])

    gemeentes.main()

    assert (tmp_path / ".cache" / "garmin" / "gemeentes.json").exists()


def test_unified_cli_routes_gemeentes(monkeypatch: pytest.MonkeyPatch) -> None:
    from summit.cli import main as cli_main

    called = MagicMock()
    monkeypatch.setattr("summit.gemeentes.main", called)
    monkeypatch.setattr("sys.argv", ["summit", "gemeentes"])
    cli_main.main()
    called.assert_called_once_with()


def test_auto_update_generates_gemeentes_after_track_refresh() -> None:
    from summit.cli.auto_update import _run

    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 1 if "summit.updates" in " ".join(cmd) else 0
        return result

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr("summit.cli.auto_update.subprocess.run", fake_run)
        _run(__import__("io").StringIO())

    commands = [" ".join(command) for command in calls]
    prs_index = next(i for i, command in enumerate(commands) if "summit.prs" in command)
    gemeente_index = next(i for i, command in enumerate(commands) if "summit.gemeentes" in command)
    assert gemeente_index > prs_index


def test_auto_update_recovers_stale_gemeentes_output(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from summit.cli import auto_update

    tracks = tmp_path / ".cache" / "garmin" / "tracks"
    tracks.mkdir(parents=True)
    track = tracks / "42.json"
    track.write_text("[]")
    track.touch()
    calls: list[list[str]] = []

    def fake_run(cmd: list[str], **kwargs: object) -> MagicMock:
        calls.append(cmd)
        result = MagicMock()
        result.returncode = 0
        return result

    monkeypatch.setattr(auto_update.Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setattr(auto_update.subprocess, "run", fake_run)
    auto_update._run(__import__("io").StringIO())

    assert any("summit.gemeentes" in " ".join(command) for command in calls)
