#!/usr/bin/env python3
"""Phase 2 only: compose specialist findings over an existing evidence bundle.

Two modes:

* default - load every specialist declared in marketplace.json and run it
  against the bundle (this is what run_audit.py does internally);
* ``--findings a.json b.json ...`` - merge findings produced by running each
  specialist's own ``scripts/analyze.py --bundle ...`` separately, which is
  useful for debugging one skill in isolation.

Performs no network I/O.
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
from aiva import orchestrator, report as report_mod          # noqa: E402
from aiva.config import AuditConfig                          # noqa: E402
from aiva.findings import Finding, finding_from_dict         # noqa: E402


def main(argv: Optional[List[str]] = None) -> int:
    util.use_utf8_stdio()   # a report quotes the site's own text; write it as UTF-8
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True, help="evidence bundle JSON")
    parser.add_argument("--findings", nargs="*", default=None,
                        help="specialist findings JSON files to merge instead of "
                             "running the specialists in-process")
    parser.add_argument("--out", help="write the report here (default: stdout)")
    parser.add_argument("--format", choices=("json", "markdown"), default="json")
    parser.add_argument("--schema", choices=("full", "handout", "flat"), default="full")
    args = parser.parse_args(argv)

    bundle = json.loads(Path(args.bundle).read_text(encoding="utf-8"))
    config = AuditConfig(**{k: v for k, v in (bundle.get("config") or {}).items()
                            if k in AuditConfig.__dataclass_fields__})
    if not config.site:
        config.site = bundle.get("site", {}).get("home_url", "")

    runs: List[dict] = []
    findings: List[Finding] = []
    if args.findings:
        pillars = orchestrator.specialist_pillars()
        for path in args.findings:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            produced = [finding_from_dict(item) for item in payload.get("findings", [])]
            for item in produced:
                item.source_skill = item.source_skill or payload.get("skill", "")
            findings.extend(produced)
            skill_id = payload.get("skill", Path(path).stem)
            runs.append({"skill": skill_id,
                         "pillar": payload.get("pillar") or pillars.get(skill_id, ""),
                         "status": orchestrator.RUN_OK, "ok": True,
                         "findings": len(produced), "source_file": str(path)})
    else:
        findings, runs = orchestrator.run_specialists(bundle)

    report = report_mod.build_report(bundle, findings, config, skill_runs=runs)
    errors = report_mod.validate_report(report)
    report["diagnostics"]["schema_validation"] = {
        "schema": report_mod.SCHEMA_FILE, "valid": not errors, "errors": errors}
    for error in errors[:10]:
        print(f"SCHEMA WARNING {error}", file=sys.stderr)

    if args.format == "markdown":
        output = report_mod.render_markdown(report)
    else:
        output = report_mod.dumps(report_mod.project(report, args.schema))

    if args.out:
        Path(args.out).write_text(output, encoding="utf-8")
        print(f"wrote {args.out}", file=sys.stderr)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
