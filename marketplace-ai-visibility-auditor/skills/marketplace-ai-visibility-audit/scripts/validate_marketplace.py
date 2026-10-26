#!/usr/bin/env python3
"""Self-check: is this package a valid Agent Skill Marketplace?

Validates every skill folder against the agentskills.io SKILL.md specification
(name rules, description limits, folder-name match, resolvable relative links)
and the marketplace manifest against the contest's convention (exactly one
entrypoint, every declared path exists, every folder on disk is declared).

    python skills/marketplace-ai-visibility-audit/scripts/validate_marketplace.py
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import List, Optional


def _bootstrap() -> Path:
    here = Path(__file__).resolve()
    for candidate in [here.parent, *here.parents]:
        if (candidate / "marketplace.json").is_file() and \
                (candidate / "lib" / "aiva" / "__init__.py").is_file():
            lib = str(candidate / "lib")
            if lib not in sys.path:
                sys.path.insert(0, lib)
            return candidate
    raise RuntimeError("cannot locate the marketplace root")


MARKETPLACE_ROOT = _bootstrap()

from aiva import util                                # noqa: E402
from aiva import validate  # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    util.use_utf8_stdio()   # a report quotes the site's own text; write it as UTF-8
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--json", action="store_true", help="emit machine-readable output")
    parser.add_argument("--strict", action="store_true",
                        help="treat warnings as failures")
    args = parser.parse_args(argv)

    result = validate.validate_marketplace(MARKETPLACE_ROOT)
    if args.json:
        print(json.dumps(result.to_dict(), indent=2))
    else:
        for message in result.checks:
            print(f"  ok      {message}")
        for message in result.warnings:
            print(f"  warn    {message}")
        for message in result.errors:
            print(f"  ERROR   {message}")
        print()
        print(f"{len(result.checks)} check(s) passed, {len(result.warnings)} warning(s), "
              f"{len(result.errors)} error(s)")
    if result.errors:
        return 1
    if args.strict and result.warnings:
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
