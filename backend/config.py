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


def load_config() -> AppConfig:
    values: dict[str, str] = {}
    if CONFIG_PATH.exists():
        try:
            values = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            values = {}

    return AppConfig(
        provider=os.getenv("PLAYLISTMUSE_AI_PROVIDER", values.get("provider", "")).strip(),
        api_key=os.getenv("PLAYLISTMUSE_AI_API_KEY", values.get("api_key", "")).strip(),
        model=os.getenv("PLAYLISTMUSE_AI_MODEL", values.get("model", "")).strip(),
        fallback_1=os.getenv(
            "PLAYLISTMUSE_AI_FALLBACK_1", values.get("fallback_1", "")
        ).strip(),
        fallback_2=os.getenv(
            "PLAYLISTMUSE_AI_FALLBACK_2", values.get("fallback_2", "")
        ).strip(),
        base_url=os.getenv("PLAYLISTMUSE_AI_BASE_URL", values.get("base_url", "")).strip(),
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
