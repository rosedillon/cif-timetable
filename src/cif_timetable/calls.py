"""Read back the calls table, filtered to what most analysis wants."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

import pandas as pd

from cif_timetable.schedules import PASSENGER_CATEGORY_PREFIXES, SERVICE_KEY

if TYPE_CHECKING:
    import pathlib

logger = logging.getLogger(__name__)

# Enough to identify a service and where it calls, without the full
# table.
PUBLIC_CALL_COLUMNS = [
    *SERVICE_KEY,
    "atoc_code",
    "train_category",
    "days_runs",
    "svc_origin_crs",
    "svc_dest_crs",
    "seq",
    "tiploc",
    "crs",
    "public_arrival",
    "public_departure",
    "is_public_call",
    "stp_indicator",
    "in_scope",
]

DEFAULT_CHUNK_SIZE = 1_000_000
PERMANENT = "P"


def read_public_calls(
    calls_path: pathlib.Path, chunk_size: int = DEFAULT_CHUNK_SIZE
) -> pd.DataFrame:
    """Read permanent, public, passenger calls from the calls table.

    A national calls table runs to tens of millions of rows, and most
    analysis wants few of them. Overlay schedules, operational passes,
    non-passenger services and calls at locations with no CRS (which
    cannot be matched to a station) are all dropped. Filtering chunk by
    chunk while reading keeps memory to a fraction of the whole file.
    """
    chunks = []
    for chunk in pd.read_csv(
        calls_path, dtype=str, usecols=PUBLIC_CALL_COLUMNS, chunksize=chunk_size
    ):
        category = chunk["train_category"].fillna("").str[:1]
        keep = (
            chunk["stp_indicator"].eq(PERMANENT)
            & chunk["is_public_call"].eq("True")
            & category.isin(PASSENGER_CATEGORY_PREFIXES)
            & chunk["crs"].notna()
            & chunk["crs"].ne("")
        )
        chunks.append(chunk[keep])

    calls = (
        pd.concat(chunks, ignore_index=True)
        if chunks
        else pd.DataFrame(columns=PUBLIC_CALL_COLUMNS)
    )
    logger.info("Read %d permanent public passenger calls from %s", len(calls), calls_path)
    return calls
