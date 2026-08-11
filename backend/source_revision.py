"""Resolve a Git revision from lightweight checkout metadata."""

from __future__ import annotations

import argparse
import re
from pathlib import Path

_SHA_RE = re.compile(r"^[0-9a-fA-F]{7,64}$")


def _valid_sha(value: str) -> str:
    candidate = value.strip()
    return candidate if _SHA_RE.fullmatch(candidate) else ""


def git_revision(git_dir: Path) -> str:
    """Return the checkout revision without requiring the git executable."""
    head_path = git_dir / "HEAD"
    try:
        head = head_path.read_text(encoding="utf-8").strip()
    except OSError:
        return ""

    direct = _valid_sha(head)
    if direct:
        return direct
    if not head.startswith("ref:"):
        return ""

    reference = head[4:].strip()
    if not reference:
        return ""

    try:
        loose = (git_dir / reference).read_text(encoding="utf-8").strip()
    except OSError:
        loose = ""
    resolved = _valid_sha(loose)
    if resolved:
        return resolved

    try:
        packed_lines = (git_dir / "packed-refs").read_text(encoding="utf-8").splitlines()
    except OSError:
        return ""

    suffix = f" {reference}"
    for line in packed_lines:
        if line.startswith(("#", "^")) or not line.endswith(suffix):
            continue
        resolved = _valid_sha(line.split(" ", 1)[0])
        if resolved:
            return resolved
    return ""


def write_revision(git_dir: Path, output: Path) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(git_revision(git_dir), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--git-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    write_revision(args.git_dir, args.output)


if __name__ == "__main__":
    main()
