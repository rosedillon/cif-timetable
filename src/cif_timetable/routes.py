"""Typical-weekday route frequencies from the calls table.

A CIF feed describes schedules with validity windows and running-day
bitmaps, not the trains that run on a given day. To count services on a
route you have to pick a date and work out which schedules are active
on it, or seasonal variants of the same train are counted several
times.
"""

from __future__ import annotations

import itertools
import logging
from collections import Counter
from typing import TYPE_CHECKING

import pandas as pd

from cif_timetable.schedules import (
    CALLS_FILENAME,
    PASSENGER_CATEGORY_PREFIXES,
    SERVICE_KEY,
)

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

# Columns needed to count routes; the rest of the table is not read.
ROUTE_COLUMNS = [
    *SERVICE_KEY,
    "stp_indicator",
    "atoc_code",
    "train_category",
    "days_runs",
    "seq",
    "crs",
    "in_scope",
    "is_public_call",
    "public_arrival",
    "public_departure",
    "arrival",
    "departure",
]

# Hours counted as daytime for the mean-trains-per-hour figure.
DEFAULT_DAYTIME_HOURS = (7, 19)

# Weekday to snapshot on when no date is given. 2 is Wednesday, which
# avoids the Monday and Friday variants many operators run.
DEFAULT_REFERENCE_WEEKDAY = 2

PERMANENT = "P"

HOURLY_FILENAME = "route_frequency_hourly.csv"
SUMMARY_FILENAME = "route_frequency_summary.csv"


def departure_hours(calls: pd.DataFrame) -> pd.Series:
    """Best available departure clock-hour for each call.

    Prefers the public departure, falling back through the working
    departure and then the arrivals, so an origin, an intermediate stop
    and a terminus all get an hour where one exists at all.
    """
    best = pd.Series("", index=calls.index)
    for column in ("public_departure", "departure", "public_arrival", "arrival"):
        candidate = calls[column].fillna("").astype(str)
        best = best.where(best.str.len() > 0, candidate)
    return pd.to_numeric(best.str[:2], errors="coerce")


def resolve_reference_date(
    calls: pd.DataFrame,
    reference_date: str | None = None,
    reference_weekday: int = DEFAULT_REFERENCE_WEEKDAY,
) -> pd.Timestamp:
    """Pick the date the frequency snapshot is taken on.

    Uses *reference_date* when given. Otherwise takes the middle of the
    data's own validity span and moves forward to *reference_weekday*,
    which lands on a day most schedules are active.
    """
    if reference_date:
        return pd.Timestamp(reference_date)
    starts = pd.to_datetime(calls["start_date"], errors="coerce")
    ends = pd.to_datetime(calls["end_date"], errors="coerce")
    middle = starts.min() + (ends.max() - starts.min()) / 2
    shift = (reference_weekday - middle.weekday()) % 7
    return (middle + pd.Timedelta(days=shift)).normalize()


def active_on(calls: pd.DataFrame, reference_date: pd.Timestamp) -> pd.DataFrame:
    """Permanent public passenger calls on schedules running that day.

    A schedule qualifies when it is permanent, its date range covers the
    reference date, and its running-days bitmap has a 1 for that
    weekday. Each train is then counted once, from whichever seasonal
    variant runs that day.
    """
    days = calls["days_runs"].fillna("").astype(str)
    category = calls["train_category"].fillna("").astype(str)
    starts = pd.to_datetime(calls["start_date"], errors="coerce")
    ends = pd.to_datetime(calls["end_date"], errors="coerce")
    weekday = reference_date.weekday()

    keep = (
        (calls["stp_indicator"] == PERMANENT)
        & (calls["is_public_call"].astype(str) == "True")
        & category.str[:1].isin(PASSENGER_CATEGORY_PREFIXES)
        & (starts <= reference_date)
        & (ends >= reference_date)
        & (days.str.len() > weekday)
        & (days.str[weekday] == "1")
    )
    return calls[keep].copy()


