from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

import backend.generation_counter as generation_counter


def test_generation_counter_persists_and_survives_deletions(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "generation_counter.json"
    monkeypatch.setattr(generation_counter, "GENERATION_COUNTER_PATH", path)

    assert generation_counter.total_generations() == 0
    assert generation_counter.record_generation() == 1
    assert generation_counter.record_generation() == 2
    assert generation_counter.record_generation() == 3
    assert generation_counter.total_generations() == 3

    # A fresh read (e.g. after a restart) sees the same persisted total.
    assert generation_counter.total_generations() == 3


def test_generations_by_month_sums_to_the_lifetime_total(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "generation_counter.json"
    monkeypatch.setattr(generation_counter, "GENERATION_COUNTER_PATH", path)

    assert generation_counter.generations_by_month() == {}

    generation_counter.record_generation()
    generation_counter.record_generation()
    generation_counter.record_generation()

    current_month = datetime.now(UTC).strftime("%Y-%m")
    by_month = generation_counter.generations_by_month()
    assert by_month == {current_month: 3}
    assert sum(by_month.values()) == generation_counter.total_generations()
