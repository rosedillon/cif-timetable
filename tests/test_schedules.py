from __future__ import annotations

import csv
from typing import TYPE_CHECKING

from cif_timetable import (
    CALLS_COLUMNS,
    CALLS_FILENAME,
    clean_timetable,
    iter_schedules,
    load_tiploc_crs_map,
    tiplocs_for,
)

if TYPE_CHECKING:
    import pathlib


def _rows(directory: pathlib.Path) -> list[dict[str, str]]:
    with (directory / CALLS_FILENAME).open() as handle:
        return list(csv.DictReader(handle))


class TestIterSchedules:
    def test_only_schedules_are_yielded(self, cif_feed: pathlib.Path) -> None:
        records = list(iter_schedules(cif_feed))
        assert len(records) == 8
        assert all("CIF_train_uid" in record for record in records)

    def test_other_record_types_are_skipped(self, cif_feed: pathlib.Path) -> None:
        # The header, the TIPLOCs and the association must not appear.
        uids = {record["CIF_train_uid"] for record in iter_schedules(cif_feed)}
        assert uids == {f"C0000{n}" for n in range(1, 9)}


class TestCleanTimetable:
    def test_writes_the_declared_columns(self, cleaned: pathlib.Path) -> None:
        with (cleaned / CALLS_FILENAME).open() as handle:
            assert next(csv.reader(handle)) == CALLS_COLUMNS

    def test_counts_are_returned(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        counts = clean_timetable(cif_feed, tmp_path / "out", tiploc_to_crs=mapping)
        assert counts["schedules"] == 8
        assert counts["kept"] > 0
        assert counts["call_rows"] == counts["call_rows"]

    def test_service_fields_on_every_call(self, cleaned: pathlib.Path) -> None:
        rows = [row for row in _rows(cleaned) if row["train_uid"] == "C00001"]
        assert len(rows) == 4
        assert {row["atoc_code"] for row in rows} == {"NT"}
        assert {row["svc_origin_crs"] for row in rows} == {"AAA"}
        assert {row["svc_dest_crs"] for row in rows} == {"DDD"}

    def test_calling_order_is_preserved(self, cleaned: pathlib.Path) -> None:
        rows = [row for row in _rows(cleaned) if row["train_uid"] == "C00001"]
        assert [row["crs"] for row in rows] == ["AAA", "BBB", "CCC", "DDD"]
        assert [int(row["seq"]) for row in rows] == [0, 1, 2, 3]

    def test_recovered_crs_reaches_the_calls(self, cleaned: pathlib.Path) -> None:
        # CCCC has no published CRS; without recovery every call there
        # is lost.
        codes = {row["crs"] for row in _rows(cleaned)}
        assert "CCC" in codes

    def test_public_calls_are_flagged(self, cleaned: pathlib.Path) -> None:
        rows = [row for row in _rows(cleaned) if row["train_uid"] == "C00001"]
        assert all(row["is_public_call"] == "True" for row in rows)

    def test_pass_only_service(self, cleaned: pathlib.Path) -> None:
        rows = [row for row in _rows(cleaned) if row["train_uid"] == "C00008"]
        assert all(row["is_public_call"] == "False" for row in rows)

    def test_operators_can_be_excluded(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        output = tmp_path / "no-me"
        counts = clean_timetable(cif_feed, output, tiploc_to_crs=mapping, exclude_operators={"ME"})
        assert counts["excluded"] == 1
        assert "ME" not in {row["atoc_code"] for row in _rows(output)}


class TestScope:
    def test_scope_filters_services(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        scope = tiplocs_for(mapping, {"BBB"})
        output = tmp_path / "scoped"
        clean_timetable(cif_feed, output, tiploc_to_crs=mapping, scope_tiplocs=scope)
        rows = _rows(output)
        assert rows
        assert all(row["n_scope_stops"] == "1" for row in rows)

    def test_whole_calling_pattern_kept(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        # Scoping to BBB alone must still record the train's other
        # public calls, or a journey from BBB to DDD becomes
        # unreachable.
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        scope = tiplocs_for(mapping, {"BBB"})
        output = tmp_path / "scoped"
        clean_timetable(cif_feed, output, tiploc_to_crs=mapping, scope_tiplocs=scope)
        rows = [row for row in _rows(output) if row["train_uid"] == "C00001"]
        assert {row["crs"] for row in rows} == {"AAA", "BBB", "CCC", "DDD"}

    def test_in_scope_flag(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        scope = tiplocs_for(mapping, {"BBB"})
        output = tmp_path / "scoped"
        clean_timetable(cif_feed, output, tiploc_to_crs=mapping, scope_tiplocs=scope)
        rows = [row for row in _rows(output) if row["train_uid"] == "C00001"]
        in_scope = {row["crs"] for row in rows if row["in_scope"] == "True"}
        assert in_scope == {"BBB"}

    def test_out_of_scope_service_dropped(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path, tmp_path: pathlib.Path
    ) -> None:
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        output = tmp_path / "nowhere"
        counts = clean_timetable(cif_feed, output, tiploc_to_crs=mapping, scope_tiplocs={"NOSUCH"})
        assert counts["kept"] == 0
        assert counts["call_rows"] == 0

    def test_no_scope_means_the_whole_network(self, cleaned: pathlib.Path) -> None:
        rows = [row for row in _rows(cleaned) if row["train_uid"] == "C00001"]
        assert all(row["in_scope"] == "True" for row in rows)
