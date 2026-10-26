"""The package behaves the same on Windows, Linux and macOS.

Two platform assumptions broke a Windows run of v1.10.1, and neither was
visible on Linux because Linux happens to make both assumptions true:

1. **Console encoding.** A report quotes the audited site's own text, so it
   carries whatever the site publishes - a rupee sign, a Japanese product
   name. Python takes its stdout encoding from the console, and a Windows
   console is a legacy code page: cp1252 cannot encode U+20B9, so three CLI
   entry points died with ``UnicodeEncodeError`` while printing a perfectly
   valid report.

2. **Path separators.** ``str(PurePath)`` uses the platform separator, so the
   claim scanner named a file ``docs\\WALKTHROUGH.md`` on Windows and
   ``docs/WALKTHROUGH.md`` everywhere else.

Both are reproduced here on *any* platform: the encoding one by forcing the
child process's stdout to cp1252 with ``PYTHONIOENCODING`` (exactly the
condition a Windows console creates), the path one by asserting the spelling
the boundary helper produces. Neither test is skipped anywhere.

Run just this file:

    python3 tests/run_tests.py portability -v
"""

from __future__ import annotations

import io
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path, PureWindowsPath

import helpers
from test_compliance import TestClaimsAreScopedToWhatWasMeasured as Scanner
from test_compliance import _relative

from aiva import paths, util

ROOT = helpers.ROOT
ENTRYPOINT = ROOT / "skills" / "marketplace-ai-visibility-audit" / "scripts"

#: The console encoding a default Windows install gives a Python process.
#: U+20B9 (the rupee sign the weak fixture prices its goods in) has no cp1252
#: code point, which is the whole of the bug.
LEGACY_CONSOLE = "cp1252"
UNENCODABLE = "₹"


def run_cli(*args, encoding: str = LEGACY_CONSOLE, timeout: int = 300):
    """Run a CLI entry point with a child console that cannot spell U+20B9.

    ``PYTHONIOENCODING`` sets the child's stdout encoding before any of our
    code runs, which is precisely what a Windows console does. The parent
    decodes UTF-8 explicitly rather than trusting its own locale, so the
    assertion is about the child's bytes and not about the runner's platform.
    """
    environment = dict(os.environ, PYTHONIOENCODING=encoding)
    return subprocess.run([sys.executable, *[str(a) for a in args]],
                          capture_output=True, timeout=timeout, env=environment)


