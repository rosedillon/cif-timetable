# cif-timetable

[![PyPI](https://img.shields.io/pypi/v/cif-timetable)](https://pypi.org/project/cif-timetable/)
[![Python](https://img.shields.io/pypi/pyversions/cif-timetable)](https://pypi.org/project/cif-timetable/)
[![CI](https://github.com/rosedillon/cif-timetable/actions/workflows/ci.yml/badge.svg)](https://github.com/rosedillon/cif-timetable/actions/workflows/ci.yml)
[![Licence: GPL-3.0](https://img.shields.io/badge/licence-GPL--3.0-blue)](https://github.com/rosedillon/cif-timetable/blob/main/LICENSE)

Turn Network Rail's SCHEDULE feed into a flat table of calling points,
and count how many trains run on each route.

The feed holds every train schedule in Great Britain as
newline-delimited JSON, about 690,000 schedules in a 3.5 GB daily
extract. Each one is a nested record with a validity window, a
running-day bitmap and a calling pattern addressed by TIPLOC. Getting
from that to the number of trains from A to B on a Wednesday takes more
work than it looks.

```python
from pathlib import Path
from cif_timetable import load_tiploc_crs_map, clean_timetable, analyse_routes

feed = Path("CIF_ALL_FULL_DAILY_toc-full.json")
mapping = load_tiploc_crs_map(feed, station_reference=Path("stations.csv"))
clean_timetable(feed, Path("timetable"), tiploc_to_crs=mapping)
analyse_routes(Path("timetable"))
```

## Install

Python 3.11 or later.

```sh
pip install cif-timetable
```

or, from a clone, `pip install .`. It depends on pandas.

## Getting the feed

The SCHEDULE feed comes from
[Network Rail Open Data](https://publicdatafeeds.networkrail.co.uk)
(free registration) or the [Rail Data Marketplace](https://raildata.org.uk).
Download the JSON version, not the fixed-width CIF; this package reads
only the newline-delimited JSON. The
[Open Rail Data wiki](https://wiki.openraildata.com/index.php/SCHEDULE)
documents the record types.

You also need a station list with `stationName` and `crsCode` columns.
The next section explains why.

## Stations that go missing

The feed publishes several TIPLOCs for some stations, one per platform
group. For some of them `crs_code` is null, even though
`tps_description` names the station plainly:

```json
{"tiploc_code": "WATRLMN", "crs_code": null, "tps_description": "LONDON WATERLOO"}
```

A call you cannot match to a station is no use, so any code that drops
calls without a CRS loses those stations, without an error or a
warning. On a national run that removes Waterloo, Victoria, London
Bridge, Clapham Junction and Vauxhall, and every South Western flow
into London with them.

Pass a station list and those TIPLOCs are recovered by matching the
description against station names. On a real extract that recovers 39
TIPLOCs, and they are the ones you would expect:

```
WATRLMN -> WAT     CLPHMJC -> CLJ     LNDNBDE -> LBG
VICTRIC -> VIC     CLPHMJW -> CLJ     LNDNBDC -> LBG
VICTRIE -> VIC     VAUXHLM -> VXH     VAUXHLW -> VXH
```

Only exact matches count, after platform group qualifiers such as
`(MAIN)` or `PLATFORMS 1-4` are stripped. A description that does not
resolve to exactly one station stays unmapped, so a depot, ferry pier
or rail replacement bus stop never gains train service:
`CEEVILLE DEPOT` does not become `CEEVILLE`. A few descriptions are too
abbreviated to match, such as `STOURBRIDGE JN (TOWN PLAT)`; give those
in a JSON file with `--overrides`.

Without a station list you get a warning:

```
WARNING 8513 TIPLOC(s) have no published CRS and no station reference was given to
recover them. Calls at those locations will be unusable, which is how London Waterloo
goes missing. Pass station_reference to fix it.
```

## Two steps

```console
$ cif-timetable clean CIF_ALL_FULL_DAILY_toc-full.json -o timetable \
    --station-reference stations.csv
schedules read        690,533
schedules kept        559,702
call rows           6,769,321
-> timetable/timetable_calls.csv
```

That takes under a minute for a 3.5 GB extract. The file is streamed,
and a substring test skips the JSON parse for the record types that are
not needed, which is most lines.

```console
$ cif-timetable routes -d timetable --top 8
84,307 routes -> timetable/route_frequency_summary.csv

origin_crs destination_crs  daily_trains  peak_tph  peak_hour
       WAT             CLJ           652        41          7
       CLJ             WAT           623        41         17
       VXH             CLJ           537        37         17
       WAT             VXH           537        37         17
       VXH             WAT           529        37          8
       CLJ             VXH           529        37          8
       LVJ             BKQ           435        28          8
       BKQ             LVJ           434        28          8
```

Waterloo to Clapham Junction, with 41 trains an hour in the morning
peak, is the busiest pair in the country, and it would not appear at
all without the CRS recovery above.

`routes` also writes `route_frequency_hourly.csv`, with trains per
route per hour. Use `--date` to choose the day, `--exclude-operator` to
leave an operator out, and `--json` for machine-readable output.

## How trains are counted

Grouping rows is not enough, for two reasons.

A schedule is not a train. Each has a validity window and a running-day
bitmap, and one service can appear several times as seasonal variants,
so counting rows counts some trains twice or more. Instead a snapshot
date is chosen, either the one you give or the middle of the data's own
span moved to a Wednesday. Only schedules that are permanent, cover
that date and have a `1` in that weekday's place in the bitmap are
counted. Short-term overlays, buses, ships and empty stock are left
out.

A route is more than a train's two ends. Every ordered pair of a
service's public stops counts as one train, timed by the earlier stop's
departure hour. A Leeds to London train counts towards Leeds to
Wakefield, Wakefield to Doncaster and Leeds to London alike, because a
passenger can use it for any of them. Counting only origin to
destination would show Wakefield to Doncaster with almost no service.

## Scope

Give `clean` a station list and only schedules touching those stations
are kept:

```sh
cif-timetable clean feed.json -o timetable -s my-stations.csv
```

A kept schedule keeps its whole calling pattern: every in-scope stop
plus every public stop anywhere. A Leeds to London train's London
terminus is recorded even when London is out of scope, so the journey
can still be looked up. Only out-of-scope operational passes are
dropped. The `in_scope` column says whether each stop is one of the
selected stations.

## The calls table

`timetable_calls.csv` has one row per calling point, with the service's
fields repeated on each row so the table is flat:

| Group | Columns |
|---|---|
| Service | `train_uid`, `stp_indicator`, `atoc_code`, `days_runs`, `start_date`, `end_date`, `train_category`, `power_type`, `timing_load`, `speed`, `signalling_id` |
| Whole journey | `svc_origin_crs`, `svc_origin_tiploc`, `svc_origin_dep`, `svc_dest_crs`, `svc_dest_tiploc`, `svc_dest_arr`, `n_scope_stops` |
| This call | `seq`, `tiploc`, `crs`, `location_type`, `arrival`, `departure`, `pass`, `public_arrival`, `public_departure`, `is_public_call`, `in_scope` |

`read_public_calls()` reads it back filtered to permanent, public,
passenger calls with a CRS. That is what most analysis wants, and it is
a fraction of the rows.

[rail-loading](https://github.com/rosedillon/rail-loading) reads this
table to fill in departure times that train operators leave out of
their passenger counts.

## Limitations

- Associations are not followed. `JsonAssociationV1` records (trains
  joining and dividing) are skipped, so a journey that needs a portion
  change is not shown as a through service.
- Short-term changes are left out, not applied. Only permanent (`P`)
  schedules are counted, so an overlay or cancellation that changes a
  train on your snapshot date is ignored.
- Times stay as clock strings: `0712` is `0712`. Trains running past
  midnight are not moved onto the next day.
- There is no routeing or ticketing logic. The table says what the feed
  says a train does, not whether a ticket is valid on it.
- `analyse_routes` counts ordered pairs of stops, so busy stations have
  a great many routes. 84,307 routes for Great Britain is expected.

## Development

```sh
git clone https://github.com/rosedillon/cif-timetable
cd cif-timetable
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
pytest
ruff check . && ruff format --check . && mypy src
```

The tests build a small synthetic feed with the same record shapes as
the real one. It includes a TIPLOC published without a CRS, a depot
that must not match a station, a Sunday-only train, a short-term
overlay, a bus and a pass-only service, and each exclusion rule has a
test. No licensed data is committed.

## Licence

GPL-3.0. See [LICENSE](https://github.com/rosedillon/cif-timetable/blob/main/LICENSE).

Not affiliated with or endorsed by Network Rail.
