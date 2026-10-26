# Fixture: site_locales

A multi-market site shaped like the one that produced the evidence defects this
fixture exists to regression-test. Fictional; served on loopback only.

Reproduced deliberately:

* `/in/en/` is a **locale root** carrying prices, a cart control and variant
  swatches. The content-signal branch of `classify_page` used to call it a
  product page, after which it was counted among "identified product pages"
  and cited as the product page carrying no Product schema.
* `/global/en/privacy.html` mentions **Returns only in its navigation**. It was
  cited as the site's statement of its return window, quoted from the top of
  the page.
* `/in/en/customer-service/return-policy.html` is the page that actually
  answers that question, and is what a correct audit must cite.
* `/ee/et/**` and `/ae/en/` are **other markets**, advertised in the shared
  sitemap. An audit entered at `/in/en/` must not fold them into its ratios.
* `/in/en/` states accepted payment methods in its own prose; a cart button
  elsewhere must never be mistaken for that statement.
