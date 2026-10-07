"""Build the TIPLOC to CRS mapping from a CIF schedule feed.

Schedules address locations by TIPLOC (a timing point code). Almost
everything downstream wants CRS, the three-letter station code
passengers see. The feed's ``TiplocV1`` records map one to the other,
but with gaps.

Missing CRS codes
-----------------
The CIF publishes several TIPLOCs per station, one per platform group,
and for some of them ``crs_code`` is null while ``tps_description``
still names the station plainly::

    {"tiploc_code": "WATRLMN", "crs_code": null,
     "tps_description": "LONDON WATERLOO"}

Code that drops calls without a CRS loses those stations without any
error. In a national run that removed Waterloo, Victoria, London
Bridge, Clapham Junction and Vauxhall, and with them every South
Western flow into London.

When a station list is supplied, TIPLOCs with no published CRS are
recovered by matching their description against station names. Only
exact matches count, after platform group qualifiers are stripped. A
description that does not resolve to exactly one station stays
unmapped, so a rail replacement bus stop, ferry pier or depot never
gains train service.
"""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING

import pandas as pd

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

# Qualifiers the CIF appends when a station has several TIPLOCs.
# Stripping one and matching the rest of the name recovers the station.
PLATFORM_GROUP_SUFFIXES = (
    "(E)",
    "(W)",
    "(N)",
    "(S)",
    "(EAST)",
    "(WEST)",
    "(NORTH)",
    "(SOUTH)",
    "(TOWN PLAT)",
    "(MAIN)",
    "D.C.",
    "DC",
    "ELL",
    "NLL",
    "HIGH LEVEL",
    "LOW LEVEL",
    "MAIN",
    "STATION",
)

PLATFORM_NUMBERS = re.compile(r"\b(PLATS?|PLATFORMS?)\s*[\d\s-]*$")

# How many qualifiers to strip before giving up on a description.
MAX_SUFFIX_STRIPS = 3

NAME_COLUMN = "stationName"
CODE_COLUMN = "crsCode"


def normalise_station_name(name: str) -> str:
    """Upper-case, expand ``&`` and reduce to single-spaced words.

    >>> normalise_station_name("Ashton-under-Lyne")
    'ASHTON UNDER LYNE'
    >>> normalise_station_name("Bath & Wells")
    'BATH AND WELLS'
    """
    text = str(name).upper().replace("&", " AND ")
    return " ".join(re.sub(r"[^A-Z0-9]+", " ", text).split())


def load_station_names(station_reference: pathlib.Path) -> dict[str, str]:
    """Map normalised station names to CRS, where the name is unique.

    A name shared by two CRS codes is dropped rather than guessed at.
    """
    frame = pd.read_csv(station_reference)
    if not {NAME_COLUMN, CODE_COLUMN}.issubset(frame.columns):
        logger.warning(
            "%s has no %s/%s columns, so TIPLOCs without a published CRS cannot be "
            "recovered by name",
            station_reference,
            NAME_COLUMN,
            CODE_COLUMN,
        )
        return {}

    by_name: dict[str, set[str]] = {}
    for name, code in zip(frame[NAME_COLUMN], frame[CODE_COLUMN], strict=True):
        if pd.isna(name) or pd.isna(code):
            continue
        by_name.setdefault(normalise_station_name(name), set()).add(str(code).strip().upper())
    return {name: next(iter(codes)) for name, codes in by_name.items() if len(codes) == 1}


def crs_from_description(description: str, names: dict[str, str]) -> str:
    """Recover a CRS from a TIPLOC description, or return ``""``.

    Matches the whole description, then retries after stripping one
    platform-group qualifier at a time. Only an exact match on the whole
    remaining name is accepted.
    """
    text = description.strip().upper()
    for _ in range(MAX_SUFFIX_STRIPS + 1):
        code = names.get(normalise_station_name(text))
        if code:
            return code

        stripped = PLATFORM_NUMBERS.sub("", text).strip()
        for suffix in PLATFORM_GROUP_SUFFIXES:
            if stripped.endswith(suffix) and len(stripped) > len(suffix):
                stripped = stripped[: -len(suffix)].strip(" -")
                break
        if stripped == text:
            return ""
        text = stripped
    return ""


