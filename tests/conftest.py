"""A synthetic CIF schedule feed.

The real feed is several gigabytes and licensed through Network Rail, so
these build a small one with the same record shapes. Real lines look
like::

    {"TiplocV1":{"tiploc_code":"ABCWM","crs_code":null,...}}
    {"JsonScheduleV1":{"CIF_train_uid":"C12345",...}}

The toy network is a single corridor::

    AAAA(AAA) --- BBBB(BBB) --- CCCC(CCC) --- DDDD(DDD)

with one TIPLOC published without a CRS, so recovery by description
is exercised. A TIPLOC like that is how London Waterloo went missing
from a national run.
"""

from __future__ import annotations

import json
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    import pathlib

# A Wednesday, inside every fixture schedule's validity window.
REFERENCE_DATE = "2026-03-11"
# The Sunday of the same week.
SUNDAY_DATE = "2026-03-15"
SCHEDULE_START = "2026-01-05"
SCHEDULE_END = "2026-12-12"

WEEKDAYS_ONLY = "1111100"
EVERY_DAY = "1111111"
SUNDAY_ONLY = "0000001"


def tiploc(
    code: str,
    crs: str | None,
    description: str,
    stanox: str = "12345",
) -> str:
    return json.dumps(
        {
            "TiplocV1": {
                "transaction_type": "Create",
                "tiploc_code": code,
                "nalco": "000000",
                "stanox": stanox,
                "crs_code": crs,
                "description": description[:16],
                "tps_description": description,
            }
        }
    )


def location(
    code: str,
    *,
    public_arrival: str | None = None,
    public_departure: str | None = None,
    arrival: str | None = None,
    departure: str | None = None,
    passing: str | None = None,
) -> dict[str, Any]:
    location_type = "LO" if public_departure and not public_arrival else "LI"
    if public_arrival and not public_departure:
        location_type = "LT"
    return {
        "location_type": location_type,
        "tiploc_code": code,
        "arrival": arrival,
        "departure": departure,
        "pass": passing,
        "public_arrival": public_arrival,
        "public_departure": public_departure,
    }


def schedule(
    train_uid: str,
    locations: list[dict[str, Any]],
    *,
    atoc_code: str = "NT",
    category: str = "OO",
    days_runs: str = WEEKDAYS_ONLY,
    stp_indicator: str = "P",
    signalling_id: str = "1A01",
    start_date: str = SCHEDULE_START,
    end_date: str = SCHEDULE_END,
) -> str:
    return json.dumps(
        {
            "JsonScheduleV1": {
                "CIF_train_uid": train_uid,
                "CIF_stp_indicator": stp_indicator,
                "atoc_code": atoc_code,
                "schedule_days_runs": days_runs,
                "schedule_start_date": start_date,
                "schedule_end_date": end_date,
                "transaction_type": "Create",
                "schedule_segment": {
                    "CIF_train_category": category,
                    "CIF_power_type": "DMU",
                    "CIF_timing_load": "150",
                    "CIF_speed": "075",
                    "signalling_id": signalling_id,
                    "schedule_location": locations,
                },
            }
        }
    )


def corridor(train_uid: str, signalling_id: str, hour: int, **kwargs: Any) -> str:
    """A train from AAAA to DDDD, calling at all, leaving at *hour*."""
    return schedule(
        train_uid,
        [
            location("AAAA", public_departure=f"{hour:02d}00", departure=f"{hour:02d}00"),
            location(
                "BBBB",
                public_arrival=f"{hour:02d}10",
                public_departure=f"{hour:02d}11",
                arrival=f"{hour:02d}10",
                departure=f"{hour:02d}11",
            ),
            location(
                "CCCC",
                public_arrival=f"{hour:02d}20",
                public_departure=f"{hour:02d}21",
                arrival=f"{hour:02d}20",
                departure=f"{hour:02d}21",
            ),
            location("DDDD", public_arrival=f"{hour:02d}30", arrival=f"{hour:02d}30"),
        ],
        signalling_id=signalling_id,
        **kwargs,
    )


@pytest.fixture
def cif_feed(tmp_path: pathlib.Path) -> pathlib.Path:
    """A synthetic newline-delimited JSON schedule feed."""
    lines = [
        json.dumps({"JsonTimetableV1": {"classification": "public", "owner": "Network Rail"}}),
        tiploc("AAAA", "AAA", "AYTOWN"),
        tiploc("BBBB", "BBB", "BEEFORD"),
        # Published with no CRS: only recoverable from the description.
        # This is the London Waterloo case.
        tiploc("CCCC", None, "CEEVILLE"),
        tiploc("DDDD", "DDD", "DEETOWN"),
        # A depot, which must never match a station name.
        tiploc("DEPOTXX", None, "CEEVILLE DEPOT"),
        # Not a schedule; must be skipped.
        json.dumps({"JsonAssociationV1": {"main_train_uid": "C00001"}}),
        # Three weekday corridor trains at 07:00, 08:00, 08:00.
        corridor("C00001", "1A01", 7),
        corridor("C00002", "1A02", 8),
        corridor("C00003", "1A03", 8),
        # A Sunday-only train: excluded from a Wednesday snapshot.
        corridor("C00004", "1A04", 9, days_runs=SUNDAY_ONLY),
        # A short-term-plan overlay: excluded, only permanent counts.
        corridor("C00005", "1A05", 10, stp_indicator="O"),
        # A bus replacement: not a passenger train category.
        corridor("C00006", "1A06", 11, category="BS"),
        # A different operator, for the exclusion test.
        corridor("C00007", "1A07", 12, atoc_code="ME"),
        # A train that only passes through, never calling publicly.
        schedule(
            "C00008",
            [
                location("AAAA", passing="0500"),
                location("DDDD", passing="0530"),
            ],
            signalling_id="1A08",
        ),
    ]
    path = tmp_path / "CIF_TEST.json"
    path.write_text("\n".join(lines) + "\n")
    return path


@pytest.fixture
def station_reference(tmp_path: pathlib.Path) -> pathlib.Path:
    """A station list with names, for CRS recovery."""
    path = tmp_path / "stations.csv"
    path.write_text("stationName,crsCode\nAytown,AAA\nBeeford,BBB\nCeeville,CCC\nDeetown,DDD\n")
    return path


@pytest.fixture
def cleaned(cif_feed: pathlib.Path, station_reference: pathlib.Path, tmp_path: pathlib.Path):
    """A cleaned calls table built from the synthetic feed."""
    from cif_timetable import clean_timetable, load_tiploc_crs_map

    output = tmp_path / "timetable"
    mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
    clean_timetable(cif_feed, output, tiploc_to_crs=mapping)
    return output
