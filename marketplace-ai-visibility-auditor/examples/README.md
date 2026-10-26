# Example output

`sample-report.json` and `sample-report.md` are a real, unedited run of the
entrypoint skill against the bundled **`site_mixed`** fixture — a realistic
middling storefront with a client-rendered product route, a noindexed page, a
dead sitemap entry, a redirect chain that ends on the home page, a listing price
that disagrees with the product page, an under-described organisation, and two
URLs claiming to be the same product.

Regenerate them at any time:

```bash
python3 skills/marketplace-ai-visibility-audit/scripts/run_audit.py \
    --offline mixed --out examples --format both
mv examples/audit-report.json examples/sample-report.json
mv examples/audit-report.md   examples/sample-report.md
```

URLs in the report are `http://127.0.0.1:<port>` because the fixture is served
from a local loopback server; the port changes per run. Nothing external is
contacted.

`sample-report.json` is the default `full` projection. For the brief's exact
minimum shape add `--schema handout`; for the flattest variant, `--schema flat`.
