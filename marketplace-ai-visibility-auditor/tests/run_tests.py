#!/usr/bin/env python3
"""Run the whole suite with the standard library only.

    python3 tests/run_tests.py          # everything
    python3 tests/run_tests.py -v       # verbose
    python3 tests/run_tests.py rules    # only tests/test_rules.py
"""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
for extra in (str(HERE), str(ROOT / "lib")):
    if extra not in sys.path:
        sys.path.insert(0, extra)

SUITES = ("test_core", "test_rules", "test_report", "test_e2e",
          "test_safety", "test_compliance", "test_claim_scanner", "test_portability", "test_cocoacraft_regression",
          "test_answerability", "test_generalization", "test_hardening",
          "test_ikea_regression", "test_page_types",
          "test_page_type_provenance", "test_transport_only",
          "test_redirect_semantics", "test_specialist_reliability",
          "test_product_identity", "test_sitemap_semantics",
          "test_canonical_eligibility", "test_round3_hardening",
          "test_page_eligibility", "test_location_semantics",
          "test_freshness_semantics", "test_site_shapes",
          "test_semantics", "test_entity_relationships",
          "test_recommendation_applicability", "test_contextual_findings", "test_site_type_semantics",
          "test_provenance", "test_rendered_evidence", "test_false_positives",
          "test_recommendation_precision", "test_semantic_fixture")


def main(argv: list) -> int:
    verbosity = 2 if any(a in ("-v", "--verbose") for a in argv) else 1
    selected = [a for a in argv if not a.startswith("-")]
    names = SUITES
    if selected:
        names = tuple(n for n in SUITES
                      if any(s in n for s in selected))
        if not names:
            print(f"no suite matches {selected}; available: {', '.join(SUITES)}")
            return 2

    loader = unittest.TestLoader()
    suite = unittest.TestSuite(loader.loadTestsFromName(name) for name in names)
    result = unittest.TextTestRunner(verbosity=verbosity).run(suite)

    print()
    print(f"suites: {', '.join(names)}")
    print(f"tests: {result.testsRun}  failures: {len(result.failures)}  "
          f"errors: {len(result.errors)}  skipped: {len(result.skipped)}")
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