class TestStdoutSurvivesALegacyConsole(unittest.TestCase):
    """Failures 1-3: UnicodeEncodeError on a cp1252 stdout."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.bundle = str(Path(cls.tmp.name) / "bundle.json")
        result = run_cli(ENTRYPOINT / "collect_evidence.py", "--offline", "weak",
                         "--out", cls.bundle)
        assert result.returncode == 0, result.stderr.decode("utf-8", "replace")

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_the_full_audit_prints_a_report_a_legacy_console_cannot_spell(self):
        result = run_cli(ENTRYPOINT / "run_audit.py", "--offline", "weak", "--quiet")
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode("utf-8", "replace")[-800:])
        text = result.stdout.decode("utf-8")
        report = json.loads(text)
        self.assertGreater(report["summary"]["total_findings"], 10)
        self.assertIn(UNENCODABLE, text,
                      "the character is what makes this a portability test")

    def test_compose_report_prints_the_same_report(self):
        result = run_cli(ENTRYPOINT / "compose_report.py", "--bundle", self.bundle)
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode("utf-8", "replace")[-800:])
        report = json.loads(result.stdout.decode("utf-8"))
        self.assertGreater(report["summary"]["total_findings"], 10)

    def test_every_specialist_script_prints_its_findings(self):
        for entry in paths.specialist_skills():
            script = ROOT / entry["path"] / entry["script"]
            result = run_cli(script, "--bundle", self.bundle)
            self.assertEqual(result.returncode, 0,
                             f"{entry['id']}: "
                             + result.stderr.decode("utf-8", "replace")[-500:])
            payload = json.loads(result.stdout.decode("utf-8"))
            self.assertEqual(payload["skill"], entry["id"])

    def test_the_answerability_matrix_carries_the_quoted_price(self):
        """The matrix quotes prices from the fixture, which is where U+20B9
        enters the output at all."""
        script = ROOT / "skills" / "answerability-audit" / "scripts" / "analyze.py"
        result = run_cli(script, "--bundle", self.bundle, "--matrix")
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode("utf-8", "replace")[-500:])
        self.assertIn(UNENCODABLE, result.stdout.decode("utf-8"))

    def test_the_markdown_projection_survives_too(self):
        result = run_cli(ENTRYPOINT / "run_audit.py", "--offline", "weak", "--quiet",
                         "--format", "markdown")
        self.assertEqual(result.returncode, 0,
                         result.stderr.decode("utf-8", "replace")[-800:])
        self.assertIn(UNENCODABLE, result.stdout.decode("utf-8"))

    def test_the_bytes_are_utf8_whatever_the_console_claims(self):
        """Not "it did not crash" but "it wrote the right bytes": decoding as
        cp1252 must *not* reproduce the source text."""
        result = run_cli(ENTRYPOINT / "run_audit.py", "--offline", "weak", "--quiet")
        self.assertEqual(result.returncode, 0)
        as_utf8 = result.stdout.decode("utf-8")
        self.assertIn(UNENCODABLE, as_utf8)
        self.assertNotIn(UNENCODABLE, result.stdout.decode(LEGACY_CONSOLE, "replace"))


class TestTheStdioHelper(unittest.TestCase):
    """One helper, used by every entry point, safe to call anywhere."""

    def test_it_is_the_only_stdio_configuration_in_the_package(self):
        callers = []
        for script in sorted(ROOT.glob("skills/*/scripts/*.py")):
            text = script.read_text(encoding="utf-8")
            self.assertIn("util.use_utf8_stdio()", text,
                          f"{script.name} writes to stdout without configuring it")
            callers.append(script)
            # No second mechanism: no per-script wrapper, no reconfigure call
            # of its own, no environment variable pushed at the user.
            self.assertNotIn("TextIOWrapper", text, script.name)
            self.assertNotIn("PYTHONIOENCODING", text, script.name)
        self.assertEqual(len(callers), 10)
        library = (ROOT / "lib" / "aiva").glob("*.py")
        homes = [p.name for p in library if "def use_utf8_stdio" in p.read_text(encoding="utf-8")]
        self.assertEqual(homes, ["util.py"], "exactly one home for the helper")

    def test_it_leaves_an_already_utf8_stream_alone(self):
        before = sys.stdout
        util.use_utf8_stdio()
        self.assertIs(sys.stdout, before, "the stream is reconfigured, never replaced")
        self.assertEqual((sys.stdout.encoding or "").lower().replace("-", ""), "utf8")

    def test_it_is_a_no_op_on_a_stream_that_cannot_be_reconfigured(self):
        """A test harness or a caller may install a plain StringIO. That is a
        deliberate choice by whoever made it, and must not raise."""
        captured = io.StringIO()
        original = sys.stdout
        sys.stdout = captured
        try:
            util.use_utf8_stdio()
            print(UNENCODABLE)
        finally:
            sys.stdout = original
        self.assertEqual(captured.getvalue().strip(), UNENCODABLE)

    def test_it_survives_a_detached_stream(self):
        class Detached:
            encoding = "cp1252"

            def reconfigure(self, **_kwargs):
                raise ValueError("underlying buffer has been detached")

        original_out, original_err = sys.stdout, sys.stderr
        sys.stdout = sys.stderr = Detached()
        try:
            util.use_utf8_stdio()               # must not raise
        finally:
            sys.stdout, sys.stderr = original_out, original_err

    def test_it_is_available_on_python_39(self):
        """`TextIOWrapper.reconfigure` is stdlib from 3.7, and the helper uses
        nothing newer - no `sys.stdout.reconfigure` walrus, no 3.10 syntax."""
        self.assertGreaterEqual(sys.version_info[:2], (3, 9))
        source = (ROOT / "lib" / "aiva" / "util.py").read_text(encoding="utf-8")
        import ast
        ast.parse(source)                        # parses under the running interpreter
        self.assertIn("reconfigure", source)


class TestScannedPathsAreSpelledTheSameEverywhere(unittest.TestCase):
    """Failure 4: `docs\\WALKTHROUGH.md` on Windows, `docs/WALKTHROUGH.md` here."""

    def test_a_windows_style_path_is_reported_posix_style(self):
        """The exact shape of the Windows failure, exercised from any platform:
        a Windows root and a Windows path in, a "/"-separated name out."""
        root = PureWindowsPath(r"C:\src\marketplace-ai-visibility-auditor")
        for parts, expected in (
                (("docs", "WALKTHROUGH.md"), "docs/WALKTHROUGH.md"),
                (("README.md",), "README.md"),
                (("skills", "engagement-audit", "references", "checks.md"),
                 "skills/engagement-audit/references/checks.md"),
                (("lib", "aiva", "semantics.py"), "lib/aiva/semantics.py")):
            windows = root.joinpath(*parts)
            self.assertIn("\\", str(windows), "the fixture must be a Windows path")
            self.assertEqual(_relative(windows, root), expected)

    def test_no_scanned_name_contains_a_backslash(self):
        for path in Scanner()._sources():
            name = _relative(path)
            self.assertNotIn("\\", name)
            self.assertFalse(name.startswith("/"), name)

    def test_the_documentation_is_still_in_scope_under_either_spelling(self):
        """The fix normalises the spelling; it does not narrow the scan."""
        scanned = {_relative(path) for path in Scanner()._sources()}
        for required in ("docs/WALKTHROUGH.md", "README.md", "CHANGELOG.md",
                         "examples/sample-report.md",
                         "skills/machine-readability-audit/SKILL.md",
                         "skills/engagement-audit/references/checks.md"):
            self.assertIn(required, scanned, required)

    def test_the_offender_message_uses_the_same_spelling(self):
        """A failure message a Windows developer reads must name the file the
        way the repository does, so it can be pasted into an editor."""
        sample = next(p for p in Scanner()._sources() if p.name == "WALKTHROUGH.md")
        message = f"{_relative(sample)}:12: 'assistants will'"
        self.assertTrue(message.startswith("docs/WALKTHROUGH.md:"), message)


if __name__ == "__main__":
    unittest.main()
