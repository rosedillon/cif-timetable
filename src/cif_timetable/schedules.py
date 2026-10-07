"""Stream a CIF schedule feed into a flat table of calling points.

The source is Network Rail's SCHEDULE feed in newline-delimited JSON,
one record per line. Records are ``TiplocV1`` (location reference),
``JsonScheduleV1`` (a train schedule with its calling pattern),
``JsonAssociationV1`` (join and split links) or a single
``JsonTimetableV1`` header.

A full daily extract is several gigabytes, so the file is streamed, and
a substring test skips the JSON parse for the record types that are not
wanted, which is most lines.

Scope
-----
Passing a station list keeps only schedules that touch one of those
stations. A kept schedule keeps its whole calling pattern: every
in-scope stop plus every public stop anywhere. A Leeds to London
train's London terminus is recorded even if London is out of scope, so
the journey can still be looked up. Only out-of-scope operational passes
are dropped, since a place a train runs through without stopping is no
use for a station to station lookup.

Each row carries an ``in_scope`` flag saying whether that particular
stop is one of the selected stations.
"""

from __future__ import annotations

import csv
import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    import pathlib
    from collections.abc import Iterator

logger = logging.getLogger(__name__)

# Train categories beginning with these are passenger services.
# O is ordinary passenger and X express. B (bus), S (ship) and E
# (empty stock) are left out.
PASSENGER_CATEGORY_PREFIXES = ("O", "X")

# Columns identifying one schedule within the calls table.
SERVICE_KEY = ["train_uid", "start_date", "end_date", "svc_origin_dep", "signalling_id"]

# Service-level columns, denormalised onto every call row so the table
# is flat.
SERVICE_FIELDS = [
    "train_uid",
    "stp_indicator",
    "atoc_code",
    "days_runs",
    "start_date",
    "end_date",
    "train_category",
    "power_type",
    "timing_load",
    "speed",
    "signalling_id",
    "svc_origin_crs",
    "svc_origin_tiploc",
    "svc_origin_dep",
    "svc_dest_crs",
    "svc_dest_tiploc",
    "svc_dest_arr",
    "n_scope_stops",
]

CALL_FIELDS = [
    "seq",
    "tiploc",
    "crs",
    "location_type",
    "arrival",
    "departure",
    "pass",
    "public_arrival",
    "public_departure",
    "is_public_call",
    "in_scope",
]

CALLS_COLUMNS = SERVICE_FIELDS + CALL_FIELDS

CALLS_FILENAME = "timetable_calls.csv"

_PROGRESS_EVERY = 250_000


def iter_schedules(cif_path: pathlib.Path) -> Iterator[dict[str, Any]]:
    """Yield each ``JsonScheduleV1`` record, skipping other lines."""
    with cif_path.open() as handle:
        for line in handle:
            if '"JsonScheduleV1"' not in line:
                continue
            record: dict[str, Any] = json.loads(line)["JsonScheduleV1"]
            yield record


def service_summary(
    record: dict[str, Any], tiploc_to_crs: dict[str, str], scope_stops: int
) -> dict[str, Any]:
    """Service-level fields, with the whole service's origin and end."""
    segment = record.get("schedule_segment") or {}
    locations = segment.get("schedule_location") or []
    origin = locations[0] if locations else {}
    destination = locations[-1] if locations else {}
    origin_tiploc = (origin.get("tiploc_code") or "").strip().upper()
    destination_tiploc = (destination.get("tiploc_code") or "").strip().upper()
    return {
        "train_uid": record.get("CIF_train_uid"),
        "stp_indicator": record.get("CIF_stp_indicator"),
        "atoc_code": record.get("atoc_code"),
        "days_runs": record.get("schedule_days_runs"),
        "start_date": record.get("schedule_start_date"),
        "end_date": record.get("schedule_end_date"),
        "train_category": segment.get("CIF_train_category"),
        "power_type": segment.get("CIF_power_type"),
        "timing_load": segment.get("CIF_timing_load"),
        "speed": segment.get("CIF_speed"),
        "signalling_id": segment.get("signalling_id"),
        "svc_origin_crs": tiploc_to_crs.get(origin_tiploc, ""),
        "svc_origin_tiploc": origin_tiploc,
        "svc_origin_dep": origin.get("public_departure") or origin.get("departure"),
        "svc_dest_crs": tiploc_to_crs.get(destination_tiploc, ""),
        "svc_dest_tiploc": destination_tiploc,
        "svc_dest_arr": destination.get("public_arrival") or destination.get("arrival"),
        "n_scope_stops": scope_stops,
    }


