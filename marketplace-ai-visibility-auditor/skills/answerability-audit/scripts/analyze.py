#!/usr/bin/env python3
"""answerability-audit - can the evidence answer the questions buyers ask?

The other five specialists audit mechanisms: crawlability, markup, entity
clarity, freshness, on-page continuity. A site can pass all of them and still
fail the only test that matters, because nobody asked whether the resulting
evidence answers a question.

This skill asks. It generates questions from the site's own catalogue and
content, resolves each against the shared evidence bundle, and reports the
ones the site cannot answer - with the URL it looked at and the snippet it
found. Questions are never invented: if the crawl saw no product, no
product question is generated.

Consumes the shared evidence bundle. Performs no network I/O.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List, Optional


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
from aiva import answerability                        # noqa: E402
from aiva.analysis import (action, cap_severity, confidence_for,   # noqa: E402
                           crawl_yielded_evidence, finding, observed)
from aiva.findings import Finding                     # noqa: E402

SKILL = "answerability-audit"
PILLAR = "answerability"

#: A question kind is only worth a finding when enough of them failed to show
#: a pattern rather than one thin page.
MIN_FAILURES_FOR_FINDING = 2

#: What each question kind is *about*, for the finding title.
KIND_LABEL = {
    "product_price": "the price of a product",
    "product_availability": "whether a product is in stock",
    "product_specifications": "a product's specifications",
    "category_cheapest": "which item in a category is cheapest",
    "product_comparison": "how two products differ",
    "return_window": "the return window",
    "shipping_destinations": "where the site ships and what delivery costs",
    "payment_options": "which payment methods are accepted",
}


def _rows_by_kind(matrix: dict, statuses) -> Dict[str, List[dict]]:
    out: Dict[str, List[dict]] = {}
    for row in matrix["questions"]:
        if row["status"] in statuses:
            out.setdefault(row["kind"], []).append(row)
    return out


def rule_unanswerable_questions(bundle: dict, matrix: dict) -> List[Finding]:
    """Questions the site's own content raises but its evidence cannot answer."""
    out: List[Finding] = []
    failures = _rows_by_kind(matrix, ("not_answerable",))
    for kind, rows in sorted(failures.items()):
        asked = [r for r in matrix["questions"] if r["kind"] == kind]
        if len(rows) < MIN_FAILURES_FOR_FINDING and len(asked) < MIN_FAILURES_FOR_FINDING:
            # One product with no price is a page problem, not a pattern - and
            # a site-wide question (returns, shipping) is asked exactly once,
            # so it is allowed through on its own.
            if kind not in ("return_window", "shipping_destinations", "payment_options"):
                continue
        ratio = len(rows) / max(1, len(asked))
        severity = cap_severity("high" if ratio >= 0.6 else "medium", len(asked))
        example = rows[0]
        out.append(finding(
            f"AN-UNANSWERABLE-{kind.upper().replace('_', '-')}",
            f"A buyer asking about {KIND_LABEL.get(kind, kind)} finds no answer in the "
            f"fetched evidence",
            severity, PILLAR,
            evidence=f"{len(rows)} of {len(asked)} generated question(s) of this kind could "
                     f"not be answered from the crawled pages. Example: "
                     f"\"{example['question']}\" - {example['evidence']}.",
            interpretation="The question was generated from this site's own content, so it "
                           "is a question the catalogue invites. An assistant assembling an "
                           "answer has the same pages this audit read; where the fact is not "
                           "in them, the answer has to come from somewhere else or not at "
                           "all. This measures the evidence, not any particular assistant's "
                           "behaviour.",
            items=[observed(f'"{row["question"]}" - {row["evidence"]}',
                            url=row["citing_url"], locator=row["evidence_source"])
                   for row in rows[:5]],
            action=action(example["suggested_action"] or
                          "Publish the missing fact in the server-rendered HTML and mirror "
                          "it in structured data.",
                          priority="high" if severity in ("high", "critical") else "medium",
                          effort="medium", impact="high",
                          mechanism="A question is answerable when the fact is present in "
                                    "the response and identifiable without guessing. "
                                    "Publishing it once, in a typed field, makes every "
                                    "phrasing of the question resolvable from the same value.",
                          steps=[example["suggested_action"]] if example["suggested_action"]
                          else ["State the fact in the page and in structured data."],
                          verification="Re-run this audit; the question moves out of "
                                       "not_answerable in the answerability matrix.",
                          verification_type="self_verifiable"),
            urls=[row["citing_url"] for row in rows if row["citing_url"]],
            confidence=confidence_for(len(rows), len(asked)),
            metrics={"scope": "template" if ratio >= 0.8 else "section",
                     "affected": len(rows), "sampled": len(asked),
                     "sample_unit": "generated question(s)",
                     "question_kind": kind},
            tags=["answerability", kind.split("_")[0]]))
    return out


