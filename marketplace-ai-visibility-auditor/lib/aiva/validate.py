"""Self-validation: is this package a well-formed Agent Skill Marketplace?

Checks the agentskills.io SKILL.md rules for every skill folder and the
contest's marketplace.json convention, without any third-party dependency.
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import frontmatter, jsonschema_lite, paths

NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
#: `Read`, `Bash(python3:*)`, `Write` - a tool name, optionally scoped.
_ALLOWED_TOOL_TOKEN = re.compile(r"^[A-Za-z][A-Za-z0-9_-]*(?:\([^()]*\))?$")

KNOWN_FRONTMATTER = {"name", "description", "license", "compatibility", "metadata",
                     "allowed-tools", "version"}
MAX_NAME = 64
MAX_DESCRIPTION = 1024
MAX_COMPATIBILITY = 500
RECOMMENDED_MAX_BODY_LINES = 500


class Result:
    def __init__(self) -> None:
        self.errors: List[str] = []
        self.warnings: List[str] = []
        self.checks: List[str] = []

    def error(self, message: str) -> None:
        self.errors.append(message)

    def warn(self, message: str) -> None:
        self.warnings.append(message)

    def ok(self, message: str) -> None:
        self.checks.append(message)

    @property
    def valid(self) -> bool:
        return not self.errors

    def to_dict(self) -> dict:
        return {"valid": self.valid, "errors": self.errors,
                "warnings": self.warnings, "passed": self.checks}


def validate_skill_folder(folder: Path, result: Result) -> Optional[Dict[str, object]]:
    """Validate one skill folder against the agentskills.io specification."""
    skill_md = folder / "SKILL.md"
    if not skill_md.is_file():
        result.error(f"{folder.name}: no SKILL.md")
        return None
    text = skill_md.read_text(encoding="utf-8")
    raw, body = frontmatter.split(text)
    if raw is None:
        result.error(f"{folder.name}/SKILL.md: no YAML frontmatter delimited by ---")
        return None
    data = frontmatter.parse_mapping(raw)

    name = str(data.get("name", ""))
    if not name:
        result.error(f"{folder.name}/SKILL.md: frontmatter has no 'name'")
    else:
        if len(name) > MAX_NAME:
            result.error(f"{folder.name}: name is {len(name)} chars (max {MAX_NAME})")
        if not NAME_RE.match(name):
            result.error(f"{folder.name}: name '{name}' must be lowercase alphanumeric with "
                         "single hyphens, not starting or ending with a hyphen")
        if name != folder.name:
            result.error(f"{folder.name}: name '{name}' must match the directory name")

    description = str(data.get("description", "")).strip()
    if not description:
        result.error(f"{folder.name}: frontmatter has no 'description'")
    elif len(description) > MAX_DESCRIPTION:
        result.error(f"{folder.name}: description is {len(description)} chars "
                     f"(max {MAX_DESCRIPTION})")
    elif len(description) < 40:
        result.warn(f"{folder.name}: description is very short; it should say what the skill "
                    "does AND when to use it")

    compatibility = str(data.get("compatibility", "") or "")
    if compatibility and len(compatibility) > MAX_COMPATIBILITY:
        result.error(f"{folder.name}: compatibility is {len(compatibility)} chars "
                     f"(max {MAX_COMPATIBILITY})")

    metadata = data.get("metadata")
    if metadata is not None and metadata != "":
        if not isinstance(metadata, dict):
            result.error(f"{folder.name}: metadata must be a mapping of string keys to "
                         "string values")
        else:
            for key, value in metadata.items():
                if not isinstance(value, str):
                    result.error(f"{folder.name}: metadata.{key} must be a string")

    allowed_tools = data.get("allowed-tools")
    if allowed_tools is not None and allowed_tools != "":
        # The spec's format is a single space-separated string, not a YAML
        # list. A list parses as YAML but is not what the frontmatter reader
        # expects, so it is rejected here rather than silently ignored.
        if not isinstance(allowed_tools, str):
            result.error(f"{folder.name}: allowed-tools must be a space-separated string, "
                         f"not {type(allowed_tools).__name__}")
        else:
            for token in allowed_tools.split():
                if not _ALLOWED_TOOL_TOKEN.match(token):
                    result.error(f"{folder.name}: allowed-tools entry {token!r} is not a "
                                 "valid tool token (expected `Name` or `Name(scope)`)")

    unknown = set(data) - KNOWN_FRONTMATTER
    if unknown:
        result.warn(f"{folder.name}: unrecognised frontmatter key(s): "
                    f"{', '.join(sorted(unknown))}")

    body_lines = len(body.splitlines())
    if body_lines > RECOMMENDED_MAX_BODY_LINES:
        result.warn(f"{folder.name}: SKILL.md body is {body_lines} lines; the spec recommends "
                    f"keeping it under {RECOMMENDED_MAX_BODY_LINES} and pushing detail into "
                    "references/")

    # Every relative link in the body must resolve inside the skill folder.
    for match in re.finditer(r"\]\(([^)]+)\)", body):
        target = match.group(1).split("#")[0].strip()
        if not target or target.startswith(("http://", "https://", "mailto:")):
            continue
        if not (folder / target).exists():
            result.error(f"{folder.name}/SKILL.md: broken relative link '{target}'")

    if not result.errors:
        result.ok(f"{folder.name}: SKILL.md is agentskills.io compliant")
    return {"name": name, "description": description, "body_lines": body_lines,
            "frontmatter": data}


def validate_marketplace(root: Optional[Path] = None) -> Result:
    root = root or paths.root()
    result = Result()

    manifest_path = root / "marketplace.json"
    if not manifest_path.is_file():
        result.error("marketplace.json is missing from the marketplace root")
        return result
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        result.error(f"marketplace.json is not valid JSON: {exc}")
        return result
    result.ok("marketplace.json parses as JSON")

    for field in ("name", "version", "skills"):
        if field not in manifest:
            result.error(f"marketplace.json has no '{field}'")
    skills = manifest.get("skills", [])
    if not isinstance(skills, list) or not skills:
        result.error("marketplace.json 'skills' must be a non-empty array")
        return result

    entrypoints = [s for s in skills if s.get("entrypoint")]
    if len(entrypoints) != 1:
        result.error(f"marketplace.json must mark exactly one skill as entrypoint "
                     f"(found {len(entrypoints)})")
    else:
        result.ok(f"exactly one entrypoint skill: {entrypoints[0]['id']}")

    seen_ids: Dict[str, int] = {}
    for entry in skills:
        skill_id = entry.get("id")
        path_value = entry.get("path")
        if not skill_id or not path_value:
            result.error(f"marketplace.json skill entry missing id or path: {entry}")
            continue
        seen_ids[skill_id] = seen_ids.get(skill_id, 0) + 1
        folder = root / path_value
        if not folder.is_dir():
            result.error(f"{skill_id}: path '{path_value}' does not exist")
            continue
        if folder.name != skill_id:
            result.error(f"{skill_id}: manifest id must match the skill folder name "
                         f"('{folder.name}')")
        info = validate_skill_folder(folder, result)
        if info and info["name"] and info["name"] != skill_id:
            result.error(f"{skill_id}: SKILL.md name '{info['name']}' does not match the "
                         "manifest id")
        script = entry.get("script")
        if script and not (folder / script).is_file():
            result.error(f"{skill_id}: declared script '{script}' does not exist")

    for skill_id, count in seen_ids.items():
        if count > 1:
            result.error(f"marketplace.json lists '{skill_id}' {count} times")

    # Every skill folder on disk must be declared in the manifest.
    declared = {entry.get("path") for entry in skills}
    for folder in sorted((root / "skills").glob("*")):
        if not folder.is_dir():
            continue
        relative = f"skills/{folder.name}"
        if relative not in declared:
            result.error(f"skill folder '{relative}' exists on disk but is not listed in "
                         "marketplace.json")

    # Schemas must parse and stay inside the validator's supported subset.
    for schema_name in ("audit-report.schema.json", "evidence-bundle.schema.json"):
        schema_file = root / "schemas" / schema_name
        if not schema_file.is_file():
            result.error(f"schemas/{schema_name} is missing")
            continue
        try:
            schema = json.loads(schema_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            result.error(f"schemas/{schema_name} is not valid JSON: {exc}")
            continue
        unsupported = jsonschema_lite.unsupported_keywords(schema)
        if unsupported:
            result.error(f"schemas/{schema_name} uses keywords the bundled validator does not "
                         f"support: {', '.join(unsupported[:6])}")
        else:
            result.ok(f"schemas/{schema_name} parses and is fully supported")

    if not (root / "README.md").is_file():
        result.error("README.md is missing from the marketplace root")
    else:
        result.ok("README.md present")

    return result
