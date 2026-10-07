from __future__ import annotations

import json
from typing import TYPE_CHECKING

import pytest

from cif_timetable import cli
from cif_timetable.cli import build_parser

from .conftest import REFERENCE_DATE

if TYPE_CHECKING:
    import pathlib

    from _pytest.capture import CaptureFixture


SMOKE_ARGS = ["routes"]


class TestClean:
    def test_reports_counts(
        self,
        cif_feed: pathlib.Path,
        station_reference: pathlib.Path,
        tmp_path: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            [
                "clean",
                str(cif_feed),
                "-o",
                str(tmp_path / "out"),
                "--station-reference",
                str(station_reference),
            ]
        )
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "schedules read" in out
        assert "timetable_calls.csv" in out

    def test_json_counts(
        self,
        cif_feed: pathlib.Path,
        station_reference: pathlib.Path,
        tmp_path: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            [
                "clean",
                str(cif_feed),
                "-o",
                str(tmp_path / "out"),
                "--station-reference",
                str(station_reference),
                "--json",
            ]
        )
        assert exit_code == 0
        assert json.loads(capsys.readouterr().out)["schedules"] == 8

    def test_warns_without_reference(
        self, cif_feed: pathlib.Path, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["clean", str(cif_feed), "-o", str(tmp_path / "out")]) == 0
        assert "Major London terminals are affected" in capsys.readouterr().err

    def test_scoping_reports_the_tiploc_count(
        self,
        cif_feed: pathlib.Path,
        station_reference: pathlib.Path,
        tmp_path: pathlib.Path,
        capsys: CaptureFixture[str],
    ) -> None:
        exit_code = cli.main(
            ["clean", str(cif_feed), "-o", str(tmp_path / "out"), "-s", str(station_reference)]
        )
        assert exit_code == 0
        assert "map to" in capsys.readouterr().err

    def test_overrides_are_read_from_json(
        self,
        cif_feed: pathlib.Path,
        station_reference: pathlib.Path,
        tmp_path: pathlib.Path,
    ) -> None:
        overrides = tmp_path / "overrides.json"
        overrides.write_text(json.dumps({"DEPOTXX": "ZZZ"}))
        exit_code = cli.main(
            [
                "clean",
                str(cif_feed),
                "-o",
                str(tmp_path / "out"),
                "--station-reference",
                str(station_reference),
                "--overrides",
                str(overrides),
            ]
        )
        assert exit_code == 0

    def test_missing_feed_is_an_error(
        self, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["clean", str(tmp_path / "nope.json")]) == 1
        assert "not found" in capsys.readouterr().err

    def test_station_list_matches_nothing(
        self, cif_feed: pathlib.Path, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        stations = tmp_path / "nomatch.csv"
        stations.write_text("stationName,crsCode\nNowhere,ZZZ\n")
        exit_code = cli.main(
            ["clean", str(cif_feed), "-o", str(tmp_path / "out"), "-s", str(stations)]
        )
        assert exit_code == 1
        assert "no TIPLOCs matched" in capsys.readouterr().err


class TestRoutes:
    def test_prints_the_top_routes(
        self, cleaned: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(["routes", "-d", str(cleaned), "--date", REFERENCE_DATE])
        assert exit_code == 0
        out = capsys.readouterr().out
        assert "daily_trains" in out
        assert "AAA" in out

    def test_json_output(self, cleaned: pathlib.Path, capsys: CaptureFixture[str]) -> None:
        exit_code = cli.main(["routes", "-d", str(cleaned), "--date", REFERENCE_DATE, "--json"])
        assert exit_code == 0
        payload = json.loads(capsys.readouterr().out)
        assert any(row["origin_crs"] == "AAA" for row in payload)

    def test_top_limits_the_output(
        self, cleaned: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        exit_code = cli.main(
            ["routes", "-d", str(cleaned), "--date", REFERENCE_DATE, "--top", "2", "--json"]
        )
        assert exit_code == 0
        assert len(json.loads(capsys.readouterr().out)) == 2

    def test_date_with_no_services(
        self, cleaned: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["routes", "-d", str(cleaned), "--date", "2099-01-01"]) == 0
        assert "No qualifying passenger services" in capsys.readouterr().err

    def test_missing_calls_table(
        self, tmp_path: pathlib.Path, capsys: CaptureFixture[str]
    ) -> None:
        assert cli.main(["routes", "-d", str(tmp_path)]) == 1
        assert "cif-timetable clean" in capsys.readouterr().err


def test_no_subcommand_is_an_error() -> None:
    with pytest.raises(SystemExit) as exit_info:
        cli.main([])
    assert exit_info.value.code != 0


@pytest.mark.parametrize(
    ("argv", "verbose"),
    [(SMOKE_ARGS, False), (["-v", *SMOKE_ARGS], True), ([*SMOKE_ARGS, "-v"], True)],
)
def test_verbose_flag(argv: list[str], verbose: bool) -> None:
    assert build_parser().parse_args(argv).verbose is verbose
