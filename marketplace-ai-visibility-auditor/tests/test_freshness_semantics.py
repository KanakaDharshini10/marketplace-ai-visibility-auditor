"""Freshness semantics: a copyright year is a weak signal, and is reported as one.

An old footer year used to be described as "one of the cheapest cues a machine
has that a site may be abandoned", with a mechanism in which "dead sites lose
to maintained competitors as sources". The audit measures none of that. It
reads a year in a footer. These tests hold the rule to the observation, and to
weighing that observation against the other date signals the site carries:

* old year + fresh content elsewhere -> ``info``, "contradicted", no
  suggestion the content is unmaintained;
* old year + a recent ``Last-Modified`` header -> the same;
* old year + genuinely old maintenance dates -> ``medium`` at most,
  "consistent", worded as a possibility to check;
* old year + no other signal at all -> ``low``, "uncorroborated".

In every case the interpretation says the audit does not measure how any
assistant weighs the year, and never uses abandonment or ranking language.

Run just this file:

    python3 tests/run_tests.py freshness_semantics -v
"""

from __future__ import annotations

import datetime as dt
import unittest

from helpers import ORIGIN, bundle, find, html_doc, page, run

RULE = "FC-STALE-COPYRIGHT"
BANNED = ("abandon", "dead site", "lose to", "loses to", "competitor",
          "cheapest cues", "ranking")


def _today() -> dt.date:
    return dt.datetime.now(dt.timezone.utc).date()


def _ld_with_modified(days_ago: int) -> str:
    when = (_today() - dt.timedelta(days=days_ago)).isoformat()
    return ('<script type="application/ld+json">{"@context":"https://schema.org",'
            f'"@type":"WebPage","name":"Policy","dateModified":"{when}"}}</script>')


def _page(path: str, *, old_year: int, head: str = "", headers=None) -> dict:
    return page(ORIGIN + path, html_doc(
        title=path.strip("/").title() or "Home", canonical=ORIGIN + path, head=head,
        body=f"<main><h1>{path.strip('/').title() or 'Home'}</h1><p>Some content.</p></main>"
             f"<footer>&copy; {old_year} Kestrel Ltd</footer>"), headers=headers)


class TestCopyrightIsAWeakSignal(unittest.TestCase):
    OLD = _today().year - 6

    def _assert_never_infers_abandonment(self, found):
        text = " ".join([found.evidence, found.interpretation or "",
                         found.suggested_action.mechanism or ""]).lower()
        for banned in BANNED:
            self.assertNotIn(banned, text, f"{banned!r} in {text!r}")
        self.assertIn("does not measure", text)
        self.assertIn("weak", text)

    def test_old_year_with_fresh_content_is_contradicted_and_info(self):
        pages = [_page("/", old_year=self.OLD, head=_ld_with_modified(12)),
                 _page("/pages/policy", old_year=self.OLD, head=_ld_with_modified(30)),
                 _page("/pages/about", old_year=self.OLD)]
        found = find(run("freshness-corroboration", bundle(pages)), RULE)
        self.assertIsNotNone(found, "the observation is still reported")
        self.assertEqual(found.severity, "info")
        self.assertEqual(found.metrics["situation"], "contradicted")
        self.assertIn("fresher signals", found.evidence)
        self.assertIn("does not suggest the content is unmaintained", found.interpretation)
        self._assert_never_infers_abandonment(found)

    def test_old_year_with_recent_last_modified_header_is_contradicted(self):
        recent = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=5)).strftime(
            "%a, %d %b %Y %H:%M:%S GMT")
        pages = [_page("/", old_year=self.OLD, headers={"last-modified": recent}),
                 _page("/pages/about", old_year=self.OLD)]
        found = find(run("freshness-corroboration", bundle(pages)), RULE)
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "info")
        self.assertEqual(found.metrics["situation"], "contradicted")
        self._assert_never_infers_abandonment(found)

    def test_old_year_with_genuinely_stale_content_is_qualified(self):
        pages = [_page("/", old_year=self.OLD, head=_ld_with_modified(1100)),
                 _page("/pages/policy", old_year=self.OLD, head=_ld_with_modified(1200)),
                 _page("/pages/about", old_year=self.OLD, head=_ld_with_modified(1300))]
        # No sitemap lastmod either: the helper's default sitemap is dated
        # today, which is itself a fresh signal and would contradict the year.
        found = find(run("freshness-corroboration", bundle(pages, sitemaps=[])), RULE)
        self.assertIsNotNone(found)
        self.assertEqual(found.metrics["situation"], "consistent")
        self.assertIn(found.severity, ("low", "medium"))
        self.assertIn("possibility", found.interpretation)
        self.assertIn("not a measured outcome", found.interpretation)
        self._assert_never_infers_abandonment(found)

    def test_old_year_alone_is_uncorroborated_and_low(self):
        pages = [_page("/", old_year=self.OLD), _page("/pages/about", old_year=self.OLD)]
        found = find(run("freshness-corroboration", bundle(pages, sitemaps=[])), RULE)
        self.assertIsNotNone(found)
        self.assertEqual(found.severity, "low")
        self.assertEqual(found.metrics["situation"], "uncorroborated")
        self.assertIn("nothing to corroborate or contradict", found.evidence)
        self._assert_never_infers_abandonment(found)

    def test_a_current_year_is_not_a_finding(self):
        pages = [_page("/", old_year=_today().year), _page("/pages/about", old_year=_today().year)]
        self.assertIsNone(find(run("freshness-corroboration", bundle(pages)), RULE))


if __name__ == "__main__":
    unittest.main()
