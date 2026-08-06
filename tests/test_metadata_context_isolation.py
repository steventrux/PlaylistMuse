from __future__ import annotations

from contextvars import Context

from backend.metadata_validation import active_constraints


def test_default_metadata_constraints_are_not_shared_between_contexts() -> None:
    first = Context().run(active_constraints)
    first.allowed_artists.append("Example Artist")

    second = Context().run(active_constraints)

    assert second is not first
    assert second.allowed_artists == []
