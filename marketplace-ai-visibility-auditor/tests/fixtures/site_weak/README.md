# Fixture: site_weak

A deliberately broken storefront used to regression-test detection. Every
defect here is intentional and annotated in the source with an
`<!-- DEFECT: ... -->` comment naming the rule that should fire.

Nothing in this folder is a real brand. Served locally by
`lib/aiva/localserve.py`; never deployed.
