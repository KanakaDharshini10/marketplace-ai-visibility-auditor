#!/usr/bin/env python3
"""Phase 1 only: build the shared evidence bundle and write it to disk.

Useful when you want to inspect exactly what the audit observed, or to run the
specialists separately (see compose_report.py). This is the only script in the
marketplace that performs network I/O.
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
from aiva import discover, jsonschema_lite, paths     # noqa: E402
from aiva.config import AuditConfig                   # noqa: E402

FIXTURES = {
    "weak": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_weak",
    "mixed": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_mixed",
    "strong": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_strong",
    "locales": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_locales",
    "semantic": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_semantic",
    "rendered": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_rendered",
}


def main(argv: Optional[List[str]] = None) -> int:
    util.use_utf8_stdio()   # a report quotes the site's own text; write it as UTF-8
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("site", nargs="?", help="site URL or bare domain")
    parser.add_argument("--offline", choices=sorted(FIXTURES))
    parser.add_argument("--out", required=True, help="path to write the bundle JSON")
    parser.add_argument("--max-pages", type=int, default=None)
    parser.add_argument("--time-budget", type=float, default=None)
    parser.add_argument("--no-external", action="store_true")
    parser.add_argument("--render", action="store_true",
                        help="also collect browser-rendered evidence for a bounded subset "
                             "of pages (requires Playwright; skipped gracefully if absent)")
    parser.add_argument("--render-pages", type=int, default=None,
                        help="how many pages the optional render pass may open "
                             "(default 3); only meaningful with --render")
    parser.add_argument("--validate", action="store_true",
                        help="validate the bundle against schemas/evidence-bundle.schema.json")
    args = parser.parse_args(argv)
    if not args.site and not args.offline:
        parser.error("provide a site URL, or --offline weak|mixed|strong")

    server = None
    site = args.site
    if args.offline:
        from aiva import localserve
        server, site = localserve.start(FIXTURES[args.offline],
                                        soft_404=(args.offline == "weak"))

    config = AuditConfig(site=site)
    if args.max_pages is not None:
        config.max_pages = args.max_pages
    if args.time_budget is not None:
        config.total_time_budget_s = args.time_budget
    if args.offline:
        config.request_delay_s = 0.1
        config.check_external = False
    if args.no_external:
        config.check_external = False
    config.use_headless_render = bool(args.render)
    if args.render_pages is not None:
        config.render_page_limit = max(0, args.render_pages)

    try:
        bundle = discover.collect(config)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    Path(args.out).write_text(json.dumps(bundle, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"wrote {args.out} "
          f"({bundle['stats']['html_pages_parsed']} page(s), "
          f"{bundle['stats']['requests']} request(s), "
          f"{bundle['stats']['cache_reuses']} cache reuse(s))", file=sys.stderr)

    if args.validate:
        schema = paths.load_schema("evidence-bundle.schema.json")
        errors = jsonschema_lite.validate(bundle, schema)
        for error in errors[:20]:
            print(f"BUNDLE SCHEMA ERROR {error}", file=sys.stderr)
        if errors:
            return 1
        print("bundle validates against evidence-bundle.schema.json", file=sys.stderr)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