def load_tiploc_crs_map(
    cif_path: pathlib.Path,
    station_reference: pathlib.Path | None = None,
    overrides: dict[str, str] | None = None,
) -> dict[str, str]:
    """Build the TIPLOC to CRS mapping from ``TiplocV1`` records.

    Only lines containing ``TiplocV1`` are parsed as JSON, so this is
    quick even on a feed of several gigabytes. TIPLOCs with no CRS map
    to ``""``.

    Parameters
    ----------
    cif_path
        The newline-delimited JSON schedule feed.
    station_reference
        A CSV with ``stationName`` and ``crsCode`` columns, used to
        recover TIPLOCs the feed publishes without a CRS. Without it
        nothing is recovered, and the module docstring explains what
        that loses.
    overrides
        Explicit TIPLOC to CRS entries, applied last so they win over
        both the feed and name recovery. These are for the few
        descriptions too abbreviated to match, such as
        ``STOURBRIDGE JN (TOWN PLAT)``.
    """
    logger.info("Scanning TIPLOC records in %s", cif_path)
    tiploc_to_crs: dict[str, str] = {}
    descriptions: dict[str, str] = {}

    with cif_path.open() as handle:
        for line in handle:
            if '"TiplocV1"' not in line:
                continue
            record = json.loads(line)["TiplocV1"]
            tiploc = (record.get("tiploc_code") or "").strip().upper()
            if not tiploc:
                continue
            code = record.get("crs_code") or ""
            tiploc_to_crs[tiploc] = code.strip().upper() if code else ""
            if not tiploc_to_crs[tiploc]:
                descriptions[tiploc] = (record.get("tps_description") or "").strip()

    published = sum(1 for code in tiploc_to_crs.values() if code)

    recovered = 0
    if station_reference is not None:
        names = load_station_names(station_reference)
        for tiploc, description in descriptions.items():
            if not description:
                continue
            code = crs_from_description(description, names)
            if code:
                tiploc_to_crs[tiploc] = code
                recovered += 1
        logger.info(
            "Recovered a CRS for %d of %d TIPLOCs published without one, by matching "
            "descriptions against %s",
            recovered,
            len(descriptions),
            station_reference,
        )
    elif descriptions:
        logger.warning(
            "%d TIPLOC(s) have no published CRS and no station reference was given to "
            "recover them. Calls at those locations will be unusable, which is how "
            "London Waterloo goes missing. Pass station_reference to fix it.",
            len(descriptions),
        )

    for tiploc, code in (overrides or {}).items():
        tiploc_to_crs[tiploc.strip().upper()] = str(code).strip().upper()

    logger.info(
        "Loaded %d TIPLOCs, %d with a CRS (%d published, %d recovered, %d overridden)",
        len(tiploc_to_crs),
        sum(1 for code in tiploc_to_crs.values() if code),
        published,
        recovered,
        len(overrides or {}),
    )
    return tiploc_to_crs


def load_station_codes(station_list: pathlib.Path) -> set[str]:
    """Read the set of station codes to keep from a CSV.

    Accepts either a file with a ``crsCode`` column, or a headerless
    two-column ``name,code`` list.
    """
    frame = pd.read_csv(station_list)
    if CODE_COLUMN in frame.columns:
        codes = frame[CODE_COLUMN].dropna().astype(str).str.strip().str.upper()
        return set(codes) - {"NAN", ""}

    frame = pd.read_csv(station_list, header=None, names=["station_name", "code"])
    codes = frame["code"].dropna().astype(str).str.strip().str.upper()
    return set(codes) - {"NAN", ""}


def tiplocs_for(tiploc_to_crs: dict[str, str], codes: set[str]) -> set[str]:
    """The TIPLOCs whose CRS is in *codes*."""
    return {tiploc for tiploc, code in tiploc_to_crs.items() if code in codes}
