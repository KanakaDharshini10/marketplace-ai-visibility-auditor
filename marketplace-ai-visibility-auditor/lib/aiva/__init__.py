"""aiva - AI Visibility Audit shared runtime.

This package is the *shared evidence layer* of the
`marketplace-ai-visibility-auditor` Agent Skill Marketplace.

Design contract
---------------
1. Only the entrypoint skill performs network I/O, and it does so exactly once
   per URL (:class:`aiva.evidence.EvidenceStore` is a fetch-once cache).
2. Specialist skills are *pure functions over the evidence bundle*. They never
   fetch, never mutate a live site and never invent an observation - every
   finding they emit must cite an :class:`aiva.findings.EvidenceItem` that
   points back at a real, recorded observation.
3. Everything is read-only. GET/HEAD only, robots.txt honoured, rate limited.

Stdlib only. No third-party runtime dependency is required.
"""

from .version import __version__, TOOL_NAME  # noqa: F401

__all__ = ["__version__", "TOOL_NAME"]
