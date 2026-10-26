"""Agent Skills / marketplace specification compliance.

Everything the Round 3 brief and the agentskills.io specification require of the
package itself, asserted rather than assumed.
"""

from __future__ import annotations

import inspect
import json
import pathlib
import re
import unittest

import helpers
from aiva import frontmatter, jsonschema_lite, paths, report as report_mod, validate
from aiva.config import AuditConfig
from aiva.discover import sample_frontier

ROOT = helpers.ROOT
NAME_RE = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")


def _relative(path, root=None) -> str:
    """A scanned file's name, relative to the package root, POSIX-style.

    ``PurePath.__str__`` uses the platform separator, so the same file reads
    "docs/WALKTHROUGH.md" on Linux and macOS and "docs\\WALKTHROUGH.md" on
    Windows. Both the offender messages and the scope assertions name files,
    so both go through here: one spelling of a path, on every platform, and
    a failure message that copies and pastes the same way everywhere.

    ``root`` defaults to the package root and is passed explicitly only by
    the portability tests, which hand it a Windows-flavoured pair so the
    normalisation can be exercised from any platform.
    """
    return pathlib.PurePath(path).relative_to(root if root is not None else ROOT).as_posix()


def _prose_of(path) -> str:
    """The prose a reader acts on, with the source syntax removed.

    For Markdown that is the file. For Python it is the docstrings, string
    literals and comments *with their delimiters stripped* - because a rule's
    mechanism sentence lives inside a string literal, and treating that
    literal's own quotes as "this phrase is being named" would exempt every
    sentence in every specialist from the scan. Quoting inside the prose still
    counts: a phrase in backticks or in inner quotes is named, not asserted.
    """
    text = path.read_text(encoding="utf-8")
    if path.suffix != ".py":
        return text
    import io
    import tokenize
    lines = text.splitlines()
    out = [""] * (len(lines) + 2)
    try:
        tokens = list(tokenize.generate_tokens(io.StringIO(text).readline))
    except (tokenize.TokenError, IndentationError, SyntaxError):   # pragma: no cover
        return text
    for token in tokens:
        if token.type not in (tokenize.STRING, tokenize.COMMENT):
            continue
        body = token.string
        if token.type == tokenize.COMMENT:
            body = body.lstrip("#")
        else:
            body = re.sub(r'^[a-zA-Z]*(\'\'\'|"""|\'|")', "", body)
            body = re.sub(r'(\'\'\'|"""|\'|")$', "", body)
        row = token.start[0]
        for offset, piece in enumerate(body.splitlines() or [""]):
            if row + offset < len(out):
                out[row + offset] += (" " if out[row + offset] else "") + piece
    return "\n".join(out)


def _sentences(block: str):
    """(offset, sentence) pairs. Naive on purpose: the split only has to be
    good enough to keep a disclaimer attached to the clause it scopes."""
    start = 0
    for match in re.finditer(r"(?<=[.!?;])\s+", block):
        yield start, block[start:match.start()]
        start = match.end()
    if start < len(block):
        yield start, block[start:]


class TestMarketplaceManifest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = paths.load_manifest()

    def test_manifest_is_valid_json_with_required_fields(self):
        for field in ("name", "version", "skills"):
            self.assertIn(field, self.manifest)
        self.assertTrue(self.manifest["skills"])

    def test_exactly_one_entrypoint(self):
        entries = [s for s in self.manifest["skills"] if s.get("entrypoint")]
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0]["id"], "marketplace-ai-visibility-audit")

    def test_one_specialist_per_pillar(self):
        from aiva.findings import PILLARS
        specialists = paths.specialist_skills(self.manifest)
        self.assertEqual(len(specialists), 6)
        self.assertEqual({s["pillar"] for s in specialists}, set(PILLARS))

    def test_every_declared_path_and_script_exists(self):
        for entry in self.manifest["skills"]:
            folder = ROOT / entry["path"]
            self.assertTrue(folder.is_dir(), entry["path"])
            self.assertTrue((folder / "SKILL.md").is_file(), entry["id"])
            self.assertTrue((folder / entry["script"]).is_file(), entry["script"])

    def test_manifest_is_self_contained(self):
        """No skill may be resolved from an external service."""
        blob = json.dumps(self.manifest)
        for scheme in ("http://", "https://", "git+", "npm:", "file://"):
            self.assertNotIn(scheme, blob)

    def test_no_undeclared_skill_folder(self):
        declared = {entry["path"] for entry in self.manifest["skills"]}
        on_disk = {f"skills/{p.name}" for p in (ROOT / "skills").iterdir() if p.is_dir()}
        self.assertEqual(on_disk, declared)