def rule_prose_only_answers(bundle: dict, matrix: dict) -> Optional[Finding]:
    """Facts a reader can find but a machine has to parse out of a sentence."""
    partial = [r for r in matrix["questions"] if r["status"] == "partial"]
    asked = matrix["questions"]
    if len(partial) < MIN_FAILURES_FOR_FINDING or not asked:
        return None
    ratio = len(partial) / len(asked)
    kinds = sorted({row["kind"] for row in partial})
    return finding(
        "AN-ANSWERS-PROSE-ONLY",
        "Answers exist on the page but only as prose, not as typed values",
        cap_severity("medium" if ratio < 0.6 else "high", len(asked)), PILLAR,
        evidence=f"{len(partial)} of {len(asked)} generated question(s) were answerable only "
                 f"from visible text, with no typed value behind them "
                 f"({', '.join(kinds)}).",
        interpretation="A fact stated in a sentence is available to a reader and recoverable "
                       "by a machine only after parsing that sentence, which differs by "
                       "phrasing and by language. The same fact in a typed field is read "
                       "directly. This is the gap between a page a person can use and "
                       "evidence a system can quote.",
        items=[observed(f'"{row["question"]}" - {row["evidence"]}',
                        url=row["citing_url"], locator=row["evidence_source"])
               for row in partial[:5]],
        action=action("Mirror the facts already published into typed structured data.",
                      priority="medium", effort="low", impact="high",
                      mechanism="The content already exists; publishing it as a typed value "
                                "removes the parsing step between the page and an answer.",
                      steps=sorted({row["suggested_action"] for row in partial
                                    if row["suggested_action"]})[:4]
                      or ["Mirror the visible facts in structured data."],
                      verification="Re-run this audit; these questions move from partial to "
                                   "answerable in the answerability matrix.",
                      verification_type="self_verifiable"),
        urls=[row["citing_url"] for row in partial if row["citing_url"]],
        confidence=confidence_for(len(partial), len(asked)),
        metrics={"scope": "template" if ratio >= 0.6 else "section",
                 "affected": len(partial), "sampled": len(asked),
                 "sample_unit": "generated question(s)",
                 "kinds": kinds},
        tags=["answerability", "structured-data"])


def analyze(bundle: dict) -> List[Finding]:
    if not crawl_yielded_evidence(bundle):
        return []
    matrix = answerability.build_matrix(bundle)
    if not matrix["questions"]:
        # Nothing the site's content supports asking. That is a fact about the
        # crawl, not a defect, and it is recorded in the matrix notes.
        return []
    out: List[Finding] = []
    out.extend(rule_unanswerable_questions(bundle, matrix))
    prose = rule_prose_only_answers(bundle, matrix)
    if prose:
        out.append(prose)
    for item in out:
        item.source_skill = SKILL
        item.pillar = PILLAR
    return out


def main(argv: Optional[List[str]] = None) -> int:
    util.use_utf8_stdio()   # a report quotes the site's own text; write it as UTF-8
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", required=True)
    parser.add_argument("--out")
    parser.add_argument("--matrix", action="store_true",
                        help="emit the full answerability matrix instead of findings")
    args = parser.parse_args(argv)
    with open(args.bundle, "r", encoding="utf-8") as handle:
        bundle = json.load(handle)
    if args.matrix:
        payload = json.dumps(answerability.build_matrix(bundle), indent=2,
                             ensure_ascii=False)
    else:
        payload = json.dumps({"skill": SKILL, "pillar": PILLAR,
                              "findings": [f.to_dict() for f in analyze(bundle)]},
                             indent=2, ensure_ascii=False)
    if args.out:
        Path(args.out).write_text(payload, encoding="utf-8")
    else:
        print(payload)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
