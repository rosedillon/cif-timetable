"""Command-line interface.

``clean`` turns a schedule feed into a calls table, and ``routes``
counts services from that table.
"""

from __future__ import annotations

import argparse
import json
import logging
import pathlib
import sys
from typing import TYPE_CHECKING

from cif_timetable.routes import (
    DEFAULT_DAYTIME_HOURS,
    DEFAULT_REFERENCE_WEEKDAY,
    SUMMARY_FILENAME,
    analyse_routes,
)
from cif_timetable.schedules import CALLS_FILENAME, clean_timetable
from cif_timetable.tiplocs import load_station_codes, load_tiploc_crs_map, tiplocs_for

if TYPE_CHECKING:
    from collections.abc import Sequence

logger = logging.getLogger(__name__)


def _cmd_clean(args: argparse.Namespace) -> int:
    if not args.cif.exists():
        print(f"error: {args.cif} not found", file=sys.stderr)
        return 1

    overrides = {}
    if args.overrides:
        overrides = json.loads(args.overrides.read_text())

    reference = args.station_reference or args.stations
    if reference is None:
        print(
            "warning: no --stations or --station-reference given, so TIPLOCs the feed "
            "publishes without a CRS cannot be recovered. Major London terminals are "
            "affected; the README explains.",
            file=sys.stderr,
        )

    mapping = load_tiploc_crs_map(args.cif, station_reference=reference, overrides=overrides)

    scope = None
    if args.stations is not None:
        codes = load_station_codes(args.stations)
        scope = tiplocs_for(mapping, codes)
        print(f"{len(codes):,} station codes map to {len(scope):,} TIPLOCs", file=sys.stderr)
        if not scope:
            print(
                "error: no TIPLOCs matched the station list; check the CRS column",
                file=sys.stderr,
            )
            return 1

    counts = clean_timetable(
        args.cif,
        args.output,
        tiploc_to_crs=mapping,
        scope_tiplocs=scope,
        exclude_operators=set(args.exclude_operator or ()),
    )

    if args.json:
        json.dump(counts, sys.stdout, indent=2)
        sys.stdout.write("\n")
    else:
        print(f"schedules read   {counts['schedules']:>12,}")
        print(f"schedules kept   {counts['kept']:>12,}")
        print(f"call rows        {counts['call_rows']:>12,}")
        if counts["excluded"]:
            print(f"excluded         {counts['excluded']:>12,}")
        print(f"-> {args.output / CALLS_FILENAME}")
    return 0


def _cmd_routes(args: argparse.Namespace) -> int:
    calls_path = args.directory / CALLS_FILENAME
    if not calls_path.exists():
        print(
            f"error: {calls_path} not found. Run `cif-timetable clean <feed> -o "
            f"{args.directory}` first.",
            file=sys.stderr,
        )
        return 1

    summary = analyse_routes(
        args.directory,
        reference_date=args.date,
        reference_weekday=args.weekday,
        daytime_hours=(args.daytime_start, args.daytime_end),
        exclude_operators=set(args.exclude_operator or ()),
    )
    if summary.empty:
        print("No qualifying passenger services found.", file=sys.stderr)
        return 0

    if args.json:
        summary.head(args.top).to_json(sys.stdout, orient="records", indent=2)
        sys.stdout.write("\n")
        return 0

    print(f"{len(summary):,} routes -> {args.directory / SUMMARY_FILENAME}\n")
    columns = ["origin_crs", "destination_crs", "daily_trains", "peak_tph", "peak_hour"]
    print(summary.head(args.top)[columns].to_string(index=False))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cif-timetable",
        description=(
            "Parse a Network Rail CIF schedule feed (newline-delimited JSON) into a "
            "table of calling points, and count route frequencies from it."
        ),
    )
    parser.add_argument("-v", "--verbose", action="store_true", help="log progress")
    subparsers = parser.add_subparsers(dest="command", required=True)

    clean = subparsers.add_parser(
        "clean",
        help="Turn a schedule feed into a calls table.",
        description="Stream the feed and write one row per calling point.",
    )
    clean.add_argument("cif", type=pathlib.Path, help="the schedule feed (.json)")
    clean.add_argument(
        "-o",
        "--output",
        type=pathlib.Path,
        default=pathlib.Path("timetable"),
        help="output directory (default: ./timetable)",
    )
    clean.add_argument(
        "-s",
        "--stations",
        type=pathlib.Path,
        help="CSV of station codes to keep; omit to keep the whole network",
    )
    clean.add_argument(
        "--station-reference",
        type=pathlib.Path,
        help="station name/code CSV for recovering TIPLOCs with no published CRS "
        "(defaults to --stations)",
    )
    clean.add_argument(
        "--overrides", type=pathlib.Path, help="JSON file of explicit TIPLOC->CRS entries"
    )
    clean.add_argument(
        "--exclude-operator",
        action="append",
        metavar="ATOC",
        help="drop an operator entirely, e.g. ME for Merseyrail (repeatable)",
    )
    clean.add_argument("--json", action="store_true", help="emit counts as JSON")
    clean.set_defaults(func=_cmd_clean)

    routes = subparsers.add_parser(
        "routes",
        help="Count trains per route on a typical weekday.",
        description="Count services per origin/destination/hour from a calls table.",
    )
    routes.add_argument(
        "-d",
        "--directory",
        type=pathlib.Path,
        default=pathlib.Path("timetable"),
        help="directory holding the calls table (default: ./timetable)",
    )
    routes.add_argument("--date", help="snapshot date, YYYY-MM-DD (default: derived)")
    routes.add_argument(
        "--weekday",
        type=int,
        default=DEFAULT_REFERENCE_WEEKDAY,
        help="weekday to snapshot when no date is given, 0=Monday (default: 2)",
    )
    routes.add_argument(
        "--daytime-start", type=int, default=DEFAULT_DAYTIME_HOURS[0], help="daytime start hour"
    )
    routes.add_argument(
        "--daytime-end", type=int, default=DEFAULT_DAYTIME_HOURS[1], help="daytime end hour"
    )
    routes.add_argument(
        "--exclude-operator", action="append", metavar="ATOC", help="drop an operator"
    )
    routes.add_argument("--top", type=int, default=15, help="how many routes to print")
    routes.add_argument("--json", action="store_true", help="emit JSON")
    routes.set_defaults(func=_cmd_routes)

    # -v also works after the subcommand.
    for subcommand in subparsers.choices.values():
        subcommand.add_argument(
            "-v",
            "--verbose",
            action="store_true",
            default=argparse.SUPPRESS,
            help="log progress",
        )

    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(levelname)s %(message)s",
    )
    return int(args.func(args))