def count_route_hours(calls: pd.DataFrame) -> Counter[tuple[str, str, int]]:
    """Trains per (origin, destination, departure hour) on one day.

    Every ordered pair of a service's public stops counts as one train,
    timed by the earlier stop's departure hour. A route therefore counts
    every train a passenger could take along it, including those that
    start or end somewhere else.

    Only pairs with at least one in-scope end are counted, so the
    out-of-scope part of a train that also serves the scope does not add
    to the totals.
    """
    ordered = calls.sort_values([*SERVICE_KEY, "seq"])
    columns = [*SERVICE_KEY, "crs", "in_scope", "hour"]
    counts: Counter[tuple[str, str, int]] = Counter()
    key_length = len(SERVICE_KEY)

    for _, rows in itertools.groupby(
        ordered[columns].itertuples(index=False, name=None),
        key=lambda row: row[:key_length],
    ):
        stops = [(row[-3], row[-2], row[-1]) for row in rows]
        for (origin, origin_scope, hour), (
            destination,
            destination_scope,
            _,
        ) in itertools.combinations(stops, 2):
            if (
                origin
                and destination
                and origin != destination
                and pd.notna(hour)
                and (origin_scope or destination_scope)
            ):
                counts[(origin, destination, int(hour))] += 1
    return counts


def summarise(
    hourly: pd.DataFrame, daytime_hours: tuple[int, int] = DEFAULT_DAYTIME_HOURS
) -> pd.DataFrame:
    """Per-route daily trains, peak, daytime mean, first and last."""
    start, end = daytime_hours
    grouped = hourly.groupby(["origin_crs", "destination_crs"])

    rows = []
    for key, group in grouped:
        origin, destination = str(key[0]), str(key[1])
        # Positional argmax rather than .loc[idxmax()]: the label type
        # is opaque after a multi-column groupby.
        peak_row = group.iloc[int(group["trains"].to_numpy().argmax())]
        daytime = group[group["hour"].between(start, end)]
        rows.append(
            {
                "origin_crs": origin,
                "destination_crs": destination,
                "daily_trains": int(group["trains"].sum()),
                "peak_tph": int(peak_row["trains"]),
                "peak_hour": int(peak_row["hour"]),
                "daytime_mean_tph": (
                    float(daytime["trains"].sum()) / (end - start + 1)
                    if not daytime.empty
                    else 0.0
                ),
                "first_hour": int(group["hour"].min()),
                "last_hour": int(group["hour"].max()),
            }
        )

    summary = pd.DataFrame(rows)
    if summary.empty:
        return summary
    return summary.sort_values("daily_trains", ascending=False).reset_index(drop=True)


def analyse_routes(
    output_dir: pathlib.Path,
    *,
    reference_date: str | None = None,
    reference_weekday: int = DEFAULT_REFERENCE_WEEKDAY,
    daytime_hours: tuple[int, int] = DEFAULT_DAYTIME_HOURS,
    exclude_operators: frozenset[str] | set[str] = frozenset(),
) -> pd.DataFrame:
    """Build route frequencies from a cleaned calls table.

    Reads ``timetable_calls.csv`` from *output_dir* and writes
    ``route_frequency_hourly.csv`` and ``route_frequency_summary.csv``
    beside it. Returns the summary.
    """
    calls_path = output_dir / CALLS_FILENAME
    logger.info("Reading calls from %s", calls_path)
    calls = pd.read_csv(calls_path, dtype=str, usecols=ROUTE_COLUMNS)

    excluded_codes = {code.strip().upper() for code in exclude_operators}
    if excluded_codes:
        is_excluded = calls["atoc_code"].fillna("").str.upper().isin(excluded_codes)
        logger.info(
            "Excluding %d call rows for %s", int(is_excluded.sum()), sorted(excluded_codes)
        )
        calls = calls[~is_excluded]

    snapshot = resolve_reference_date(calls, reference_date, reference_weekday)
    logger.info("Frequency snapshot for %s (%s)", snapshot.date(), snapshot.day_name())

    calls = active_on(calls, snapshot)
    calls["seq"] = pd.to_numeric(calls["seq"], errors="coerce")
    calls["hour"] = departure_hours(calls)
    calls["in_scope"] = calls["in_scope"].astype(str).eq("True")
    calls = calls.dropna(subset=["seq", "hour"])
    logger.info("Counting routes over %d qualifying calls", len(calls))

    counts = count_route_hours(calls)
    if not counts:
        logger.warning("No qualifying passenger services found; no routes written")
        return pd.DataFrame()

    hourly = pd.DataFrame(
        [
            (origin, destination, hour, trains)
            for (origin, destination, hour), trains in counts.items()
        ],
        columns=["origin_crs", "destination_crs", "hour", "trains"],
    ).sort_values(["origin_crs", "destination_crs", "hour"])
    hourly.to_csv(output_dir / HOURLY_FILENAME, index=False)

    summary = summarise(hourly, daytime_hours)
    summary.to_csv(output_dir / SUMMARY_FILENAME, index=False)
    logger.info("Wrote %d routes to %s", len(summary), output_dir / SUMMARY_FILENAME)
    return summary