def call_rows(
    record: dict[str, Any],
    tiploc_to_crs: dict[str, str],
    scope_tiplocs: set[str] | None,
) -> list[dict[str, Any]] | None:
    """Call rows for a schedule that touches the scope, else ``None``.

    With *scope_tiplocs* ``None``, every location with a CRS is in
    scope.
    """
    segment = record.get("schedule_segment") or {}
    locations = segment.get("schedule_location") or []
    indexed = [
        (index, location, (location.get("tiploc_code") or "").strip().upper())
        for index, location in enumerate(locations)
    ]

    if scope_tiplocs is None:
        scope_tiplocs = {tiploc for _, _, tiploc in indexed if tiploc_to_crs.get(tiploc)}

    scope_stops = sum(1 for _, _, tiploc in indexed if tiploc in scope_tiplocs)
    if not scope_stops:
        return None

    summary = service_summary(record, tiploc_to_crs, scope_stops)
    rows = []
    for sequence, location, tiploc in indexed:
        public_arrival = location.get("public_arrival")
        public_departure = location.get("public_departure")
        # A public call picks up or sets down passengers. Anything else
        # is a pass or an operational stop.
        is_public = bool(public_arrival or public_departure)
        in_scope = tiploc in scope_tiplocs
        if not (in_scope or is_public):
            continue
        rows.append(
            {
                **summary,
                "seq": sequence,
                "tiploc": tiploc,
                "crs": tiploc_to_crs.get(tiploc, ""),
                "location_type": location.get("location_type"),
                "arrival": location.get("arrival"),
                "departure": location.get("departure"),
                "pass": location.get("pass"),
                "public_arrival": public_arrival,
                "public_departure": public_departure,
                "is_public_call": is_public,
                "in_scope": in_scope,
            }
        )
    return rows


def clean_timetable(
    cif_path: pathlib.Path,
    output_dir: pathlib.Path,
    *,
    tiploc_to_crs: dict[str, str],
    scope_tiplocs: set[str] | None = None,
    exclude_operators: frozenset[str] | set[str] = frozenset(),
) -> dict[str, int]:
    """Stream the feed and write one row per kept calling point.

    Parameters
    ----------
    cif_path
        The newline-delimited JSON schedule feed.
    output_dir
        Where ``timetable_calls.csv`` is written.
    tiploc_to_crs
        From :func:`~cif_timetable.tiplocs.load_tiploc_crs_map`.
    scope_tiplocs
        Keep only schedules touching these TIPLOCs. ``None`` keeps
        everything.
    exclude_operators
        ATOC codes to drop entirely, e.g. ``{"ME"}`` for Merseyrail.

    Returns
    -------
    dict
        Row counts under ``"schedules"``, ``"kept"``, ``"call_rows"``
        and ``"excluded"``.
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    excluded_codes = {code.strip().upper() for code in exclude_operators}

    counts = {"schedules": 0, "kept": 0, "call_rows": 0, "excluded": 0}
    path = output_dir / CALLS_FILENAME
    logger.info("Streaming schedules from %s", cif_path)

    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=CALLS_COLUMNS)
        writer.writeheader()
        for record in iter_schedules(cif_path):
            counts["schedules"] += 1
            if counts["schedules"] % _PROGRESS_EVERY == 0:
                logger.info("Read %d schedules", counts["schedules"])

            if excluded_codes:
                operator = (record.get("atoc_code") or "").strip().upper()
                if operator in excluded_codes:
                    counts["excluded"] += 1
                    continue

            rows = call_rows(record, tiploc_to_crs, scope_tiplocs)
            if not rows:
                continue
            counts["kept"] += 1
            counts["call_rows"] += len(rows)
            writer.writerows(rows)

    logger.info(
        "Wrote %d call rows from %d of %d schedules to %s",
        counts["call_rows"],
        counts["kept"],
        counts["schedules"],
        path,
    )
    return counts
