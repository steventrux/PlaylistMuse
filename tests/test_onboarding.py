from __future__ import annotations

from pathlib import Path

import backend.onboarding as onboarding


def test_onboarding_is_required_until_acknowledged(
    monkeypatch,
    tmp_path: Path,
) -> None:
    path = tmp_path / "onboarding.json"
    monkeypatch.setattr(onboarding, "ONBOARDING_PATH", path)

    assert onboarding.onboarding_status() == {"required": True}
    assert onboarding.acknowledge_onboarding() == {"required": False}
    assert onboarding.onboarding_status() == {"required": False}
    assert path.stat().st_mode & 0o777 == 0o600
