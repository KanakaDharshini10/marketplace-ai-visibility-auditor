"""robots.txt parsing with full introspection.

``urllib.robotparser`` can answer *may I fetch this?* but cannot tell us
*which rule, in which group, said so* - and that answer is exactly the
evidence an audit has to cite. So we parse it ourselves, following RFC 9309
(and Google's longest-match / allow-wins tiebreak).

The parser is used for two different jobs:

1. **Compliance** - deciding what this auditor is allowed to fetch.
2. **Diagnosis** - reporting which *AI assistant* crawlers the site blocks,
   which is invisible to classic SEO tooling but decides whether a brand can
   be cited at all.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional, Tuple
from urllib.parse import urlsplit, unquote


@dataclass
class Rule:
    allow: bool
    pattern: str
    line_no: int
    regex: "re.Pattern" = field(repr=False, default=None)

    def __post_init__(self) -> None:
        if self.regex is None:
            self.regex = compile_pattern(self.pattern)

    @property
    def specificity(self) -> int:
        # RFC 9309: the most specific (longest) pattern wins.
        return len(self.pattern.replace("*", "").replace("$", ""))

    def to_dict(self) -> dict:
        return {"type": "allow" if self.allow else "disallow",
                "pattern": self.pattern, "line": self.line_no}


@dataclass
class Group:
    agents: List[str] = field(default_factory=list)
    rules: List[Rule] = field(default_factory=list)
    crawl_delay: Optional[float] = None
    line_no: int = 0

    def to_dict(self) -> dict:
        return {"user_agents": list(self.agents), "line": self.line_no,
                "crawl_delay": self.crawl_delay,
                "rules": [r.to_dict() for r in self.rules]}


def compile_pattern(pattern: str) -> "re.Pattern":
    """Translate a robots path pattern into a regex.

    ``*`` matches any run of characters, a trailing ``$`` anchors the end.
    Everything else is literal.
    """
    anchored_end = pattern.endswith("$")
    body = pattern[:-1] if anchored_end else pattern
    out = ["^"]
    for ch in body:
        if ch == "*":
            out.append(".*")
        else:
            out.append(re.escape(ch))
    if anchored_end:
        out.append("$")
    try:
        return re.compile("".join(out))
    except re.error:  # pragma: no cover - defensive
        return re.compile("^$a")  # matches nothing


class RobotsTxt:
    """Parsed robots.txt with per-agent introspection."""

    def __init__(self) -> None:
        self.groups: List[Group] = []
        self.sitemaps: List[str] = []
        self.raw: str = ""
        self.status: int = 0
        self.url: str = ""
        self.error: Optional[str] = None
        self.parse_warnings: List[str] = []
        self.exists: bool = False
        self.unreachable: bool = False   # 5xx / network error -> assume disallow
        self.other_directives: List[Tuple[int, str, str]] = []

    # -- construction ------------------------------------------------------
    @classmethod
    def from_response(cls, url: str, status: int, body: str,
                      error: Optional[str] = None) -> "RobotsTxt":
        robots = cls()
        robots.url = url
        robots.status = status
        robots.error = error
        if error or status >= 500:
            # RFC 9309 §2.3.1.4: unreachable robots.txt => assume complete
            # disallow. We surface this as a finding rather than ignoring it.
            robots.unreachable = True
            return robots
        if status == 0 or status >= 400:
            # 4xx == "unavailable" == allowed to crawl everything.
            return robots
        robots.exists = True
        robots.raw = body or ""
        robots._parse(robots.raw)
        return robots

    @classmethod
    def allow_all(cls, url: str = "") -> "RobotsTxt":
        robots = cls()
        robots.url = url
        robots.status = 404
        return robots

    # -- parsing -----------------------------------------------------------
    def _parse(self, text: str) -> None:
        current: Optional[Group] = None
        expecting_agent = False
        for idx, raw_line in enumerate(text.splitlines(), start=1):
            line = raw_line.split("#", 1)[0].strip()
            if not line:
                continue
            if ":" not in line:
                self.parse_warnings.append(f"line {idx}: no ':' separator -> ignored")
                continue
            field_name, _, value = line.partition(":")
            key = field_name.strip().lower()
            value = value.strip()

            if key in ("user-agent", "useragent"):
                if current is None or not expecting_agent:
                    current = Group(line_no=idx)
                    self.groups.append(current)
                    expecting_agent = True
                current.agents.append(value)
                continue

            expecting_agent = False
            if key in ("allow", "disallow"):
                if current is None:
                    self.parse_warnings.append(
                        f"line {idx}: '{field_name.strip()}' before any User-agent -> ignored")
                    continue
                if value == "":
                    # An empty ``Disallow:`` means "allow everything" and
                    # contributes no rule. An empty ``Allow:`` is undefined in
                    # RFC 9309; keeping it would build a zero-length pattern
                    # that matches every path and could then be cited as the
                    # deciding rule ("allow: ''"), which is not evidence.
                    continue
                if not value.startswith("/") and value != "*":
                    self.parse_warnings.append(
                        f"line {idx}: path '{value}' does not start with '/'")
                current.rules.append(Rule(allow=(key == "allow"), pattern=value, line_no=idx))
            elif key == "sitemap":
                if value:
                    self.sitemaps.append(value)
            elif key in ("crawl-delay", "crawldelay"):
                if current is not None:
                    try:
                        current.crawl_delay = float(value)
                    except ValueError:
                        self.parse_warnings.append(
                            f"line {idx}: non-numeric Crawl-delay '{value}'")
            else:
                self.other_directives.append((idx, key, value))

    # -- querying ----------------------------------------------------------
    @staticmethod
    def _merge(groups: List[Group]) -> Optional[Group]:
        """Combine records that name the same product token (RFC 9309 §2.2.1).

        A robots.txt may repeat a user-agent in several records; a crawler has
        to treat their rules as one group. Returning only the first record
        silently drops the others - and the failure direction is "fetch
        something the site disallowed", so this is a compliance bug, not a
        cosmetic one.
        """
        if not groups:
            return None
        if len(groups) == 1:
            return groups[0]
        merged = Group(line_no=groups[0].line_no)
        seen_agents: List[str] = []
        delays = []
        for group in groups:
            for agent in group.agents:
                if agent not in seen_agents:
                    seen_agents.append(agent)
            merged.rules.extend(group.rules)
            if group.crawl_delay is not None:
                delays.append(group.crawl_delay)
        merged.agents = seen_agents
        # The politest declared delay wins, so merging can never speed us up.
        merged.crawl_delay = max(delays) if delays else None
        return merged

    def group_for(self, agent: str) -> Optional[Group]:
        """Longest matching product token wins; ``*`` is the fallback.

        Matching is a case-insensitive *prefix* test on the product token, as
        RFC 9309 §2.2.1 specifies. It is deliberately not a substring test: a
        site whose robots.txt says ``User-agent: bot`` is naming one crawler,
        not every crawler whose name happens to contain those three letters.
        """
        token = (agent or "*").lower()
        best_len = -1
        best: List[Group] = []
        wildcard: List[Group] = []
        for group in self.groups:
            group_best = -1
            is_wildcard = False
            for declared in group.agents:
                dl = declared.strip().lower()
                if dl == "*":
                    is_wildcard = True
                    continue
                if not dl:
                    continue
                if token == dl or token.startswith(dl):
                    group_best = max(group_best, len(dl))
            if is_wildcard:
                wildcard.append(group)
            if group_best < 0:
                continue
            if group_best > best_len:
                best_len, best = group_best, [group]
            elif group_best == best_len:
                best.append(group)
        return self._merge(best) or self._merge(wildcard)

    def decision(self, agent: str, url_or_path: str) -> Tuple[bool, Optional[Rule], Optional[Group]]:
        """Return ``(allowed, deciding_rule, group)``."""
        if self.unreachable:
            return False, None, None
        path = url_or_path
        if "://" in path:
            parts = urlsplit(path)
            path = parts.path or "/"
            if parts.query:
                path += "?" + parts.query
        if not path:
            path = "/"
        decoded = unquote(path)

        group = self.group_for(agent)
        if group is None or not group.rules:
            return True, None, group

        winner: Optional[Rule] = None
        for rule in group.rules:
            if rule.regex.match(path) or rule.regex.match(decoded):
                if winner is None:
                    winner = rule
                elif rule.specificity > winner.specificity:
                    winner = rule
                elif rule.specificity == winner.specificity and rule.allow and not winner.allow:
                    winner = rule  # allow wins ties
        if winner is None:
            return True, None, group
        return winner.allow, winner, group

    def can_fetch(self, agent: str, url_or_path: str) -> bool:
        return self.decision(agent, url_or_path)[0]

    def crawl_delay_for(self, agent: str) -> Optional[float]:
        group = self.group_for(agent)
        return group.crawl_delay if group else None

    def blocks_everything_for(self, agent: str) -> bool:
        allowed, rule, _ = self.decision(agent, "/")
        return (not allowed) and rule is not None and rule.pattern in ("/", "/*")

    def agent_summary(self, agent: str) -> dict:
        """Compact, quotable evidence for one crawler token."""
        allowed_root, rule_root, group = self.decision(agent, "/")
        return {
            "agent": agent,
            "matched_group_line": group.line_no if group else None,
            "matched_group_agents": list(group.agents) if group else [],
            "root_allowed": allowed_root,
            "deciding_rule": rule_root.to_dict() if rule_root else None,
            "crawl_delay": group.crawl_delay if group else None,
            "blocks_site": self.blocks_everything_for(agent),
        }

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "status": self.status,
            "exists": self.exists,
            "unreachable": self.unreachable,
            "error": self.error,
            "bytes": len(self.raw),
            # Kept so specialist skills can re-derive per-path decisions from
            # the bundle without re-fetching anything.
            "raw": self.raw[:20000],
            "sitemaps": list(self.sitemaps),
            "groups": [g.to_dict() for g in self.groups],
            "parse_warnings": list(self.parse_warnings),
            "unknown_directives": [
                {"line": ln, "field": f, "value": v} for ln, f, v in self.other_directives
            ],
        }
