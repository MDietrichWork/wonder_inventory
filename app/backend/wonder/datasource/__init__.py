"""Data-source adapters. fetch_table(logical_table, run_date) -> list[dict]."""
from typing import List
from ..config import settings
from .base import DataSource
from .fixtures import FixtureDataSource


def get_datasource(run_dates: List[str]) -> DataSource:
    if settings.data_source == "bigquery":
        from .bigquery import BigQueryDataSource
        return BigQueryDataSource()
    return FixtureDataSource(run_dates)
