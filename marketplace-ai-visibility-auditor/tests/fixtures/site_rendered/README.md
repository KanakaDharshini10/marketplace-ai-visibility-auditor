# `site_rendered` — the raw/rendered distinction, on purpose

An invented lantern maker whose product and listing pages assemble their
decisive facts **after** hydration. Nothing here is modelled on a real site.

| page | server response states | browser-rendered state adds |
|---|---|---|
| `/products/halo-lantern.html` | name, brand, description | price, availability, a buy control, an aggregate rating and review text, a specification table, and typed `Offer`/`AggregateRating` |
| `/collections/lanterns.html` | nine entries with prices | a filter control and a sort control |
| `/index.html` | everything it has | nothing — the control for "rendering changed nothing" |

Used by `tests/test_rendered_evidence.py` to prove the audit tells
"absent from the page" apart from "absent from the server response", and by the
security tests to prove rendering obeys the same robots and address rules as
the fetcher. The scripts are synchronous and take no input, so a render of this
fixture is deterministic.
