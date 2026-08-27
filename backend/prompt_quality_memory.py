"""Curated prompt-quality cases shared by regression tests and future user feedback."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

CaseStatus = Literal["candidate", "approved", "deprecated"]
CaseOrigin = Literal["regression", "maintainer", "user_feedback"]
CaseFlow = Literal["generation", "studio"]

_SCHEMA_VERSION = 1
_DEFAULT_MEMORY_PATH = Path(__file__).resolve().parents[1] / "quality" / "prompt_cases.json"


class PromptQualityCase(BaseModel):
    """One structured example of a prompt behavior PlaylistMuse must remember."""

    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=3, max_length=120, pattern=r"^[a-z0-9][a-z0-9-]*$")
    status: CaseStatus = "candidate"
    origin: CaseOrigin
    source: str | None = Field(default=None, max_length=300)
    flows: list[CaseFlow] = Field(min_length=1, max_length=2)
    prompt: str = Field(min_length=3, max_length=2000)
    context: dict[str, Any] = Field(default_factory=dict)
    failure: str = Field(min_length=3, max_length=1200)
    desired_behavior: str = Field(min_length=3, max_length=1200)
    guidance: str = Field(default="", max_length=1600)
    expectations: dict[str, Any] = Field(default_factory=dict)
    tags: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("flows")
    @classmethod
    def unique_flows(cls, value: list[CaseFlow]) -> list[CaseFlow]:
        return list(dict.fromkeys(value))

    @field_validator("tags")
    @classmethod
    def clean_tags(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        for tag in value:
            normalized = "-".join(str(tag).strip().casefold().split())[:60]
            if normalized and normalized not in cleaned:
                cleaned.append(normalized)
        return cleaned


class PromptQualityMemory(BaseModel):
    """Versioned quality corpus; only approved cases are allowed to guide production later."""

    model_config = ConfigDict(extra="forbid")

    schema_version: int = _SCHEMA_VERSION
    cases: list[PromptQualityCase] = Field(default_factory=list)

    @field_validator("schema_version")
    @classmethod
    def supported_schema(cls, value: int) -> int:
        if value != _SCHEMA_VERSION:
            raise ValueError(f"Unsupported prompt-quality schema version: {value}")
        return value

    @field_validator("cases")
    @classmethod
    def unique_case_ids(cls, value: list[PromptQualityCase]) -> list[PromptQualityCase]:
        ids = [case.id for case in value]
        if len(ids) != len(set(ids)):
            raise ValueError("Prompt-quality case ids must be unique.")
        return value


def load_prompt_quality_memory(path: Path | None = None) -> PromptQualityMemory:
    source = path or _DEFAULT_MEMORY_PATH
    payload = json.loads(source.read_text(encoding="utf-8"))
    return PromptQualityMemory.model_validate(payload)


def approved_prompt_quality_cases(
    *,
    flow: CaseFlow | None = None,
    path: Path | None = None,
) -> list[PromptQualityCase]:
    """Return only curated cases; candidate user feedback must never affect behavior directly."""
    cases = [case for case in load_prompt_quality_memory(path).cases if case.status == "approved"]
    if flow is not None:
        cases = [case for case in cases if flow in case.flows]
    return cases
