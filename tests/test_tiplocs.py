from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from cif_timetable import (
    crs_from_description,
    load_station_codes,
    load_station_names,
    load_tiploc_crs_map,
    normalise_station_name,
    tiplocs_for,
)

if TYPE_CHECKING:
    import pathlib


class TestNormaliseStationName:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Ashton-under-Lyne", "ASHTON UNDER LYNE"),
            ("Bath & Wells", "BATH AND WELLS"),
            ("  London   Waterloo  ", "LONDON WATERLOO"),
            ("St. Albans City", "ST ALBANS CITY"),
        ],
    )
    def test_normalisation(self, raw: str, expected: str) -> None:
        assert normalise_station_name(raw) == expected


class TestLoadStationNames:
    def test_names_map_to_codes(self, station_reference: pathlib.Path) -> None:
        names = load_station_names(station_reference)
        assert names["AYTOWN"] == "AAA"

    def test_ambiguous_name_dropped(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "ambiguous.csv"
        path.write_text("stationName,crsCode\nTwintown,AAA\nTwintown,BBB\nSolo,CCC\n")
        names = load_station_names(path)
        assert "TWINTOWN" not in names
        assert names["SOLO"] == "CCC"

    def test_missing_columns(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "wrong.csv"
        path.write_text("a,b\n1,2\n")
        assert load_station_names(path) == {}


class TestCrsFromDescription:
    @pytest.fixture
    def names(self) -> dict[str, str]:
        return {"LONDON WATERLOO": "WAT", "STOURBRIDGE JUNCTION": "SBJ"}

    def test_exact_match(self, names: dict[str, str]) -> None:
        assert crs_from_description("LONDON WATERLOO", names) == "WAT"

    @pytest.mark.parametrize(
        "description",
        [
            "LONDON WATERLOO (MAIN)",
            "LONDON WATERLOO PLATFORMS 1-4",
            "LONDON WATERLOO HIGH LEVEL",
        ],
    )
    def test_platform_qualifiers_are_stripped(
        self, description: str, names: dict[str, str]
    ) -> None:
        assert crs_from_description(description, names) == "WAT"

    def test_depot_not_matched(self, names: dict[str, str]) -> None:
        # Inventing train service at a depot would be worse than leaving
        # it blank.
        assert crs_from_description("LONDON WATERLOO DEPOT", names) == ""

    def test_unrelated_place(self, names: dict[str, str]) -> None:
        assert crs_from_description("GOUROCK PIER", names) == ""


class TestLoadTiplocCrsMap:
    def test_published_codes_are_read(self, cif_feed: pathlib.Path) -> None:
        mapping = load_tiploc_crs_map(cif_feed)
        assert mapping["AAAA"] == "AAA"
        assert mapping["DDDD"] == "DDD"

    def test_no_crs_without_reference(self, cif_feed: pathlib.Path) -> None:
        mapping = load_tiploc_crs_map(cif_feed)
        assert mapping["CCCC"] == ""

    def test_crs_recovered_from_description(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path
    ) -> None:
        # The London Waterloo case: published with crs_code null, but
        # the description names the station.
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        assert mapping["CCCC"] == "CCC"

    def test_depot_not_recovered(
        self, cif_feed: pathlib.Path, station_reference: pathlib.Path
    ) -> None:
        mapping = load_tiploc_crs_map(cif_feed, station_reference=station_reference)
        assert mapping["DEPOTXX"] == ""

    def test_overrides_win(self, cif_feed: pathlib.Path, station_reference: pathlib.Path) -> None:
        mapping = load_tiploc_crs_map(
            cif_feed, station_reference=station_reference, overrides={"cccc": "zzz"}
        )
        assert mapping["CCCC"] == "ZZZ"

    def test_warns_when_no_reference_is_given(
        self, cif_feed: pathlib.Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        with caplog.at_level("WARNING"):
            load_tiploc_crs_map(cif_feed)
        assert "London Waterloo goes missing" in caplog.text


class TestStationCodes:
    def test_reads_a_crs_column(self, station_reference: pathlib.Path) -> None:
        assert load_station_codes(station_reference) == {"AAA", "BBB", "CCC", "DDD"}

    def test_reads_a_headerless_two_column_list(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / "simple.csv"
        path.write_text("Aytown,AAA\nBeeford,BBB\n")
        assert load_station_codes(path) == {"AAA", "BBB"}

    def test_tiplocs_for_filters_the_mapping(self) -> None:
        mapping = {"AAAA": "AAA", "BBBB": "BBB", "ZZZZ": ""}
        assert tiplocs_for(mapping, {"AAA"}) == {"AAAA"}
