from __future__ import annotations

from typing import TYPE_CHECKING

import pandas as pd
import pytest

from cif_timetable import analyse_routes, read_public_calls, resolve_reference_date
from cif_timetable.routes import HOURLY_FILENAME, SUMMARY_FILENAME
from cif_timetable.schedules import CALLS_FILENAME

from .conftest import REFERENCE_DATE, SUNDAY_DATE

if TYPE_CHECKING:
    import pathlib


@pytest.fixture
def summary(cleaned: pathlib.Path) -> pd.DataFrame:
    return analyse_routes(cleaned, reference_date=REFERENCE_DATE)


class TestReferenceDate:
    def test_explicit_date(self, cleaned: pathlib.Path) -> None:
        calls = pd.read_csv(cleaned / CALLS_FILENAME, dtype=str)
        assert resolve_reference_date(calls, "2026-05-06") == pd.Timestamp("2026-05-06")

    def test_derived_date_weekday(self, cleaned: pathlib.Path) -> None:
        calls = pd.read_csv(cleaned / CALLS_FILENAME, dtype=str)
        for weekday in range(7):
            assert resolve_reference_date(calls, None, weekday).weekday() == weekday

    def test_derived_date_inside_span(self, cleaned: pathlib.Path) -> None:
        calls = pd.read_csv(cleaned / CALLS_FILENAME, dtype=str)
        date = resolve_reference_date(calls, None, 2)
        assert pd.Timestamp("2026-01-05") <= date <= pd.Timestamp("2026-12-12")


class TestRouteCounting:
    def test_ordered_pairs(self, summary: pd.DataFrame) -> None:
        # A 4-stop train serves 6 ordered pairs, not just end to end.
        pairs = set(zip(summary["origin_crs"], summary["destination_crs"], strict=True))
        assert ("AAA", "BBB") in pairs
        assert ("BBB", "DDD") in pairs
        assert ("AAA", "DDD") in pairs
        assert len(pairs) == 6

    def test_daily_trains(self, summary: pd.DataFrame) -> None:
        # Four weekday corridor trains qualify: 07:00, 08:00, 08:00 and
        # the 12:00 Merseyrail one. The Sunday-only, overlay, bus and
        # pass-only services do not.
        route = summary[(summary["origin_crs"] == "AAA") & (summary["destination_crs"] == "DDD")]
        assert int(route["daily_trains"].iloc[0]) == 4

    def test_peak_hour(self, summary: pd.DataFrame) -> None:
        route = summary[(summary["origin_crs"] == "AAA") & (summary["destination_crs"] == "DDD")]
        assert int(route["peak_hour"].iloc[0]) == 8
        assert int(route["peak_tph"].iloc[0]) == 2

    def test_first_and_last_hours(self, summary: pd.DataFrame) -> None:
        route = summary[(summary["origin_crs"] == "AAA") & (summary["destination_crs"] == "DDD")]
        assert int(route["first_hour"].iloc[0]) == 7
        assert int(route["last_hour"].iloc[0]) == 12

    def test_routes_are_directional(self, summary: pd.DataFrame) -> None:
        pairs = set(zip(summary["origin_crs"], summary["destination_crs"], strict=True))
        assert ("AAA", "DDD") in pairs
        assert ("DDD", "AAA") not in pairs


class TestExclusions:
    def test_running_days(self, cleaned: pathlib.Path, summary: pd.DataFrame) -> None:
        # The 09:00 train runs Sundays only. A Wednesday snapshot must
        # not see it; a Sunday snapshot must see it and nothing else.
        def daily(frame: pd.DataFrame) -> int:
            route = frame[(frame["origin_crs"] == "AAA") & (frame["destination_crs"] == "DDD")]
            return int(route["daily_trains"].iloc[0])

        sunday = analyse_routes(cleaned, reference_date=SUNDAY_DATE)
        assert daily(summary) == 4
        assert daily(sunday) == 1

    def test_short_term_overlays_are_excluded(self, summary: pd.DataFrame) -> None:
        # The 10:00 train is an STP overlay, not permanent; counting it
        # would double-count the service it overlays.
        hours = set(
            summary[(summary["origin_crs"] == "AAA") & (summary["destination_crs"] == "DDD")][
                ["first_hour", "last_hour"]
            ].iloc[0]
        )
        assert 10 not in hours

    def test_non_passenger_excluded(self, summary: pd.DataFrame) -> None:
        # The 11:00 service is a bus (category BS).
        route = summary[(summary["origin_crs"] == "AAA") & (summary["destination_crs"] == "DDD")]
        assert int(route["last_hour"].iloc[0]) != 11

    def test_pass_only_services(self, summary: pd.DataFrame) -> None:
        route = summary[(summary["origin_crs"] == "AAA") & (summary["destination_crs"] == "DDD")]
        assert int(route["first_hour"].iloc[0]) != 5

    def test_operators_can_be_excluded(self, cleaned: pathlib.Path) -> None:
        with_me = analyse_routes(cleaned, reference_date=REFERENCE_DATE)
        without_me = analyse_routes(
            cleaned, reference_date=REFERENCE_DATE, exclude_operators={"ME"}
        )
        route = lambda frame: int(  # noqa: E731
            frame[(frame["origin_crs"] == "AAA") & (frame["destination_crs"] == "DDD")][
                "daily_trains"
            ].iloc[0]
        )
        assert route(without_me) == route(with_me) - 1


class TestOutputs:
    def test_both_files_are_written(self, cleaned: pathlib.Path, summary: pd.DataFrame) -> None:
        assert (cleaned / HOURLY_FILENAME).exists()
        assert (cleaned / SUMMARY_FILENAME).exists()

    def test_summary_is_ordered_by_daily_trains(self, summary: pd.DataFrame) -> None:
        assert list(summary["daily_trains"]) == sorted(summary["daily_trains"], reverse=True)

    def test_date_with_no_services(self, cleaned: pathlib.Path) -> None:
        # Well outside every schedule's validity window.
        assert analyse_routes(cleaned, reference_date="2099-01-01").empty


class TestReadPublicCalls:
    def test_filters_calls(self, cleaned: pathlib.Path) -> None:
        calls = read_public_calls(cleaned / CALLS_FILENAME)
        assert set(calls["stp_indicator"]) == {"P"}
        assert set(calls["is_public_call"]) == {"True"}
        assert all(category[:1] in ("O", "X") for category in calls["train_category"])

    def test_drops_calls_with_no_crs(self, cleaned: pathlib.Path) -> None:
        calls = read_public_calls(cleaned / CALLS_FILENAME)
        assert calls["crs"].notna().all()
        assert (calls["crs"] != "").all()

    def test_chunking_gives_the_same_result(self, cleaned: pathlib.Path) -> None:
        whole = read_public_calls(cleaned / CALLS_FILENAME)
        chunked = read_public_calls(cleaned / CALLS_FILENAME, chunk_size=2)
        assert len(whole) == len(chunked)
