"""Parse the Network Rail CIF schedule feed into a calling-points table.

Build the TIPLOC to CRS mapping, then write the calls table::

    from cif_timetable import clean_timetable, load_tiploc_crs_map

    mapping = load_tiploc_crs_map(cif, station_reference=stations)
    clean_timetable(cif, out, tiploc_to_crs=mapping)
"""

from __future__ import annotations

from cif_timetable.calls import PUBLIC_CALL_COLUMNS, read_public_calls
from cif_timetable.routes import (
    DEFAULT_DAYTIME_HOURS,
    DEFAULT_REFERENCE_WEEKDAY,
    active_on,
    analyse_routes,
    count_route_hours,
    departure_hours,
    resolve_reference_date,
    summarise,
)
from cif_timetable.schedules import (
    CALLS_COLUMNS,
    CALLS_FILENAME,
    PASSENGER_CATEGORY_PREFIXES,
    SERVICE_KEY,
    call_rows,
    clean_timetable,
    iter_schedules,
    service_summary,
)
from cif_timetable.tiplocs import (
    crs_from_description,
    load_station_codes,
    load_station_names,
    load_tiploc_crs_map,
    normalise_station_name,
    tiplocs_for,
)

__all__ = [
    "CALLS_COLUMNS",
    "CALLS_FILENAME",
    "DEFAULT_DAYTIME_HOURS",
    "DEFAULT_REFERENCE_WEEKDAY",
    "PASSENGER_CATEGORY_PREFIXES",
    "PUBLIC_CALL_COLUMNS",
    "SERVICE_KEY",
    "active_on",
    "analyse_routes",
    "call_rows",
    "clean_timetable",
    "count_route_hours",
    "crs_from_description",
    "departure_hours",
    "iter_schedules",
    "load_station_codes",
    "load_station_names",
    "load_tiploc_crs_map",
    "normalise_station_name",
    "read_public_calls",
    "resolve_reference_date",
    "service_summary",
    "summarise",
    "tiplocs_for",
]

__version__ = "0.1.0"
