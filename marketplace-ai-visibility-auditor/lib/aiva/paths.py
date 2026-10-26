"""Filesystem layout helpers.

The marketplace is self-contained: nothing outside its root is ever read, and
no external service is needed to resolve it.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Dict, List, Optional

# lib/aiva/paths.py -> lib/aiva -> lib -> <marketplace root>
MARKETPLACE_ROOT = Path(__file__).resolve().parents[2]


def root() -> Path:
    return MARKETPLACE_ROOT


def manifest_path() -> Path:
    return MARKETPLACE_ROOT / "marketplace.json"


def load_manifest() -> dict:
    with manifest_path().open("r", encoding="utf-8") as handle:
        return json.load(handle)


def schema_path(name: str) -> Path:
    return MARKETPLACE_ROOT / "schemas" / name


def load_schema(name: str) -> dict:
    with schema_path(name).open("r", encoding="utf-8") as handle:
        return json.load(handle)


def skills_dir() -> Path:
    return MARKETPLACE_ROOT / "skills"


def entrypoint_skill(manifest: Optional[dict] = None) -> dict:
    manifest = manifest or load_manifest()
    entries = [s for s in manifest.get("skills", []) if s.get("entrypoint")]
    if len(entries) != 1:
        raise ValueError(
            f"marketplace.json must mark exactly one skill as entrypoint, found {len(entries)}")
    return entries[0]


def specialist_skills(manifest: Optional[dict] = None) -> List[dict]:
    manifest = manifest or load_manifest()
    return [s for s in manifest.get("skills", []) if not s.get("entrypoint")]


def resolve_skill_path(entry: Dict[str, str]) -> Path:
    path = MARKETPLACE_ROOT / entry["path"]
    if not path.is_dir():
        raise FileNotFoundError(f"skill path does not exist: {entry['path']}")
    return path


def find_root_from(start: Path) -> Optional[Path]:
    """Walk upwards looking for a marketplace root (used by skill scripts)."""
    current = start.resolve()
    for candidate in [current, *current.parents]:
        if (candidate / "marketplace.json").is_file() and (candidate / "lib" / "aiva").is_dir():
            return candidate
    return None
