#!/usr/bin/env python3
"""Entrypoint: audit a marketplace/brand website and emit one report.

    python skills/marketplace-ai-visibility-audit/scripts/run_audit.py https://example.com

Read-only. GET/HEAD only, robots.txt honoured, rate limited, time budgeted.
Nothing this script can do modifies the audited site.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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
    raise RuntimeError(
        "cannot locate the marketplace root: run this script from inside the "
        "marketplace-ai-visibility-auditor package")


MARKETPLACE_ROOT = _bootstrap()

from aiva import util                                # noqa: E402
from aiva import orchestrator, report as report_mod   # noqa: E402
from aiva.config import AuditConfig                          # noqa: E402
from aiva.version import __version__                         # noqa: E402

FIXTURES = {
    "weak": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_weak",
    "mixed": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_mixed",
    "strong": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_strong",
    "locales": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_locales",
    "semantic": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_semantic",
    "rendered": MARKETPLACE_ROOT / "tests" / "fixtures" / "site_rendered",
}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="run_audit.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="Examples:\n"
               "  run_audit.py https://example.com\n"
               "  run_audit.py https://example.com --out ./audit --format both\n"
               "  run_audit.py --offline mixed --format markdown\n")
    parser.add_argument("site", nargs="?",
                        help="site URL or bare domain to audit")
    parser.add_argument("--offline", choices=sorted(FIXTURES),
                        help="audit a bundled fixture site over a local HTTP server "
                             "(no external network access)")
    parser.add_argument("--out", help="directory to write outputs into")
    parser.add_argument("--format", choices=("json", "markdown", "both"), default="json")
    parser.add_argument("--schema", choices=("full", "handout", "flat"), default="full",
                        help="report projection: full superset, the brief's exact floor, "
                             "or the flattest variant")
    parser.add_argument("--max-pages", type=int, default=None,
                        help="hard cap on HTML documents fetched (default 40)")
    parser.add_argument("--time-budget", type=float, default=None,
                        help="wall-clock budget in seconds (default 240, max 600)")
    parser.add_argument("--delay", type=float, default=None,
                        help="minimum seconds between requests to the same host (default 0.4)")
    parser.add_argument("--render", action="store_true",
                        help="also compare a headless render against the raw fetch "
                             "(requires Playwright; skipped gracefully if absent)")
    parser.add_argument("--render-pages", type=int, default=None,
                        help="how many pages the optional render pass may open "
                             "(default 3); only meaningful with --render")
    parser.add_argument("--no-external", action="store_true",
                        help="skip verification of off-site anchors the site declares")
    parser.add_argument("--user-agent",
                        help="override the auditor's User-Agent. Use only with the site "
                             "owner's consent, e.g. to pass an allowlist the operator "
                             "controls. Strings that impersonate a browser or a known "
                             "crawler are rejected")
    parser.add_argument("--bundle-out", help="also write the raw shared evidence bundle here")
    parser.add_argument("--quiet", action="store_true", help="suppress progress output")
    parser.add_argument("--version", action="version",
                        version=f"marketplace-ai-visibility-auditor {__version__}")
    return parser


def main(argv: Optional[List[str]] = None) -> int:
    util.use_utf8_stdio()   # a report quotes the site's own text; write it as UTF-8
    args = build_parser().parse_args(argv)
    if not args.site and not args.offline:
        build_parser().error("provide a site URL, or --offline weak|mixed|strong")

    def progress(message: str) -> None:
        if not args.quiet:
            print(f"[audit] {message}", file=sys.stderr, flush=True)

    server = None
    site = args.site
    if args.offline:
        from aiva import localserve
        directory = FIXTURES[args.offline]
        server, site = localserve.start(directory, soft_404=(args.offline == "weak"))
        progress(f"serving fixture '{args.offline}' from {directory} at {site}")

    config = AuditConfig(site=site)
    if args.max_pages is not None:
        config.max_pages = args.max_pages
    if args.time_budget is not None:
        config.total_time_budget_s = args.time_budget
    if args.delay is not None:
        config.request_delay_s = args.delay
    if args.offline:
        # Local fixture: no politeness delay needed, and no external anchors.
        config.request_delay_s = max(0.1, args.delay or 0.1)
        config.check_external = False
        config.offline_root = str(FIXTURES[args.offline])
        # The fixture server is on loopback, which the private-address guard
        # refuses for every real audit. This is the one place it is lifted.
        config.allow_private_hosts = True
    if args.no_external:
        config.check_external = False
    if args.user_agent:
        config.user_agent = args.user_agent
    config.use_headless_render = args.render
    if args.render_pages is not None:
        config.render_page_limit = max(0, args.render_pages)
    config.schema_variant = args.schema

    started = time.monotonic()
    try:
        bundle, report = orchestrator.run_audit(config, on_progress=progress)
    finally:
        if server is not None:
            server.shutdown()
            server.server_close()

    validation = report["diagnostics"].get("schema_validation", {})
    if not validation.get("valid", True):
        for error in validation.get("errors", [])[:10]:
            print(f"[audit] SCHEMA WARNING {error}", file=sys.stderr)

    projected = report_mod.project(report, args.schema)
    payload = report_mod.dumps(projected)
    markdown = report_mod.render_markdown(report)

    if args.out:
        out_dir = Path(args.out)
        out_dir.mkdir(parents=True, exist_ok=True)
        if args.format in ("json", "both"):
            (out_dir / "audit-report.json").write_text(payload, encoding="utf-8")
            progress(f"wrote {out_dir / 'audit-report.json'}")
        if args.format in ("markdown", "both"):
            (out_dir / "audit-report.md").write_text(markdown, encoding="utf-8")
            progress(f"wrote {out_dir / 'audit-report.md'}")
    else:
        print(markdown if args.format == "markdown" else payload)

    if args.bundle_out:
        Path(args.bundle_out).write_text(
            json.dumps(bundle, indent=2, ensure_ascii=False), encoding="utf-8")
        progress(f"wrote evidence bundle {args.bundle_out}")

    summary = report["summary"]
    progress(f"done in {time.monotonic() - started:.1f}s - {summary['total_findings']} finding(s), "
             f"score {summary['overall_score']}/100 ({summary['readiness_band']})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
