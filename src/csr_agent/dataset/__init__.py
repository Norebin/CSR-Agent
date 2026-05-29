"""Dataset ingestion package."""

from .ingestion import (
    DEFAULT_COLUMN_ALIASES,
    discover_csvs,
    load_tasks_from_csv,
    load_tasks_from_csvs,
)

__all__ = [
    "DEFAULT_COLUMN_ALIASES",
    "load_tasks_from_csv",
    "load_tasks_from_csvs",
    "discover_csvs",
]
