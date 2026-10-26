# Fixture: site_mixed

A partly-good storefront: crawlable and marked up, but with the failure
modes a real mid-sized site accumulates - a client-rendered product route, a
noindexed page, a dead sitemap entry, a redirect chain that ends on the home
page, a listing price that disagrees with the product page, an
under-described organisation, and two URLs claiming to be the same product.

Every defect is annotated in the source with `<!-- DEFECT: ... -->`.
Not a real brand. Served locally by `lib/aiva/localserve.py`.
