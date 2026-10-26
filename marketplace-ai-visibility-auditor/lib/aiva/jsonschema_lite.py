"""A ~100-line JSON Schema subset validator.

The marketplace ships a real ``schemas/audit-report.schema.json`` and validates
its own output against it on every run. Pulling in ``jsonschema`` for that
would break the stdlib-only guarantee, so we implement the subset the schema
actually uses: type, required, properties, additionalProperties, items, enum,
minimum/maximum, minItems, minLength, pattern, oneOf/anyOf, $ref (local),
const and uniqueItems.

Unsupported keywords are ignored rather than silently passing something wrong -
:func:`unsupported_keywords` lets the test-suite assert the schema stays inside
the supported subset.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Tuple

SUPPORTED = {
    "$schema", "$id", "$defs", "$ref", "title", "description", "examples",
    "type", "required", "properties", "additionalProperties", "items",
    "enum", "const", "minimum", "maximum", "exclusiveMinimum", "exclusiveMaximum",
    "minItems", "maxItems", "minLength", "maxLength", "pattern",
    "oneOf", "anyOf", "allOf", "uniqueItems", "default", "format",
}

_TYPES = {
    "object": dict,
    "array": list,
    "string": str,
    "number": (int, float),
    "integer": int,
    "boolean": bool,
    "null": type(None),
}


def unsupported_keywords(schema: Any, path: str = "$") -> List[str]:
    found: List[str] = []
    if isinstance(schema, dict):
        for key, value in schema.items():
            if key not in SUPPORTED:
                found.append(f"{path}.{key}")
            if key in ("properties", "$defs"):
                for name, sub in (value or {}).items():
                    found.extend(unsupported_keywords(sub, f"{path}.{key}.{name}"))
            elif key in ("items", "additionalProperties"):
                if isinstance(value, dict):
                    found.extend(unsupported_keywords(value, f"{path}.{key}"))
            elif key in ("oneOf", "anyOf", "allOf"):
                for index, sub in enumerate(value or []):
                    found.extend(unsupported_keywords(sub, f"{path}.{key}[{index}]"))
    return found


def _resolve(ref: str, root: Dict[str, Any]) -> Dict[str, Any]:
    if not ref.startswith("#"):
        raise ValueError(f"only local $ref is supported, got {ref!r}")
    node: Any = root
    for part in ref.lstrip("#/").split("/"):
        if not part:
            continue
        node = node[part.replace("~1", "/").replace("~0", "~")]
    return node


def _check(instance: Any, schema: Dict[str, Any], root: Dict[str, Any],
           path: str, errors: List[str]) -> None:
    if not isinstance(schema, dict):
        return
    if "$ref" in schema:
        _check(instance, _resolve(schema["$ref"], root), root, path, errors)
        return

    expected = schema.get("type")
    if expected:
        wanted = expected if isinstance(expected, list) else [expected]
        types: Tuple[type, ...] = tuple()
        for name in wanted:
            mapped = _TYPES.get(name)
            if mapped:
                types += mapped if isinstance(mapped, tuple) else (mapped,)
        # bool is a subclass of int in Python; JSON Schema treats them apart.
        if types and (not isinstance(instance, types)
                      or (isinstance(instance, bool) and "boolean" not in wanted)):
            errors.append(f"{path}: expected type {'/'.join(wanted)}, got "
                          f"{type(instance).__name__}")
            return

    if "enum" in schema and instance not in schema["enum"]:
        errors.append(f"{path}: {instance!r} not in enum {schema['enum']}")
    if "const" in schema and instance != schema["const"]:
        errors.append(f"{path}: expected const {schema['const']!r}")

    if isinstance(instance, str):
        if "minLength" in schema and len(instance) < schema["minLength"]:
            errors.append(f"{path}: shorter than minLength {schema['minLength']}")
        if "maxLength" in schema and len(instance) > schema["maxLength"]:
            errors.append(f"{path}: longer than maxLength {schema['maxLength']}")
        if "pattern" in schema and not re.search(schema["pattern"], instance):
            errors.append(f"{path}: {instance!r} does not match {schema['pattern']!r}")

    if isinstance(instance, (int, float)) and not isinstance(instance, bool):
        if "minimum" in schema and instance < schema["minimum"]:
            errors.append(f"{path}: {instance} < minimum {schema['minimum']}")
        if "maximum" in schema and instance > schema["maximum"]:
            errors.append(f"{path}: {instance} > maximum {schema['maximum']}")

    if isinstance(instance, list):
        if "minItems" in schema and len(instance) < schema["minItems"]:
            errors.append(f"{path}: fewer than minItems {schema['minItems']}")
        if "maxItems" in schema and len(instance) > schema["maxItems"]:
            errors.append(f"{path}: more than maxItems {schema['maxItems']}")
        if schema.get("uniqueItems"):
            seen = [repr(i) for i in instance]
            if len(set(seen)) != len(seen):
                errors.append(f"{path}: items are not unique")
        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(instance):
                _check(item, item_schema, root, f"{path}[{index}]", errors)

    if isinstance(instance, dict):
        for name in schema.get("required", []):
            if name not in instance:
                errors.append(f"{path}: missing required property '{name}'")
        properties = schema.get("properties", {})
        for name, sub in properties.items():
            if name in instance:
                _check(instance[name], sub, root, f"{path}.{name}", errors)
        additional = schema.get("additionalProperties", True)
        if additional is False:
            for name in instance:
                if name not in properties:
                    errors.append(f"{path}: unexpected property '{name}'")
        elif isinstance(additional, dict):
            for name, value in instance.items():
                if name not in properties:
                    _check(value, additional, root, f"{path}.{name}", errors)

    for keyword in ("allOf",):
        for sub in schema.get(keyword, []):
            _check(instance, sub, root, path, errors)
    if "anyOf" in schema:
        if not any(not _sub_errors(instance, sub, root) for sub in schema["anyOf"]):
            errors.append(f"{path}: does not match any schema in anyOf")
    if "oneOf" in schema:
        matches = sum(1 for sub in schema["oneOf"] if not _sub_errors(instance, sub, root))
        if matches != 1:
            errors.append(f"{path}: matched {matches} schemas in oneOf (expected exactly 1)")


def _sub_errors(instance: Any, schema: Dict[str, Any], root: Dict[str, Any]) -> List[str]:
    errors: List[str] = []
    _check(instance, schema, root, "$", errors)
    return errors


def validate(instance: Any, schema: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable validation errors (empty == valid)."""
    errors: List[str] = []
    _check(instance, schema, schema, "$", errors)
    return errors
