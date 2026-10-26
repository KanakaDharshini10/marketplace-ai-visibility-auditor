"""Composition: how the entrypoint skill drives the six specialists.

The orchestrator never hardcodes the specialist list. It reads
``marketplace.json``, resolves each non-entrypoint skill's declared script,
loads its ``analyze(bundle)`` function and runs it against the one shared
evidence bundle. Adding, removing or reordering a specialist is a manifest
edit; no orchestrator code changes.

A specialist that raises is isolated: the failure is recorded in
``diagnostics.skill_runs`` and the remaining specialists still run, so one
broken rule cannot take down the report.

Isolated is not the same as invisible. A failed specialist produced *no*
findings, which is a different fact from producing zero: its run record
carries ``status: "failed"``, ``findings: None`` and the error, its pillar is
reported as unmeasured rather than as clean, and the report's coverage says
so. An earlier version recorded ``findings: 0`` for a failure and the progress
line read ``entity-audit: 0 finding(s) [FAILED: ...]`` - a specialist that
crashed on the first page, presented as one that audited the site and found
nothing wrong.
"""

from __future__ import annotations

import importlib.util
import time
import traceback
from pathlib import Path
from types import ModuleType
from typing import Callable, Dict, List, Optional, Tuple

from . import discover, paths, report as report_mod
from .config import AuditConfig
from .findings import Finding


class SpecialistError(RuntimeError):
    pass


def _load_module(skill_id: str, script_path: Path) -> ModuleType:
    if not script_path.is_file():
        raise SpecialistError(f"{skill_id}: script not found at {script_path}")
    module_name = f"aiva_specialist_{skill_id.replace('-', '_')}"
    spec = importlib.util.spec_from_file_location(module_name, script_path)
    if spec is None or spec.loader is None:
        raise SpecialistError(f"{skill_id}: cannot load {script_path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    if not hasattr(module, "analyze"):
        raise SpecialistError(
            f"{skill_id}: {script_path} does not define analyze(bundle) -> list[Finding]")
    return module


def load_specialists(manifest: Optional[dict] = None,
                     root: Optional[Path] = None) -> List[Tuple[str, ModuleType]]:
    manifest = manifest or paths.load_manifest()
    root = root or paths.root()
    loaded: List[Tuple[str, ModuleType]] = []
    for entry in paths.specialist_skills(manifest):
        script = root / entry["path"] / entry.get("script", "scripts/analyze.py")
        loaded.append((entry["id"], _load_module(entry["id"], script)))
    return loaded


def specialist_pillars(manifest: Optional[dict] = None) -> Dict[str, str]:
    """``skill id -> pillar`` as the manifest declares it.

    The manifest is the one place the mapping is stated, so the report can
    say which pillar a failed specialist would have measured without any
    skill list being hardcoded here.
    """
    manifest = manifest or paths.load_manifest()
    return {entry["id"]: str(entry.get("pillar") or "")
            for entry in paths.specialist_skills(manifest)}


#: Run-record statuses. ``ok`` is the only one under which ``findings`` is a
#: count; every other status leaves it ``None``, because no number describes
#: what a specialist that never finished would have reported.
RUN_OK = "ok"
RUN_FAILED = "failed"


def run_specialists(bundle: dict, manifest: Optional[dict] = None,
                    root: Optional[Path] = None) -> Tuple[List[Finding], List[dict]]:
    """Run every specialist over the one bundle, isolating each failure.

    Each run record states the specialist, the pillar it measures, its
    ``status`` (``ok`` or ``failed``), and - only when it finished - how many
    findings it produced. A failure records the exception and a short
    traceback in the same record. The findings of every specialist that did
    finish are returned unchanged.
    """
    findings: List[Finding] = []
    runs: List[dict] = []
    pillars = specialist_pillars(manifest)
    for skill_id, module in load_specialists(manifest, root):
        started = time.monotonic()
        record: Dict[str, object] = {"skill": skill_id, "pillar": pillars.get(skill_id, ""),
                                     "status": RUN_OK, "ok": True, "findings": None}
        try:
            produced = module.analyze(bundle) or []
            for item in produced:
                if not item.source_skill:
                    item.source_skill = skill_id
            findings.extend(produced)
            record["findings"] = len(produced)
        except Exception as exc:  # noqa: BLE001 - isolate specialist failures
            record["status"] = RUN_FAILED
            record["ok"] = False
            record["findings"] = None
            record["error"] = f"{type(exc).__name__}: {exc}"
            record["traceback"] = traceback.format_exc(limit=6)
        record["elapsed_s"] = round(time.monotonic() - started, 3)
        runs.append(record)
    return findings, runs


def describe_run(run: dict) -> str:
    """One progress line per specialist that never reads a failure as a count."""
    if run.get("status", RUN_OK if run.get("ok", True) else RUN_FAILED) == RUN_OK:
        return f"{run['skill']}: {run.get('findings') or 0} finding(s) [ok]"
    pillar = run.get("pillar") or "its"
    return (f"{run['skill']}: FAILED before producing findings ({run.get('error')}); "
            f"the {pillar} pillar is not measured in this report")


def run_audit(config: AuditConfig, *, manifest: Optional[dict] = None,
              root: Optional[Path] = None,
              on_progress: Optional[Callable[[str], None]] = None) -> Tuple[dict, dict]:
    """Collect once, compose the specialists, emit one report.

    Returns ``(bundle, report)``.
    """
    manifest = manifest or paths.load_manifest()
    root = root or paths.root()
    entry = paths.entrypoint_skill(manifest)  # raises unless exactly one

    def progress(message: str) -> None:
        if on_progress:
            on_progress(message)

    progress(f"collecting shared evidence from {config.site}")
    bundle = discover.collect(config)
    stats = bundle.get("stats", {})
    progress(f"collected {stats.get('html_pages_parsed', 0)} page(s) in "
             f"{stats.get('elapsed_s', 0)}s using {stats.get('requests', 0)} request(s)")

    findings, runs = run_specialists(bundle, manifest, root)
    for run in runs:
        progress("  " + describe_run(run))
    failed = [run for run in runs if run.get("status") == RUN_FAILED]
    if failed:
        progress(f"specialist coverage is incomplete: {len(failed)} of {len(runs)} "
                 f"specialist(s) failed; the report says which pillars are unmeasured")

    progress("composing report")
    built = report_mod.build_report(bundle, findings, config, skill_runs=runs)
    built["generator"]["entrypoint_skill"] = entry["id"]
    built["generator"]["specialist_skills"] = [run["skill"] for run in runs]

    errors = report_mod.validate_report(built)
    built["diagnostics"]["schema_validation"] = {
        "schema": report_mod.SCHEMA_FILE,
        "valid": not errors,
        "errors": errors,
    }
    return bundle, built