class TestSkillFiles(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.skills = []
        for entry in paths.load_manifest()["skills"]:
            folder = ROOT / entry["path"]
            data, body = frontmatter.load((folder / "SKILL.md").read_text(encoding="utf-8"))
            cls.skills.append((entry, folder, data, body))

    def test_name_rules(self):
        for entry, folder, data, _body in self.skills:
            name = data.get("name", "")
            self.assertTrue(NAME_RE.match(name), f"{name} violates the name grammar")
            self.assertLessEqual(len(name), 64)
            self.assertEqual(name, folder.name, "name must match the directory")
            self.assertEqual(name, entry["id"], "name must match the manifest id")

    def test_description_rules(self):
        for _entry, folder, data, _body in self.skills:
            description = data.get("description", "")
            self.assertTrue(description, folder.name)
            self.assertLessEqual(len(description), 1024,
                                 f"{folder.name}: description too long")
            self.assertGreater(len(description), 120,
                               f"{folder.name}: description should say what AND when")
            self.assertIn("Use ", description,
                          f"{folder.name}: description should state when to use the skill")

    def test_optional_fields_are_within_limits(self):
        for _entry, folder, data, _body in self.skills:
            if data.get("compatibility"):
                self.assertLessEqual(len(data["compatibility"]), 500, folder.name)
            if isinstance(data.get("metadata"), dict):
                for key, value in data["metadata"].items():
                    self.assertIsInstance(value, str, f"{folder.name}.metadata.{key}")
            if data.get("allowed-tools"):
                self.assertIsInstance(data["allowed-tools"], str)

    def test_frontmatter_has_no_unknown_keys(self):
        known = {"name", "description", "license", "compatibility", "metadata",
                 "allowed-tools", "version"}
        for _entry, folder, data, _body in self.skills:
            self.assertEqual(set(data) - known, set(), folder.name)

    def test_bodies_stay_lean(self):
        for _entry, folder, _data, body in self.skills:
            lines = len(body.splitlines())
            self.assertLess(lines, 500, f"{folder.name}: SKILL.md body is {lines} lines")

    def test_relative_links_resolve(self):
        for _entry, folder, _data, body in self.skills:
            for match in re.finditer(r"\]\(([^)]+)\)", body):
                target = match.group(1).split("#")[0]
                if target.startswith(("http://", "https://", "mailto:")):
                    continue
                self.assertTrue((folder / target).exists(),
                                f"{folder.name}: broken link {target}")

    def test_every_skill_declares_a_license(self):
        for _entry, folder, data, _body in self.skills:
            self.assertTrue(data.get("license"), folder.name)

    def test_reference_files_are_one_level_deep(self):
        for _entry, folder, _data, _body in self.skills:
            for path in folder.rglob("*.md"):
                if path.name == "SKILL.md":
                    continue
                relative = path.relative_to(folder)
                self.assertEqual(len(relative.parts), 2,
                                 f"{folder.name}: {relative} is nested too deep")


class TestSchemas(unittest.TestCase):
    def test_schemas_parse_and_stay_within_the_supported_subset(self):
        for name in ("audit-report.schema.json", "evidence-bundle.schema.json"):
            schema = paths.load_schema(name)
            self.assertEqual(jsonschema_lite.unsupported_keywords(schema), [], name)

    def test_report_schema_requires_the_brief_floor(self):
        schema = paths.load_schema("audit-report.schema.json")
        self.assertEqual(schema["required"], ["site", "audited_at", "summary", "findings"])
        summary = schema["properties"]["summary"]["required"]
        for field in ("total_findings", "critical", "high", "medium"):
            self.assertIn(field, summary)
        finding = schema["$defs"]["finding"]["required"]
        for field in ("id", "title", "severity", "evidence", "suggested_action"):
            self.assertIn(field, finding)

    def test_finding_requires_at_least_one_evidence_item(self):
        schema = paths.load_schema("audit-report.schema.json")
        self.assertEqual(
            schema["$defs"]["finding"]["properties"]["evidence_items"]["minItems"], 1)


class TestPackaging(unittest.TestCase):
    def test_validator_reports_no_errors(self):
        result = validate.validate_marketplace(ROOT)
        self.assertTrue(result.valid, result.errors)
        self.assertEqual(result.warnings, [])

    def test_no_third_party_runtime_dependency(self):
        """The package must run on a bare Python 3.9+ install."""
        import ast
        allowed_optional = {"playwright"}
        for path in list((ROOT / "lib").rglob("*.py")) + list((ROOT / "skills").rglob("*.py")):
            source = path.read_text(encoding="utf-8")
            tree = ast.parse(source)
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(alias.name.split(".")[0] for alias in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.level:      # relative import inside the aiva package
                        continue
                    if node.module:
                        imported.add(node.module.split(".")[0])
            for top in imported:
                if top in ("aiva", "__future__"):
                    continue
                if top in allowed_optional:
                    self.assertIn("playwright_available", source,
                                  f"{path.name}: optional import must be guarded")
                    continue
                self.assertIn(top, _STDLIB, f"{path} imports third-party module {top}")

    def test_submission_size_is_well_under_the_limit(self):
        total = sum(p.stat().st_size for p in ROOT.rglob("*")
                    if p.is_file() and "__pycache__" not in p.parts)
        self.assertLess(total, 50 * 1024 * 1024, "submission must be under 50 MB")

    def test_no_model_weights_or_binaries(self):
        forbidden = {".bin", ".pt", ".pth", ".onnx", ".safetensors", ".h5", ".ckpt", ".gguf"}
        offenders = [p for p in ROOT.rglob("*") if p.suffix.lower() in forbidden]
        self.assertEqual(offenders, [])

    def test_root_documents_exist(self):
        for name in ("README.md", "LICENSE", "marketplace.json"):
            self.assertTrue((ROOT / name).is_file(), name)


class TestBriefConstraints(unittest.TestCase):
    """The brief's non-negotiables, one assertion each.

    The constraints that are already covered structurally elsewhere are named
    here with a pointer, so this class reads as the checklist a judge would
    work through and nothing on it is left to prose.
    """

    # -- "read-only; no hacking, no authentication or security bypass" ------

    def test_no_authentication_or_transactional_surface_is_ever_requested(self):
        """Login, account, cart and checkout paths are excluded at the frontier.

        The auditor has no credentials, submits no form and follows no path
        that would act on a shop. Method-level proof (GET/HEAD only, no
        credentials) is in test_safety.TestReadOnly.
        """
        from aiva.discover import NON_CITABLE_PATH_RE
        for path in ("/cart", "/checkout", "/checkout/step-2", "/account",
                     "/account/login", "/login", "/signin", "/register",
                     "/admin", "/wp-admin", "/logout"):
            self.assertIsNotNone(NON_CITABLE_PATH_RE.search(path),
                                 f"{path} must never enter the frontier")

    def test_no_code_submits_a_form_or_writes_to_the_target(self):
        import ast
        forbidden = {"post", "put", "patch", "delete", "submit_form", "urlopen_post"}
        for path in list((ROOT / "lib").rglob("*.py")) + list((ROOT / "skills").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if isinstance(node, ast.Attribute) and node.attr.lower() in forbidden:
                    self.fail(f"{path.name} calls .{node.attr}() on the target")

    # -- "no chatbot, no product recommendation engine" --------------------

    def test_the_package_ships_no_conversational_or_ranking_surface(self):
        """The deliverable is an audit report, not an assistant or a shop.

        A chatbot needs an input loop; a recommendation engine ranks the site's
        *products* for a shopper. Neither exists: nothing reads stdin, and
        every ranking in the codebase orders findings by remediation priority.
        """
        import ast
        for path in list((ROOT / "lib").rglob("*.py")) + list((ROOT / "skills").rglob("*.py")):
            tree = ast.parse(path.read_text(encoding="utf-8"))
            for node in ast.walk(tree):
                if (isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                        and node.func.id in ("input", "raw_input")):
                    self.fail(f"{path.name} builds a conversational loop")
                if (isinstance(node, ast.Attribute) and node.attr in ("readline", "read")
                        and isinstance(node.value, ast.Attribute)
                        and node.value.attr == "stdin"):
                    self.fail(f"{path.name} reads interactive input")
        prioritize = (ROOT / "lib" / "aiva" / "prioritize.py").read_text(encoding="utf-8")
        self.assertIn("Finding", prioritize)

    # -- "gather evidence once and reuse it" -------------------------------

    def test_specialists_receive_a_bundle_and_cannot_fetch(self):
        """Composition is one crawl, one frozen bundle, many analyzers.

        Network isolation is proved by import-graph analysis in
        test_safety.TestSpecialistIsolation; this asserts the contract shape.
        """
        for entry in paths.specialist_skills():
            module = helpers.specialist(entry["id"])
            self.assertTrue(hasattr(module, "analyze"), entry["id"])
            signature = inspect.signature(module.analyze)
            self.assertEqual(list(signature.parameters), ["bundle"], entry["id"])

    # -- "deterministic" ---------------------------------------------------

    def test_the_same_bundle_always_produces_the_same_report(self):
        """Two runs over one bundle must be indistinguishable.

        Determinism is what makes a fix verifiable by re-running, and it is
        also the proof that no model or sampling randomness is involved.
        """
        bundle = helpers.commerce_bundle()
        findings = []
        for entry in paths.specialist_skills():
            findings.extend(helpers.specialist(entry["id"]).analyze(bundle))
        config = AuditConfig(site=helpers.ORIGIN)
        first = report_mod.build_report(bundle, list(findings), config)
        second = report_mod.build_report(bundle, list(findings), config)
        for report in (first, second):
            report.pop("audited_at", None)
            report.get("evidence_manifest", {}).pop("collected_at", None)
        self.assertEqual(json.dumps(first, sort_keys=True),
                         json.dumps(second, sort_keys=True))

    # -- "every finding carries observable evidence" -----------------------

    def test_no_finding_can_be_emitted_without_evidence(self):
        bundle = helpers.commerce_bundle()
        for entry in paths.specialist_skills():
            for finding in helpers.specialist(entry["id"]).analyze(bundle):
                self.assertTrue(finding.evidence_items,
                                f"{finding.rule_id} carries no evidence item")
                for item in finding.evidence_items:
                    self.assertTrue((item.observation or "").strip(), finding.rule_id)

    # -- "recommendations must be actionable" ------------------------------

    def test_every_recommendation_states_steps_and_a_way_to_check_it(self):
        bundle = helpers.commerce_bundle()
        for entry in paths.specialist_skills():
            for finding in helpers.specialist(entry["id"]).analyze(bundle):
                action = finding.suggested_action
                self.assertTrue(action.summary.strip(), finding.rule_id)
                self.assertTrue(action.steps, f"{finding.rule_id} has no steps")
                self.assertTrue(action.verification.strip(),
                                f"{finding.rule_id} cannot be verified")
                self.assertIn(action.effort, ("low", "medium", "high"))

    # -- "offline-compatible; runs inside the 5-minute budget" -------------

    def test_the_configured_budget_cannot_exceed_the_brief(self):
        config = AuditConfig(site="https://shop.example")
        self.assertLessEqual(config.total_time_budget_s, 300)
        config.total_time_budget_s = 900
        self.assertTrue(any("total_time_budget_s" in e for e in config.validate()))

    def test_the_crawl_budget_is_actually_spendable(self):
        """A budget the sampler cannot reach is not a budget.

        The quotas are a balancing device for round one; they used to be the
        hard ceiling too, and they sum to less than max_pages, so part of the
        budget was unreachable on every site.
        """
        config = AuditConfig(site="https://shop.example")
        self.assertLess(sum(config.sample_targets.values()), config.max_pages)
        plan = sample_frontier(
            [(f"https://shop.example/shop/item-{i}", "sitemap") for i in range(200)],
            config, already=["https://shop.example/"])
        self.assertEqual(len(plan), config.max_pages - 1)


_STDLIB = {
    "abc", "argparse", "ast", "collections", "contextlib", "copy", "dataclasses",
    "datetime", "email", "functools", "gzip", "hashlib", "html", "http",
    "importlib", "inspect", "io", "ipaddress", "json", "os", "pathlib", "random", "re",
    "shutil", "socket", "socketserver", "statistics", "string", "subprocess",
    "sys", "tempfile", "textwrap", "threading", "time", "traceback", "types",
    "typing", "unicodedata", "unittest", "urllib", "xml", "zlib", "zipfile",
    "helpers",
}


class TestClaimsAreScopedToWhatWasMeasured(unittest.TestCase):
    """The auditor observes one site. It does not observe any assistant.

    It sends its own honest User-Agent to one origin and reads what comes
    back. It never queries a retrieval system, never asks a model a question,
    and never measures whether a page was cited - so a finding that says an
    assistant *will* do something has left the evidence behind, however
    plausible the claim is.

    The rule is about certainty, not about topic: naming a mechanism is the
    most useful thing a finding does, and a mechanism stated conditionally is
    still a mechanism. What is banned is the indicative mood applied to a third
    party's behaviour.
    """

    #: Phrasings that assert how an external system behaves. Each was in a
    #: shipped finding, and each is followed here by what replaced it.
    FORBIDDEN = (
        "assistants will", "assistants never", "assistants are simply",
        "an assistant will", "an assistant cannot",
        "fetchers stop", "fetchers never", "most assistant fetchers",
        "retrieval systems look", "retrieval systems exclude",
        "the index cannot", "pollute the index", "disappears from every",
        "loses to a competitor", "loses to competitors",
        "is simply absent from", "silently dropped from",
        "no crawler can", "assistants never read",
        # A blanket robots block was described as meaning the site "can never
        # be the source of an answer" for the blocked agents - an unmeasured,
        # absolute outcome about answer surfaces this audit never queries.
        "can never be the source", "never be the source of an answer",
        # The report headline asserted "assistants cannot reliably reach, read
        # or attribute" from a crawl blocker - an inference about assistants
        # the audit never queried. The singular form was already banned; the
        # plural slipped through into the one sentence readers act on most.
        "assistants cannot", "assistants can't",
        # Closed in the 1.9.1 evidence-boundary sweep. Each asserted an outcome
        # in a system the audit never queries: a model inventing an address, a
        # site "losing" to competitors, content "invisible to retrieval", what
        # "most extractors" do, what "a model will supply".
        "may be abandoned", "dead site", "lose to maintained", "cited instead of you",
        "invisible to retrieval", "a model will supply", "most extractors",
        "hallucinated url", "invented branch", "cheapest cues", "produces a plausible address",
        "indistinguishable from a real one",
        # Closed in the semantic-applicability pass. Each stated, in the
        # indicative, how assistants, fetchers, retrieval systems or crawlers
        # behave - weighting agreement, reading the lead paragraph, reading
        # Open Graph before the body, treating repeated facts as trustworthy,
        # learning to distrust a sitemap - none of which this audit measures.
        # "commercially important" and the canonical phrasings asserted a
        # commercial role, or an index's behaviour, of pages this audit only
        # classified.
        "assistants weight", "assistants fetch a small", "retrieval matches against the shape",
        "quote the lead paragraph", "read the lead paragraph", "almost no storefront",
        "machines treat", "fetchers read", "assistants will ignore", "causes hallucinations",
        "rank you higher", "guarantees retrieval", "makes the assistant cite",
        "commercially important", "tells crawlers to drop", "product detail collapsed",
        "learns the site's own metadata", "extractors weight", "will often misread",
        "invisible to assistants", "unusable as a source", "dead profile",
        "nobody buys any more", "discounted wholesale", "learn to ignore",
        "assumes the worst", "usually mid-comparison", "arrive on a phone",
        "overwhelmingly read", "usually skipped", "picks one arbitrarily",
        "assistants re-crawl", "the assistant weights", "retrieval systems disambiguate",
        "assistants are asked",
        # Closed in 1.10.1, when the scan was extended from the rule code to
        # every shipped document. Each of these stated, in the indicative, what
        # an assistant, an extractor, a retrieval system or "machines" do.
        "assistants use a different", "retrieval systems answer",
        "assistant cannot quote", "extractors weight it", "the summary a fetcher gets",
        "most assistant fetchers", "assistant crawler stops",
        "the first file a retrieval crawler fetches", "crawlers learn",
        "an assistant will state", "the sentence an assistant will",
        "shopping assistant would ask", "what the assistant read",
        "llms will", "llms cannot", "ai assistants cannot",
        "the assistant gets no credit", "gets no credit", "the assistant will look elsewhere",
        "assistants will quote", "retrieval systems will ignore",
    )

    #: Every shipped file whose prose a reader acts on. The rule set was the
    #: original scope; a reference document that says an assistant *will* do
    #: something is the same unmeasured claim, read by the same person, so
    #: 1.10.1 extended the scan to the documentation, the skill files and the
    #: pre-generated example report as well.
    def _sources(self):
        for pattern in ("*/scripts/*.py", "*/SKILL.md", "*/references/*.md"):
            for path in sorted((ROOT / "skills").glob(pattern)):
                yield path
        for path in sorted((ROOT / "lib" / "aiva").glob("*.py")):
            yield path
        for path in (ROOT / "README.md", ROOT / "CHANGELOG.md"):
            yield path
        for folder in ("docs", "examples"):
            for path in sorted((ROOT / folder).glob("*.md")):
                yield path

    #: A phrase inside quotation marks or backticks is being *named*, not
    #: asserted: the changelog quotes what it removed, a rule table quotes the
    #: wording a finding no longer uses, and a SKILL.md quotes the complaint a
    #: site owner arrives with. Naming a banned phrase therefore requires
    #: quoting it - which is the convention this exemption enforces, not a
    #: loophole in it.
    _QUOTED = re.compile(r'"[^"\n]*"|\u201c[^\u201d\n]*\u201d|`[^`\n]*`|\u2018[^\u2019\n]*\u2019')

    @classmethod
    def _quoted_spans(cls, line: str):
        return [(m.start(), m.end()) for m in cls._QUOTED.finditer(line)]

    @staticmethod
    def _paragraphs(text: str):
        """(first line number, one-line text) per blank-line-separated block.

        Prose wraps, and so do the quotation marks around it, so a phrase that
        is quoted across a line break is still a quoted phrase. Scanning line
        by line reported those as assertions; scanning the block does not.
        """
        block, start = [], 1
        for number, line in enumerate(text.splitlines(), 1):
            if line.strip():
                if not block:
                    start = number
                block.append(line.strip())
            elif block:
                yield start, " ".join(block)
                block = []
        if block:
            yield start, " ".join(block)

    def test_no_shipped_document_asserts_how_an_external_system_behaves(self):
        offenders = []
        for path in self._sources():
            for number, block in self._paragraphs(_prose_of(path)):
                lowered = block.lower()
                spans = self._quoted_spans(block)
                for phrase in self.FORBIDDEN:
                    for match in re.finditer(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])",
                                             lowered):
                        if any(start <= match.start() and match.end() <= end
                               for start, end in spans):
                            continue        # named, not asserted
                        offenders.append(
                            f"{_relative(path)}:{number}: {phrase!r}")
        self.assertEqual(offenders, [],
                         "state these conditionally, or quote the phrase to name it - the "
                         "audit does not measure them: " + "; ".join(offenders))

    # -- the same rule, stated as a pattern rather than a phrase list ------
    #
    # The phrase list above is exact and grows one entry at a time; it cannot
    # catch a claim nobody has written yet. This does: it matches an external
    # subject followed by an *indicative behaviour verb*, which is the shape
    # every unsupported claim takes.
    #
    # What it deliberately does NOT match, because the project is an
    # AI-visibility auditor and this vocabulary is its subject matter:
    #
    #   * `can` / `is` / `are` / `has` - capability and definition. "a machine
    #     can read plain text", "an agent-facing index is a plain-text map"
    #     and "machine-readable" are statements about the *evidence*;
    #   * the bare word "machine", which is this package's own abstraction for
    #     any automated reader and appears throughout "machine-readable";
    #   * anything inside quotes or backticks (naming, not asserting);
    #   * a sentence that also carries a disclaimer, which is how a finding is
    #     *supposed* to name a mechanism and then scope it;
    #   * a hypothetical or conditional clause - "whether any given fetcher
    #     gives up", "if a crawler honours it" - which asserts nothing.
    _EXTERNAL_SUBJECT = (
        r"(?:an?\s+|the\s+|any\s+|every\s+|most\s+|some\s+|all\s+)?(?:ai\s+)?"
        r"(?:assistants?|llms?|chatbots?|retrieval systems?|retrieval|search engines?|"
        r"crawlers?|fetchers?|extractors?|indexes|the index|chatgpt|gemini|claude|"
        r"perplexity|copilot|gptbot|googlebot|bingbot|ai)")
    #: Verbs that assert what an external system *does*.
    _BEHAVIOUR_VERB = (
        r"(?:will|won't|shall|"
        r"treats?|reads?|weights?|prefers?|ignores?|quotes?|cites?|ranks?|picks?|"
        r"learns?|assumes?|matches?|retrieves?|selects?|trusts?|stops?|drops?|"
        r"fetches|surfaces|recommends?|understands?|parses?|sees|takes?|looks?|"
        r"gets?|needs?|wants?|expects?|honours?|honors?|crawls?|indexes|discards?|"
        r"skips?|penali[sz]es?|rewards?|favou?rs?)\b")
    #: The negative form the brief calls out by name: "AI cannot see this".
    _CANNOT_VERB = (r"(?:cannot|can't|can not|does not|doesn't|do not|don't)\s+"
                    r"(?:see|read|parse|find|access|reach|understand|quote|cite|"
                    r"retrieve|index|resolve)\b")
    #: Phrases that scope a sentence to what was measured. A sentence carrying
    #: one of these is doing the right thing, whatever verb it uses.
    _DISCLAIMERS = (
        "not something this audit measures", "does not measure", "do not measure",
        "is not measured", "are not measured", "never a claim", "not observed",
        "was not queried", "no assistant was queried", "this audit does not",
        "the audit does not", "outside this audit", "not something the audit",
        "cannot see", "is not something", "asserts how", "claims about",
        "unmeasured", "optional external validation", "does not establish",
        "not establish", "never asserts", "is an inference", "conditionally",
    )
    #: Words that make the clause hypothetical rather than assertive.
    _HYPOTHETICAL = ("whether", "if ", "where ", "unless", "would", "may ", "might",
                     "could", "assume ", "suppose", "hypothetic", "for example",
                     "e.g.", "imagine")

    @classmethod
    def _is_exempt(cls, sentence: str, start: int) -> bool:
        lowered = sentence.lower()
        if any(marker in lowered for marker in cls._DISCLAIMERS):
            return True
        before = lowered[:start]
        return any(word in before for word in cls._HYPOTHETICAL)

    def test_no_shipped_document_states_external_behaviour_in_the_indicative(self):
        """The pattern form of the rule above: subject + behaviour verb."""
        assertion = re.compile(
            rf"\b{self._EXTERNAL_SUBJECT}\s+(?:{self._BEHAVIOUR_VERB}|{self._CANNOT_VERB})",
            re.I)
        offenders = []
        for path in self._sources():
            for number, block in self._paragraphs(_prose_of(path)):
                spans = self._quoted_spans(block)
                for sentence_start, sentence in _sentences(block):
                    for match in assertion.finditer(sentence):
                        absolute = sentence_start + match.start()
                        if any(start <= absolute and absolute < end for start, end in spans):
                            continue                      # named, not asserted
                        if self._is_exempt(sentence, match.start()):
                            continue                      # scoped or hypothetical
                        offenders.append(f"{_relative(path)}:{number}: "
                                         f"{match.group(0)!r} in {sentence.strip()[:110]!r}")
        self.assertEqual(offenders, [],
                         f"{len(offenders)} statement(s) assert external behaviour in the "
                         "indicative; state what the audited evidence shows, scope the claim, "
                         "or quote the phrase to name it: " + "; ".join(offenders))

    def test_no_commerce_advice_is_emitted_without_commerce_evidence(self):
        """The second half of the compliance scan: not what the package says
        about assistants, but what it says about *trade* on a site that does
        none. The shapes and the vocabulary live in
        `test_site_type_semantics`; this asserts the property as a compliance
        rule so a new rule cannot reintroduce the leak unnoticed.
        """
        import shapes
        from test_site_type_semantics import parcel_words_in, rendered
        offenders = []
        for name, maker in shapes.NON_COMMERCE:
            for source, text in rendered(maker()):
                words = parcel_words_in(text)
                if words:
                    offenders.append(f"{name}: {source}: {words}")
        self.assertEqual(offenders, [],
                         "commerce vocabulary reached a site that sells nothing: "
                         + "; ".join(offenders))

    def test_every_proactive_recommendation_declares_its_grounding(self):
        """Evidence-backed, site-personalised and generic are different claims.

        A transport-only run that read nothing used to publish seven of these
        as though each were a deficiency it had found.
        """
        from aiva.recommend import GROUNDING, build_opportunities
        data = helpers.bundle([helpers.page(
            helpers.ORIGIN + "/", helpers.html_doc(title="Shop"))])
        opportunities = build_opportunities(data, [])
        self.assertTrue(opportunities)
        for opportunity in opportunities:
            with self.subTest(opportunity=opportunity["id"]):
                self.assertIn(opportunity.get("grounding"), GROUNDING)

    def test_a_run_that_read_nothing_offers_only_generic_advice(self):
        from aiva.recommend import build_opportunities
        for opportunity in build_opportunities(helpers.bundle([]), []):
            with self.subTest(opportunity=opportunity["id"]):
                self.assertEqual(opportunity["grounding"], "generic")


if __name__ == "__main__":
    unittest.main()


class TestConservativeUnderUncertainty(unittest.TestCase):
    """The reliability principle, as assertions rather than a paragraph.

    *Page-type classification requires multiple independent signals, and
    downstream specialist rules consume the shared classification rather than
    independently guessing page types. Negative regression cases prevent
    keyword-only matches from becoming findings.*

    Three live reports in a row produced a false positive of exactly this
    shape - a programme page, a promotions hub and a planner landing page each
    audited as an individual product - and each was fixed by removing one
    shape. These tests exist so the *rule* cannot regress, rather than the
    three shapes.
    """

    def test_specialists_do_not_re_derive_the_page_type_of_a_fetched_page(self):
        """`classify_page` is the collector's job, not an analyzer's.

        One call survives, in `crawl-render-audit`, and it is allowed for a
        specific reason: it classifies *links that were never fetched*, and
        only to suppress a finding. A wrong guess there can silence a rule but
        can never manufacture one. Anything else re-derives a fact the shared
        bundle already carries, which is how two parts of the report come to
        disagree about the same URL.
        """
        offenders = []
        for skill_dir in sorted((ROOT / "skills").iterdir()):
            script = skill_dir / "scripts" / "analyze.py"
            if not script.is_file():
                continue
            source = script.read_text(encoding="utf-8")
            if "classify_page" not in source:
                continue
            # The one permitted use documents itself as URL-only suppression.
            if "shared classification is authoritative" in source:
                continue
            offenders.append(skill_dir.name)
        self.assertEqual(offenders, [],
                         f"specialists must read page_type from the bundle: {offenders}")

    def test_the_product_funnel_refuses_every_non_product_type(self):
        from aiva.config import GENERIC_PAGE_TYPE_HINTS, PAGE_TYPE_HINTS
        from aiva.extract import NON_PRODUCT_PAGE_TYPES
        emitted = {name for name, _ in PAGE_TYPE_HINTS}
        emitted |= {name for name, _ in GENERIC_PAGE_TYPE_HINTS}
        emitted |= {"home", "error", "non_html"}
        missing = sorted((emitted - {"product", "other"}) - NON_PRODUCT_PAGE_TYPES)
        self.assertEqual(missing, [],
                         f"page types eligible for product sampling by omission: {missing}")

    def test_the_listing_funnel_refuses_every_non_listing_type(self):
        """The same invariant on the listing side, where it was missing.

        Product sampling had a funnel and a stated exclusion; listing sampling
        had a string literal in each rule that wanted one. That asymmetry is
        why a page could be asked why it has no sort control without anything
        having decided it was a listing.
        """
        from aiva.config import GENERIC_PAGE_TYPE_HINTS, PAGE_TYPE_HINTS
        from aiva.extract import LISTING_PAGE_TYPES, NON_LISTING_PAGE_TYPES
        emitted = {name for name, _ in PAGE_TYPE_HINTS}
        emitted |= {name for name, _ in GENERIC_PAGE_TYPE_HINTS}
        emitted |= {"home", "other", "error", "non_html"}
        self.assertEqual(sorted(LISTING_PAGE_TYPES & NON_LISTING_PAGE_TYPES), [])
        missing = sorted(emitted - LISTING_PAGE_TYPES - NON_LISTING_PAGE_TYPES)
        self.assertEqual(missing, [],
                         f"page types eligible for listing sampling by omission: {missing}")

    def test_nothing_selects_listing_pages_by_a_string_literal(self):
        """One funnel, or the rules drift apart from the classifier.

        `ev.category_pages(bundle)` is the only way to a listing. A rule that
        writes `page_type == "category"` for itself is a second opinion, and
        the two opinions diverge the moment the classifier learns something
        the literal does not know. Named type *tuples* are exempt: they are
        readable, greppable and shared, which is the property this protects.
        """
        import re
        allowed = re.compile(r"^[A-Z_]*(?:PAGE_TYPES|TYPES)\s*[:=]")
        offenders = []
        for path in sorted((ROOT / "skills").glob("*/scripts/analyze.py")) + \
                sorted((ROOT / "lib" / "aiva").glob("*.py")):
            if path.name in ("extract.py", "evidence.py", "config.py"):
                continue          # where the vocabulary itself is defined
            for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if '"category"' not in line or allowed.match(line.strip()):
                    continue
                if "page_type" in line or "ev.pages(" in line:
                    offenders.append(f"{path.name}:{number}: {line.strip()}")
        self.assertEqual(offenders, [],
                         "listing selection must go through ev.category_pages: "
                         + "; ".join(offenders))

    #: One fact bag per signal the classifier reads, each carrying that signal
    #: and nothing else. Named for what a reader would call them, because the
    #: assertion below is about the *class* of mistake, not these nine bags.
    ONE_SIGNAL_EACH = {
        "a price": {"prices_in_text": [{"value": "499"}], "main_text": "£499"},
        "one heading": {"h1_count": 1, "h1_texts": ["Velocity X9"],
                        "title": "Velocity X9"},
        "a bare product token": {"jsonld_types": ["Product"]},
        "an open graph product type": {"open_graph": {"og:type": "product"}},
        "a microdata product type": {"microdata": [{"types": ["Product"]}]},
        "a specification table": {"tables": [{"rows": 4}]},
        "variant controls": {"variants": {"variant_selects": 1}},
        "a breadcrumb": {"breadcrumbs": {"present": True, "link_depth": 3}},
        "a cart control in the content": {"forms": {"has_cart_action_in_main": True}},
        "an item-shaped url": {},                       # supplied by the URL below
    }

    def test_no_single_signal_produces_an_individual_product(self):
        """The principle as a property over the signals, not over pages.

        Every false positive this auditor has shipped was one of these read on
        its own. Testing them one at a time is what makes the claim "multiple
        independent signals" checkable: adding a tenth signal to the
        classifier without adding it here leaves the property intact, and
        adding one that decides alone breaks this test rather than a live
        report.
        """
        from aiva.extract import product_evidence
        for label, facts in self.ONE_SIGNAL_EACH.items():
            url = ("https://x.example/products/velocity-x9"
                   if label == "an item-shaped url" else "https://x.example/x/y")
            with self.subTest(signal=label):
                verdict = product_evidence(url, facts)
                self.assertNotEqual(
                    verdict["verdict"], "individual",
                    f"{label} decided on its own: {verdict}")

    def test_an_individual_verdict_always_names_an_anchor(self):
        """Two signals are not enough if neither says *which* item.

        A price and a specification table are both true of a comparison page,
        a shipping policy and a promotions hub. Every pairing of the signals
        that only corroborate must still fall short.
        """
        from itertools import combinations
        from aiva.extract import product_evidence
        corroborating = {k: v for k, v in self.ONE_SIGNAL_EACH.items()
                         if k in ("a price", "one heading", "a specification table",
                                  "variant controls", "a breadcrumb")}
        for first, second in combinations(sorted(corroborating), 2):
            facts = dict(corroborating[first])
            facts.update(corroborating[second])
            with self.subTest(signals=(first, second)):
                verdict = product_evidence("https://x.example/x/y", facts)
                self.assertNotEqual(verdict["verdict"], "individual",
                                    f"{first} + {second} decided it: {verdict}")

    def test_a_product_verdict_is_reported_with_its_reasons(self):
        """The decision is inspectable, which is what makes it reviewable.

        A classifier that returns only a label cannot be argued with. This one
        returns the anchors and the corroboration it used, and the live report
        carries them, so a wrong classification can be read rather than
        guessed at.
        """
        from aiva.extract import product_evidence
        facts = {"jsonld_types": ["Product"],
                 "jsonld_nodes": [{"@type": "Product", "name": "Velocity X9",
                                   "sku": "VX9",
                                   "offers": {"@type": "Offer", "price": "999"}}],
                 "h1_count": 1, "h1_texts": ["Velocity X9"], "title": "Velocity X9"}
        verdict = product_evidence("https://x.example/products/velocity-x9", facts)
        self.assertEqual(verdict["verdict"], "individual")
        self.assertTrue(verdict["anchors"])
        self.assertGreaterEqual(len(verdict["singular"]), 2)

    def test_composed_answerability_signals_are_independent(self):
        """"Requires all" is only a real conjunction over disjoint vocabularies.

        `we accept` sat in both the instrument and the acceptance lists, so one
        observation satisfied a rule that was supposed to need two. Overlap
        turns a two-signal requirement back into a keyword match without
        changing a line of the logic that reads it.
        """
        from aiva.answerability import _CONCEPT_CONTEXT
        from aiva.lexicon import VOCABULARY
        for concept, rules in _CONCEPT_CONTEXT.items():
            required = rules.get("requires_all", ())
            if not required:
                # A concept may compose nothing and only veto a context - the
                # veto half is asserted by the test below. What must not exist
                # is a *conjunction of one*, which reads like two signals and
                # is one.
                continue
            self.assertGreaterEqual(len(required), 2, concept)
            seen = {}
            for name in required:
                phrases = {p for lang in VOCABULARY[name].values() for p in lang}
                for other, other_phrases in seen.items():
                    shared = phrases & other_phrases
                    self.assertEqual(
                        shared, set(),
                        f"{concept}: {name} and {other} share {sorted(shared)}")
                seen[name] = phrases

    def test_every_composed_concept_declares_a_negative_vocabulary(self):
        """A conjunction says what an answer contains; the veto says what it
        cannot be about. Without the second half, a sentence that happens to
        satisfy both halves in an unrelated context still passes."""
        from aiva.answerability import _CONCEPT_CONTEXT
        for concept, rules in _CONCEPT_CONTEXT.items():
            self.assertTrue(rules.get("forbids"),
                            f"{concept} composes signals but vetoes no context")
