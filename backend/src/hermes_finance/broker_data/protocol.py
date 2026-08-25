"""Replaceable read-only current broker-snapshot provider protocol."""

from __future__ import annotations

from typing import Protocol

from hermes_finance.broker_data.dto import BrokerSnapshot


class BrokerSnapshotProvider(Protocol):
    def fetch_snapshot(self) -> BrokerSnapshot: ...
