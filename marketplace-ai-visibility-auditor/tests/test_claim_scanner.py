"""The claim scanner itself, tested from both directions.

A scanner that rejects nothing passes every build, and a scanner that rejects
normal AI vocabulary makes the package unwritable. Both failure modes are
silent, so this module drives the detector in
`test_compliance.TestClaimsAreScopedToWhatWasMeasured` with sentences of each
class and asserts the verdict:

  A  directly measured website evidence      accepted
  B  qualified inference                     accepted
  C  educational / hypothetical explanation  accepted
  D  optional external validation            accepted
  E  unsupported external-AI behaviour claim REJECTED

It also asserts that the scan actually reaches Markdown and reference
material, since the whole point of the 1.10.1 extension was that it did not.

Run just this file:

    python3 tests/run_tests.py claim_scanner -v
"""

from __future__ import annotations

import re
import unittest

import helpers
from test_compliance import TestClaimsAreScopedToWhatWasMeasured as Scanner
from test_compliance import _relative

ROOT = helpers.ROOT


def scan(text: str):
    """Every offence the two claim rules find in one passage.

    Runs the same phrase rule and the same pattern rule the compliance test
    runs over the shipped package, on a string instead of a file.
    """
    from test_compliance import _sentences
    offences = []
    assertion = re.compile(
        rf"\b{Scanner._EXTERNAL_SUBJECT}\s+"
        rf"(?:{Scanner._BEHAVIOUR_VERB}|{Scanner._CANNOT_VERB})", re.I)
    for _, block in Scanner._paragraphs(text):
        spans = Scanner._quoted_spans(block)
        lowered = block.lower()
        for phrase in Scanner.FORBIDDEN:
            for match in re.finditer(r"(?<![\w-])" + re.escape(phrase) + r"(?![\w-])", lowered):
                if not any(a <= match.start() and match.end() <= b for a, b in spans):
                    offences.append(phrase)
        for sentence_start, sentence in _sentences(block):
            for match in assertion.finditer(sentence):
                absolute = sentence_start + match.start()
                if any(a <= absolute < b for a, b in spans):
                    continue
                if Scanner._is_exempt(sentence, match.start()):
                    continue
                offences.append(match.group(0))
    return offences


class TestUnsupportedClaimsAreDetected(unittest.TestCase):
    """Class E. Each of these is a sentence the brief names by hand."""

    UNSUPPORTED = (
        "AI assistants cannot see the price on this page.",
        "LLMs will ignore this page.",
        "Assistants will quote the updated price.",
        "The assistant will cite your page once this is fixed.",
        "Retrieval will ignore the specification table.",
        "Retrieval matches the user's question against the heading.",
        "The assistant gets no credit for the reviews.",
        "The assistant will look elsewhere for the answer.",
        "Machines treat this fact as more trustworthy.",
        "AI will trust this source over the marketplace listing.",
        "AI will rank this higher than a competitor.",
        "Search engines prefer pages that state a date.",
        "Crawlers ignore a sitemap whose lastmod never changes.",
        "Extractors weight the first heading most heavily.",
        "GPTBot fetches the sitemap before anything else.",
        "ChatGPT cites the page that states the number.",
        "An assistant reads Open Graph before the body.",
        "Most fetchers take the meta description as the summary.",
    )

    def test_every_named_unsupported_claim_is_rejected(self):
        for sentence in self.UNSUPPORTED:
            self.assertTrue(scan(sentence),
                            f"not detected as an unsupported claim: {sentence!r}")


