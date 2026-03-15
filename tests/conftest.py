"""Shared fixtures for summit test suite."""
import textwrap
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

# ---------------------------------------------------------------------------
# Sample GPX data
# ---------------------------------------------------------------------------

SAMPLE_GPX_TRACK = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
      <trk>
        <name>Test Ride</name>
        <trkseg>
          <trkpt lat="51.5000" lon="0.0000">
            <ele>10.0</ele>
            <time>2024-06-01T09:00:00Z</time>
            <extensions><power>200</power></extensions>
          </trkpt>
          <trkpt lat="51.5010" lon="0.0010">
            <ele>15.0</ele>
            <time>2024-06-01T09:01:00Z</time>
            <extensions><power>220</power></extensions>
          </trkpt>
          <trkpt lat="51.5020" lon="0.0020">
            <ele>12.0</ele>
            <time>2024-06-01T09:02:00Z</time>
            <extensions><power>210</power></extensions>
          </trkpt>
          <trkpt lat="51.5030" lon="0.0030">
            <ele>8.0</ele>
            <time>2024-06-01T09:03:00Z</time>
            <extensions><power>230</power></extensions>
          </trkpt>
          <trkpt lat="51.5040" lon="0.0040">
            <ele>5.0</ele>
            <time>2024-06-01T09:04:00Z</time>
            <extensions><power>215</power></extensions>
          </trkpt>
        </trkseg>
      </trk>
    </gpx>
""")

SAMPLE_GPX_ROUTE = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
      <name>SEG-Test Route</name>
      <rte>
        <rtept lat="51.5000" lon="0.0000">
          <ele>10.0</ele>
        </rtept>
        <rtept lat="51.5010" lon="0.0010">
          <ele>15.0</ele>
        </rtept>
        <rtept lat="51.5020" lon="0.0020">
          <ele>12.0</ele>
        </rtept>
      </rte>
    </gpx>
""")

MALFORMED_GPX = "this is not valid xml <<<"

SAMPLE_GPX_NO_TIMESTAMPS = textwrap.dedent("""\
    <?xml version="1.0" encoding="UTF-8"?>
    <gpx version="1.1" xmlns="http://www.topografix.com/GPX/1/1">
      <trk>
        <trkseg>
          <trkpt lat="51.5000" lon="0.0000"><ele>10.0</ele></trkpt>
          <trkpt lat="51.5010" lon="0.0010"><ele>15.0</ele></trkpt>
          <trkpt lat="51.5020" lon="0.0020"><ele>12.0</ele></trkpt>
        </trkseg>
      </trk>
    </gpx>
""")


# ---------------------------------------------------------------------------
# Sample activity data
# ---------------------------------------------------------------------------

def make_activity(
    activity_id: int = 12345678,
    name: str = "Morning Ride",
    type_key: str = "cycling",
    start_time: str = "2024-06-01 09:00:00",
    duration: float = 3600.0,
    distance: float = 40000.0,
) -> dict[str, Any]:
    return {
        "activityId": activity_id,
        "activityName": name,
        "activityType": {"typeKey": type_key},
        "startTimeLocal": start_time,
        "startTimeGMT": start_time,
        "duration": duration,
        "distance": distance,
    }


SAMPLE_ACTIVITIES = [
    make_activity(12345678, "Morning Ride", "cycling",
                  "2024-06-15 09:00:00", 3600.0, 40000.0),
    make_activity(12345679, "Evening Run", "running",
                  "2024-06-16 18:00:00", 1800.0, 10000.0),
    make_activity(12345680, "Trail Ride", "mountain_biking",
                  "2024-06-17 10:00:00", 5400.0, 30000.0),
]


# ---------------------------------------------------------------------------
# Sample KOM JSON
# ---------------------------------------------------------------------------

SAMPLE_KOM_DATA = {
    "SEG-Test Hill": {
        "best": "5:30",
        "best_seconds": 330.0,
        "activity": {
            "id": 12345678,
            "name": "Morning Ride",
            "startTimeLocal": "2024-06-01 09:00:00",
            "duration_s": 330.0,
            "avg_speed_kmh": 25.5,
            "avg_power_w": 215.0,
        },
        "matches": 3,
        "top": [
            {
                "id": 12345678,
                "name": "Morning Ride",
                "startTimeLocal": "2024-06-01 09:00:00",
                "duration_s": 330.0,
                "avg_speed_kmh": 25.5,
                "avg_power_w": 215.0,
            },
            {
                "id": 12345680,
                "name": "Another Ride",
                "startTimeLocal": "2024-06-10 08:30:00",
                "duration_s": 345.0,
                "avg_speed_kmh": 24.3,
                "avg_power_w": None,
            },
        ],
        "distance_m": 2350.0,
        "ascent_m": 50.0,
        "descent_m": 20.0,
    },
    "SEG-Flat Sprint": {
        "best": None,
        "matches": 0,
        "top": [],
        "distance_m": 1000.0,
        "ascent_m": 5.0,
        "descent_m": 5.0,
    },
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def tmp_cache_dir(tmp_path: Path) -> Path:
    """A temporary cache directory with tracks/ subdirectory."""
    tracks = tmp_path / "tracks"
    tracks.mkdir()
    return tmp_path


@pytest.fixture
def tmp_segments_dir(tmp_path: Path) -> Path:
    """A temporary directory containing segment GPX files."""
    seg_dir = tmp_path / "segments"
    seg_dir.mkdir()
    # Write a sample segment GPX
    (seg_dir / "SEG-Test Hill.gpx").write_text(SAMPLE_GPX_TRACK)
    return seg_dir


@pytest.fixture
def sample_gpx_track():
    return SAMPLE_GPX_TRACK


@pytest.fixture
def sample_gpx_route():
    return SAMPLE_GPX_ROUTE


@pytest.fixture
def sample_activities():
    return list(SAMPLE_ACTIVITIES)


@pytest.fixture
def sample_kom_data():
    import copy
    return copy.deepcopy(SAMPLE_KOM_DATA)


@pytest.fixture
def mock_garmin_client(sample_activities: list[Any]) -> MagicMock:
    """Mock garminconnect.Garmin client."""
    client = MagicMock()
    client.get_activities.return_value = sample_activities
    client.get_activities_by_date.return_value = sample_activities
    client.download_activity.return_value = SAMPLE_GPX_TRACK.encode("utf-8")
    client.get_weekly_intensity_minutes.return_value = []
    return client


@pytest.fixture
def mock_rbw(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Patch subprocess.check_output so rbw_get returns test credentials."""
    def fake_check_output(cmd: Any, **kwargs: Any) -> str:
        if "--field" in cmd and "username" in cmd:
            return "test@example.com\n"
        return "testpassword\n"

    monkeypatch.setattr("subprocess.check_output", fake_check_output)
    return fake_check_output
