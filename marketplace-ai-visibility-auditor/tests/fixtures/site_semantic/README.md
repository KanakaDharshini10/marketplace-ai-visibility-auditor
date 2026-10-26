# site_semantic fixture

A generic mixed-shape site, served over loopback by the tests. Nothing here
is a real site. It exists so the semantic-applicability layer can be
regression-tested end to end against, on one site:

physical product, software product, subscription plan, service page,
documentation pages (TechArticle; one with no h1, one with a visible date and
no machine date), publisher articles (one with two h1s, one noindexed, one
with a cross-domain canonical), an ecommerce listing, a content listing, a
documentation section, a department with a parent organisation, localized
organisation names (es, ja), official profile links beside knowledge,
documentation and ambiguous external links, a redirect chain, a 403, a 429,
a timeout, a noindexed sign-in page, an Organization node with partial
metadata, and no site search.

Expected behaviours are asserted in tests/test_semantic_fixture.py.