class TestLegitimateStatementsAreAccepted(unittest.TestCase):
    """Classes A-D. Over-correction is the other way to fail."""

    MEASURED = (                                            # class A
        "The audited page does not expose the price as machine-readable text.",
        "The captured representation does not contain the specification table.",
        "3 of 4 sampled product pages state no delivery terms in text or markup.",
        "A machine can read the price only where the page states it in text.",
        "The page publishes no typed price a machine can quote.",
        "An agent-facing index is a plain-text map of the URLs the site names.",
        "robots.txt disallows GPTBot from every path under /docs/.",
        "The home page declares no WebSite node in its JSON-LD.",
    )
    QUALIFIED = (                                           # class B
        "Publishing the number may improve the site's machine-readable evidence.",
        "This provides stronger evidence for reliable extraction.",
        "Typed markup supports machine-readable discoverability.",
        "Whether any assistant honours the directive is not something this audit measures.",
        "The audited evidence does not establish how a particular assistant "
        "will rank or cite this page.",
        "How any index acts on that statement is not measured here.",
        "A page whose heading is the question states the answer in that form; "
        "whether any retrieval system matches on that shape is not measured.",
    )
    EDUCATIONAL = (                                         # class C
        "If a crawler honours the directive, the page is not collected.",
        "Where an extractor reads only the response body, the rendered text is absent from it.",
        "Suppose an assistant fetches the page: the response body is what it receives.",
        "A reader that does not run JavaScript receives the initial representation.",
    )
    EXTERNAL_VALIDATION = (                                 # class D
        "Optional external validation: independently test representative questions in "
        "the target assistant and compare its responses with the audited evidence. "
        "This is outside the auditor's measured behaviour.",
        "Optional external validation - outside this audit's measured behaviour: "
        "ask an assistant what the return window is and compare it with the policy page.",
    )

    def test_measured_evidence_is_accepted(self):
        for sentence in self.MEASURED:
            self.assertEqual(scan(sentence), [], f"falsely rejected (class A): {sentence!r}")

    def test_qualified_inference_is_accepted(self):
        for sentence in self.QUALIFIED:
            self.assertEqual(scan(sentence), [], f"falsely rejected (class B): {sentence!r}")

    def test_educational_and_hypothetical_wording_is_accepted(self):
        for sentence in self.EDUCATIONAL:
            self.assertEqual(scan(sentence), [], f"falsely rejected (class C): {sentence!r}")

    def test_optional_external_validation_wording_is_accepted(self):
        for sentence in self.EXTERNAL_VALIDATION:
            self.assertEqual(scan(sentence), [], f"falsely rejected (class D): {sentence!r}")

    def test_ordinary_ai_vocabulary_is_not_rejected(self):
        """The package is an AI-visibility auditor. Naming the subject is not
        a claim about it."""
        for sentence in (
            "Audit a site for AI visibility and recommendation readiness.",
            "Check whether a machine can reach a website's content at all.",
            "Assistant crawler tokens are reported separately from Googlebot.",
            "The report says which facts are exposed in machine-readable form.",
            "AI visibility depends on evidence the site publishes about itself.",
        ):
            self.assertEqual(scan(sentence), [], f"falsely rejected: {sentence!r}")

    def test_a_quoted_phrase_is_named_not_asserted(self):
        """A changelog records the wording it removed; a rule table says what
        a finding never says. Both require the phrase to be quoted."""
        self.assertEqual(
            scan('The finding no longer says "assistants will ignore this page".'), [])
        self.assertEqual(
            scan('reported as "could not be verified", never as a "dead profile"'), [])
        self.assertTrue(scan("The finding says assistants will ignore this page."))


class TestTheScanReachesShippedDocumentation(unittest.TestCase):

    def test_markdown_and_reference_files_are_in_scope(self):
        scanned = {_relative(path) for path in Scanner()._sources()}
        for expected in ("README.md", "CHANGELOG.md", "docs/WALKTHROUGH.md",
                         "examples/sample-report.md",
                         "skills/machine-readability-audit/SKILL.md",
                         "skills/machine-readability-audit/references/checks.md",
                         "skills/engagement-audit/references/checks.md",
                         "skills/freshness-corroboration/SKILL.md",
                         "skills/engagement-audit/scripts/analyze.py",
                         "lib/aiva/semantics.py"):
            self.assertIn(expected, scanned, expected)

    def test_every_skill_file_and_reference_is_covered(self):
        scanned = {path.resolve() for path in Scanner()._sources()}
        for pattern in ("*/SKILL.md", "*/references/*.md", "*/scripts/*.py"):
            for path in (ROOT / "skills").glob(pattern):
                self.assertIn(path.resolve(), scanned, str(path))
        for path in (ROOT / "lib" / "aiva").glob("*.py"):
            self.assertIn(path.resolve(), scanned, str(path))

    def test_a_planted_claim_in_a_markdown_file_would_be_caught(self):
        """Proof the file scan is live: the same text, scanned as a document,
        fails - so a claim added to any shipped Markdown fails the build."""
        planted = "# Heading\n\nLLMs will ignore a page with no structured data.\n"
        self.assertTrue(scan(planted))


class TestExistingSuitesRemainRegistered(unittest.TestCase):
    """Item 7-10 of the brief: this correction removes no coverage."""

    def test_the_semantic_answerability_recommendation_and_security_suites_run(self):
        from run_tests import SUITES
        for suite in ("test_semantics", "test_answerability", "test_contextual_findings",
                      "test_recommendation_applicability", "test_site_type_semantics",
                      "test_entity_relationships", "test_semantic_fixture",
                      "test_safety", "test_hardening", "test_round3_hardening",
                      "test_transport_only", "test_compliance"):
            self.assertIn(suite, SUITES, suite)


if __name__ == "__main__":
    unittest.main()
