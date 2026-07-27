"""Configuration persistence for PlaylistMuse."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from pathlib import Path

DATA_DIR = Path(os.getenv("PLAYLISTMUSE_DATA_DIR", "data"))
CONFIG_PATH = DATA_DIR / "config.json"


@dataclass(slots=True)
class AppConfig:
    provider: str = ""
    api_key: str = ""
    model: str = ""
    fallback_1: str = ""
    fallback_2: str = ""
    base_url: str = ""

    @property
    def configured(self) -> bool:
        if not self.provider or not self.model:
            return False
        if self.provider == "ollama":
            return bool(self.base_url)
        return bool(self.api_key or (self.provider == "custom" and self.base_url))

    @property
    def model_chain(self) -> list[str]:
        """Return the primary model followed by unique configured fallbacks."""
        models: list[str] = []
        for value in (self.model, self.fallback_1, self.fallback_2):
            model = value.strip()
            if model and model not in models:
                models.append(model)
        return models


def _environment_or_saved(name: str, saved: str = "") -> str:
    """Use a non-empty environment override, otherwise keep the saved value."""
    environment_value = os.getenv(name)
    if environment_value is not None and environment_value.strip():
        return environment_value.strip()
    return str(saved or "").strip()


def load_config() -> AppConfig:
    values: dict[str, str] = {}
    if CONFIG_PATH.exists():
        try:
            values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            values = {}

    return AppConfig(
        provider=_environment_or_saved(
            "PLAYLISTMUSE_AI_PROVIDER", values.get("provider", "")
        ),
        api_key=_environment_or_saved(
            "PLAYLISTMUSE_AI_API_KEY", values.get("api_key", "")
        ),
        model=_environment_or_saved(
            "PLAYLISTMUSE_AI_MODEL", values.get("model", "")
        ),
        fallback_1=_environment_or_saved(
            "PLAYLISTMUSE_AI_FALLBACK_1", values.get("fallback_1", "")
        ),
        fallback_2=_environment_or_saved(
            "PLAYLISTMUSE_AI_FALLBACK_2", values.get("fallback_2", "")
        ),
        base_url=_environment_or_saved(
            "PLAYLISTMUSE_AI_BASE_URL", values.get("base_url", "")
        ),
    )


def save_config(config: AppConfig) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    temporary = CONFIG_PATH.with_suffix(".tmp")
    temporary.write_text(json.dumps(asdict(config), indent=2), encoding="utf-8")
    try:
        temporary.chmod(0o600)
    except OSError:
        pass
    temporary.replace(CONFIG_PATH)
