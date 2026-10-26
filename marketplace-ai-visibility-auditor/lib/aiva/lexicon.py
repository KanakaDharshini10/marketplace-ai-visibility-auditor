"""Multilingual vocabulary for the handful of concepts detected from prose.

Most of this auditor reads *structure* - status codes, robots directives,
schema.org types - which is language-neutral. A few engagement checks have to
read words: does this page mention delivery, returns, stock, a way to buy?

Doing that with English-only regexes is a generalisation bug, not a
simplification: a Spanish storefront that says "Envío gratis. Devoluciones en
30 días. En stock." would be reported as hiding all three facts. Since the
brief grades on unseen sites, that is the worst kind of false positive - one
that fires *because* the site is not the kind of site the author imagined.

Two defences, in order:

1. **Prefer structured evidence.** `OfferShippingDetails` and
   `MerchantReturnPolicy` state the same facts in a language-neutral way, and
   an analyzer should believe them before it believes a regex.
2. **Then match a real vocabulary**, and when the page's language is one this
   module does not cover, say so instead of guessing. A recorded false
   negative with a note beats a confident false positive.

Coverage is Latin-script languages the author can state accurately. Everything
else is reported as unsupported rather than silently mis-audited - see
:func:`language_supported`.
"""

from __future__ import annotations

import re
import unicodedata
from typing import Dict, Iterable, List, Optional, Tuple

#: Languages whose prose these vocabularies actually cover.
SUPPORTED_LANGUAGES = ("en", "es", "fr", "de", "pt", "it", "nl",
                       "pl", "sv", "da", "nb", "no", "tr")

#: concept -> language -> phrases. Phrases are matched on diacritic-folded,
#: lowercased text with word boundaries, so "envio" matches "envío".
VOCABULARY: Dict[str, Dict[str, Tuple[str, ...]]] = {
    "shipping": {
        "en": ("shipping", "delivery", "dispatch", "courier", "freight", "ships in"),
        "es": ("envio", "envios", "entrega", "despacho", "mensajeria"),
        "fr": ("livraison", "expedition", "frais de port"),
        "de": ("versand", "lieferung", "zustellung", "versandkosten"),
        "pt": ("envio", "entrega", "frete", "expedicao"),
        "it": ("spedizione", "spedizioni", "consegna"),
        "nl": ("verzending", "levering", "bezorging"),
        "pl": ("wysyłka", "wysyłki", "dostawa", "dostawy", "przesyłka"),
        "sv": ("frakt", "leverans", "försändelse"),
        "da": ("fragt", "levering", "forsendelse"),
        "nb": ("frakt", "levering", "forsendelse"),
        "tr": ("kargo", "kargosu", "teslimat", "teslimatı", "gönderim"),
    },
    "returns": {
        "en": ("return", "returns", "refund", "refunds", "exchange", "money back"),
        "es": ("devolucion", "devoluciones", "reembolso"),
        "fr": ("retour", "retours", "remboursement"),
        "de": ("ruckgabe", "retoure", "retouren", "ruckerstattung", "umtausch"),
        "pt": ("devolucao", "devolucoes", "reembolso", "troca"),
        "it": ("reso", "resi", "rimborso"),
        "nl": ("retour", "retourneren", "terugbetaling", "ruilen"),
        "pl": ("zwrot", "zwroty", "zwrotu", "zwrotów", "reklamacja", "reklamacje"),
        "sv": ("retur", "returer", "återbetalning", "byte"),
        "da": ("retur", "returnering", "refusion", "ombytning"),
        "nb": ("retur", "returnering", "refusjon", "bytte"),
        "tr": ("iade", "iadeler", "iadesi", "geri ödeme", "değişim"),
    },
    "in_stock": {
        "en": ("in stock", "available now", "ready to ship"),
        "es": ("en stock", "disponible", "en existencia"),
        "fr": ("en stock", "disponible"),
        "de": ("auf lager", "verfugbar", "lieferbar"),
        "pt": ("em estoque", "disponivel"),
        "it": ("disponibile", "in magazzino"),
        "nl": ("op voorraad", "beschikbaar"),
        "pl": ("dostępny", "w magazynie", "na stanie"),
        "sv": ("i lager", "tillgänglig"),
        "da": ("på lager", "tilgængelig"),
        "nb": ("på lager", "tilgjengelig"),
        "tr": ("stokta", "stokta var", "mevcut"),
    },
    "out_of_stock": {
        "en": ("out of stock", "sold out", "unavailable", "notify me"),
        "es": ("agotado", "sin stock", "no disponible"),
        "fr": ("rupture de stock", "epuise", "indisponible"),
        "de": ("ausverkauft", "nicht verfugbar", "vergriffen"),
        "pt": ("esgotado", "indisponivel"),
        "it": ("esaurito", "non disponibile"),
        "nl": ("uitverkocht", "niet op voorraad"),
        "pl": ("niedostępny", "wyprzedany", "brak w magazynie"),
        "sv": ("slutsåld", "slut i lager", "ej tillgänglig"),
        "da": ("udsolgt", "ikke på lager"),
        "nb": ("utsolgt", "ikke på lager"),
        "tr": ("tükendi", "stokta yok"),
    },
    "preorder": {
        "en": ("pre order", "preorder", "backorder", "coming soon"),
        "es": ("reserva", "pre venta", "preventa"),
        "fr": ("precommande", "pre commande"),
        "de": ("vorbestellung", "vorbestellen"),
        "pt": ("pre venda", "encomenda"),
        "it": ("preordine", "pre ordine"),
        "nl": ("voorbestellen", "pre order"),
        "pl": ("przedsprzedaż", "zamówienie przedpremierowe"),
        "sv": ("förbeställ", "förbeställning"),
        "da": ("forudbestil", "forudbestilling"),
        "nb": ("forhåndsbestill",),
        "tr": ("ön sipariş",),
    },
    "add_to_cart": {
        "en": ("add to cart", "add to bag", "add to basket", "buy now",
               "buy it now", "shop now", "order now", "proceed to checkout"),
        "es": ("anadir al carrito", "agregar al carrito", "anadir a la cesta",
               "comprar ahora"),
        "fr": ("ajouter au panier", "acheter maintenant"),
        "de": ("in den warenkorb", "jetzt kaufen", "in den einkaufswagen"),
        "pt": ("adicionar ao carrinho", "comprar agora"),
        "it": ("aggiungi al carrello", "acquista ora"),
        "nl": ("in winkelwagen", "toevoegen aan winkelwagen", "nu kopen"),
        "pl": ("dodaj do koszyka", "kup teraz"),
        "sv": ("lägg i varukorgen", "köp nu"),
        "da": ("læg i kurv", "køb nu"),
        "nb": ("legg i handlekurv", "kjøp nå"),
        "tr": ("sepete ekle", "hemen al"),
    },
    "reviews": {
        "en": ("review", "reviews", "rating", "ratings", "testimonial",
               "customers say"),
        "es": ("opinion", "opiniones", "resena", "resenas", "valoracion",
               "valoraciones"),
        "fr": ("avis", "evaluation", "evaluations"),
        "de": ("bewertung", "bewertungen", "rezension", "rezensionen"),
        "pt": ("avaliacao", "avaliacoes", "opiniao", "opinioes"),
        "it": ("recensione", "recensioni", "valutazione"),
        "nl": ("beoordeling", "beoordelingen", "recensie", "recensies"),
        "pl": ("opinia", "opinie", "opinii", "recenzja", "recenzje", "recenzji",
               "ocena", "oceny", "ocen"),
        "sv": ("recension", "recensioner", "omdöme", "omdömen", "betyg"),
        "da": ("anmeldelse", "anmeldelser", "bedømmelse"),
        "nb": ("anmeldelse", "anmeldelser", "vurdering"),
        "tr": ("yorum", "yorumlar", "yorumları", "yorumlarımız", "değerlendirme",
               "değerlendirmeler", "değerlendirmeleri", "puan", "puanı"),
    },
    "faq": {
        "en": ("faq", "faqs", "frequently asked", "common questions"),
        "es": ("preguntas frecuentes",),
        "fr": ("questions frequentes", "foire aux questions"),
        "de": ("haufige fragen", "haufig gestellte fragen"),
        "pt": ("perguntas frequentes",),
        "it": ("domande frequenti",),
        "nl": ("veelgestelde vragen",),
        "pl": ("najczęściej zadawane pytania",),
        "sv": ("vanliga frågor",),
        "da": ("ofte stillede spørgsmål",),
        "nb": ("ofte stilte spørsmål",),
        "tr": ("sıkça sorulan sorular",),
    },
    "compare": {
        "en": ("compare", "comparison", "side by side"),
        "es": ("comparar", "comparacion", "comparativa"),
        "fr": ("comparer", "comparaison", "comparatif"),
        "de": ("vergleichen", "vergleich"),
        "pt": ("comparar", "comparacao"),
        "it": ("confronta", "confronto"),
        "nl": ("vergelijken", "vergelijking"),
        "pl": ("porównaj", "porównanie"),
        "sv": ("jämför", "jämförelse"),
        "da": ("sammenlign", "sammenligning"),
        "nb": ("sammenlign", "sammenligning"),
        "tr": ("karşılaştır", "karşılaştırma"),
    },
    # A catalogue that quotes on request is not a catalogue that hid its
    # prices. Industrial, medical, wholesale, made-to-order and regulated
    # sellers deliberately publish no number, and reporting that as "the price
    # is locked inside an image" is a confident wrong answer about a design
    # decision. Detected so the pricing rules can tell the two apart.
    "quote_request": {
        "en": ("request a quote", "request quote", "get a quote", "request pricing",
               "contact us for pricing", "contact us for a price", "call for price",
               "call for pricing", "price on application", "price on request",
               "poa", "enquire for price", "inquire for price", "request a demo",
               "contact sales", "talk to sales", "speak to sales", "get a demo",
               "custom quote", "ask for a quote", "quote on request"),
        "es": ("solicitar presupuesto", "pedir presupuesto", "precio bajo consulta",
               "consultar precio", "contactar con ventas"),
        "fr": ("demander un devis", "demande de devis", "prix sur demande",
               "nous consulter", "contacter le service commercial"),
        "de": ("angebot anfordern", "preis auf anfrage", "auf anfrage",
               "vertrieb kontaktieren"),
        "pt": ("solicitar orcamento", "pedir orcamento", "preco sob consulta",
               "consultar preco"),
        "it": ("richiedi un preventivo", "preventivo su richiesta",
               "prezzo su richiesta"),
        "nl": ("offerte aanvragen", "prijs op aanvraag"),
        "pl": ("zapytaj o cenę", "wycena", "cena na zapytanie"),
        "sv": ("begär offert", "pris på förfrågan"),
        "da": ("anmod om tilbud", "pris på forespørgsel"),
        "nb": ("be om tilbud", "pris på forespørsel"),
        "tr": ("teklif isteyin", "fiyat için arayın"),
    },
}

#: Phrases that contain a concept's vocabulary but do not mean the concept.
#: "Return to top" is a scroll link, not a returns policy; "return on
#: investment" and "content delivery network" belong to a consultancy's copy,
#: not a storefront's. Left in, they make a rule suppress on a real shop that
#: only has a back-to-top link, and fire on a B2B site that sells no goods -
#: both directions wrong. Matched phrases are removed before the concept
#: patterns run, so only a genuine mention survives.
#: Payment methods. Added because the payment question used to be resolved
#: against ``add_to_cart``: a page with a cart button "answered" what payment
#: methods are accepted, which is a category error, not a weak match. A
#: question must be resolved against its own concept or not at all.
VOCABULARY["payment"] = {
    "en": ("payment method", "payment methods", "we accept", "accepted cards",
           "pay with", "pay by", "credit card", "debit card", "gift card",
           "cash on delivery", "pay on delivery", "instalments", "installments"),
    "es": ("metodo de pago", "metodos de pago", "formas de pago", "aceptamos",
           "tarjeta de credito", "tarjeta de debito", "contra reembolso", "plazos"),
    "fr": ("moyen de paiement", "moyens de paiement", "mode de paiement",
           "nous acceptons", "carte bancaire", "carte de credit", "paiement a la livraison",
           "paiement en plusieurs fois"),
    "de": ("zahlungsmethode", "zahlungsmethoden", "zahlungsarten", "wir akzeptieren",
           "kreditkarte", "ec-karte", "nachnahme", "ratenzahlung"),
    "pt": ("metodo de pagamento", "metodos de pagamento", "formas de pagamento",
           "aceitamos", "cartao de credito", "cartao de debito", "pagamento na entrega"),
    "it": ("metodo di pagamento", "metodi di pagamento", "modalita di pagamento",
           "accettiamo", "carta di credito", "carta di debito", "pagamento alla consegna"),
    "nl": ("betaalmethode", "betaalmethoden", "betaalwijze", "wij accepteren",
           "creditcard", "pinpas", "achteraf betalen", "rembours"),
    "pl": ("metoda platnosci", "metody platnosci", "sposoby platnosci", "akceptujemy",
           "karta kredytowa", "karta platnicza", "platnosc przy odbiorze", "raty"),
    "sv": ("betalningsmetod", "betalningsmetoder", "betalsatt", "vi accepterar",
           "kreditkort", "betalkort", "postforskott", "delbetalning"),
    "da": ("betalingsmetode", "betalingsmetoder", "vi accepterer", "kreditkort",
           "betalingskort", "afbetaling"),
    "nb": ("betalingsmetode", "betalingsmetoder", "vi aksepterer", "kredittkort",
           "betalingskort", "delbetaling"),
    "tr": ("odeme yontemi", "odeme yontemleri", "odeme secenekleri", "kabul ediyoruz",
           "kredi karti", "banka karti", "kapida odeme", "taksit"),
}

#: The *named things* a payment answer consists of. Kept separate from the
#: `payment` topic vocabulary on purpose: "payment method" is a topic marker
#: and appears in privacy statements, event bookings and terms of use, while an
#: instrument or an acceptance statement is what an answer to "what payment
#: methods are accepted?" actually contains. Requiring both is what turns a
#: keyword hit into evidence.
VOCABULARY["payment_instrument"] = {
    "en": ("credit card", "credit cards", "debit card", "debit cards",
           "credit/debit card", "credit/debit cards", "credit or debit card",
           "credit and debit card", "credit and debit cards",
           "visa", "mastercard", "maestro", "amex",
           "american express", "paypal", "apple pay", "google pay", "upi",
           "net banking", "netbanking", "cash on delivery", "bank transfer",
           "gift card", "klarna", "accepted cards",
           "instalments", "installments", "emi"),
    "es": ("tarjeta de credito", "tarjeta de debito", "visa", "mastercard",
           "paypal", "contra reembolso", "transferencia bancaria", "bizum", "tarjeta regalo"),
    "fr": ("carte bancaire", "carte de credit", "carte bleue", "visa",
           "mastercard", "paypal", "virement bancaire", "paiement a la livraison", "carte cadeau"),
    "de": ("kreditkarte", "ec-karte", "girocard", "visa", "mastercard", "paypal",
           "sofort", "giropay", "rechnung", "nachnahme", "uberweisung", "geschenkkarte"),
    "pt": ("cartao de credito", "cartao de debito", "visa", "mastercard",
           "paypal", "pix", "boleto", "transferencia bancaria"),
    "it": ("carta di credito", "carta di debito", "visa", "mastercard", "paypal",
           "bonifico bancario", "contrassegno"),
    "nl": ("ideal", "creditcard", "pinpas", "bancontact", "paypal", "visa",
           "mastercard", "achteraf betalen", "overboeking"),
    "pl": ("blik", "przelewy24", "karta kredytowa", "karta platnicza", "paypal",
           "visa", "mastercard", "przelew bankowy", "za pobraniem"),
    "sv": ("swish", "klarna", "kreditkort", "betalkort", "visa", "mastercard",
           "faktura", "bankoverforing"),
    "da": ("dankort", "mobilepay", "kreditkort", "visa", "mastercard", "faktura",
           "bankoverforsel"),
    "nb": ("vipps", "kredittkort", "visa", "mastercard", "faktura",
           "bankoverforing"),
    "tr": ("kredi karti", "banka karti", "visa", "mastercard", "havale",
           "kapida odeme", "taksit"),
}

#: Constructions that state a method is *available for buying*. This is the
#: half that was missing: an instrument name on its own appears in refund
#: anecdotes, transaction histories and privacy notices, so "Credit/Debit card"
#: was accepted as an answer to "what payment methods are accepted?" from the
#: sentence "I purchased an article at the store and paid through a
#: Credit/Debit card. It was returned for a refund." Past-tense narration
#: ("paid by", "was charged") is deliberately absent - only a present statement
#: of what the site takes qualifies.
VOCABULARY["payment_acceptance"] = {
    "en": ("we accept", "we also accept", "we take", "accepted payment method",
           "accepted payment methods", "payment methods accepted",
           "payment method accepted", "payment options", "payment methods we",
           "forms of payment", "methods of payment", "modes of payment",
           "you can pay", "you may pay", "customers can pay", "pay with",
           "pay by", "pay using", "payable by", "payable using",
           "cards accepted", "accepted here", "is accepted", "are accepted",
           "we support", "available payment"),
    "es": ("aceptamos", "formas de pago", "metodos de pago", "medios de pago",
           "puedes pagar", "puede pagar", "se aceptan"),
    "fr": ("nous acceptons", "moyens de paiement", "modes de paiement",
           "vous pouvez payer", "sont acceptes", "est accepte"),
    "de": ("wir akzeptieren", "zahlungsarten", "zahlungsmethoden",
           "sie konnen bezahlen", "werden akzeptiert", "zahlungsmoglichkeiten"),
    "pt": ("aceitamos", "formas de pagamento", "metodos de pagamento",
           "pode pagar", "sao aceitos"),
    "it": ("accettiamo", "metodi di pagamento", "modalita di pagamento",
           "puoi pagare", "sono accettati"),
    "nl": ("wij accepteren", "betaalmethoden", "betaalmogelijkheden",
           "u kunt betalen", "worden geaccepteerd"),
    "pl": ("akceptujemy", "metody platnosci", "sposoby platnosci",
           "mozesz zaplacic", "sa akceptowane"),
    "sv": ("vi accepterar", "betalningsmetoder", "betalsatt", "du kan betala"),
    "da": ("vi accepterer", "betalingsmetoder", "du kan betale"),
    "nb": ("vi aksepterer", "betalingsmetoder", "du kan betale"),
    "tr": ("kabul ediyoruz", "odeme yontemleri", "odeme secenekleri",
           "ile odeyebilirsiniz"),
}

#: Contexts in which a payment instrument is named for some other reason. Any
#: of these inside the quotation disqualifies it, because the sentence is about
#: a refund, a record, a booking or an account rather than about what the site
#: takes at checkout.
VOCABULARY["payment_off_context"] = {
    "en": ("refund", "refunds", "refunded", "returned for", "return the item",
           "reimburse", "reimbursement", "chargeback", "charge back",
           "credited back", "credit note", "transaction history",
           "order history", "billing history", "statement of account",
           "was charged", "were charged", "paid through", "paid by",
           "paid with", "i purchased", "we collect", "we will collect",
           "personal data", "booking", "event", "museum", "donation"),
    "es": ("reembolso", "devolucion", "historial de transacciones", "reserva"),
    "fr": ("remboursement", "retour", "historique des transactions", "reservation"),
    "de": ("ruckerstattung", "retoure", "transaktionsverlauf", "buchung"),
    "pt": ("reembolso", "devolucao", "historico de transacoes", "reserva"),
    "it": ("rimborso", "reso", "storico transazioni", "prenotazione"),
    "nl": ("terugbetaling", "retour", "transactiegeschiedenis", "boeking"),
    "pl": ("zwrot", "historia transakcji", "rezerwacja"),
    "sv": ("aterbetalning", "retur", "transaktionshistorik", "bokning"),
    "da": ("refusion", "retur", "transaktionshistorik", "booking"),
    "nb": ("refusjon", "retur", "transaksjonshistorikk", "booking"),
    "tr": ("iade", "geri odeme", "islem gecmisi", "rezervasyon"),
}

#: Framing that makes a sentence a supposition rather than a statement. A page
#: whose *subject matter* is commerce writes about stock, returns and delivery
#: constantly without stating any terms of its own - "a good POS tells you when
#: something is about to run out of stock" is advice, and it was cited as a
#: product's availability. The distinction is not vocabulary but mood: what a
#: reader would do, could see, should consider, versus what this seller does.
VOCABULARY["hypothetical"] = {
    "en": ("when something", "when a customer", "when you", "if you", "if a ",
           "about to run", "could be", "would be", "should be", "might be",
           "can help", "helps you", "lets you", "allows you", "you can see",
           "for example", "such as when", "imagine", "suppose", "learn how",
           "how to", "tips for", "best practices", "guide to"),
    "es": ("cuando usted", "si usted", "por ejemplo", "como cuando",
           "aprende a", "consejos para", "guia para"),
    "fr": ("lorsque vous", "si vous", "par exemple", "apprenez a",
           "conseils pour", "guide pour"),
    "de": ("wenn sie", "falls sie", "zum beispiel", "erfahren sie",
           "tipps fur", "leitfaden"),
    "pt": ("quando voce", "se voce", "por exemplo", "aprenda a",
           "dicas para", "guia para"),
    "it": ("quando tu", "se tu", "ad esempio", "scopri come",
           "consigli per", "guida a"),
    "nl": ("wanneer u", "als u", "bijvoorbeeld", "ontdek hoe",
           "tips voor", "gids voor"),
    "pl": ("kiedy ty", "jesli ty", "na przyklad", "dowiedz sie",
           "wskazowki", "przewodnik"),
    "sv": ("nar du", "om du", "till exempel", "lar dig",
           "tips for", "guide till"),
    "da": ("nar du", "hvis du", "for eksempel", "laer hvordan",
           "tips til", "guide til"),
    "nb": ("nar du", "hvis du", "for eksempel", "laer hvordan",
           "tips til", "guide til"),
    "tr": ("oldugunda", "eger siz", "ornegin", "nasil yapilir",
           "ipuclari", "rehberi"),
}

#: The units a shipping or returns *term* is measured in. A policy states a
#: quantity: thirty days, 2-5 business days, free over 2,000. A sentence that
#: mentions the topic and carries no quantity is a mention, and the previous
#: test - "the window contains a digit anywhere" - was satisfied by the "2" in
#: a courier's product name.
VOCABULARY["policy_unit"] = {
    "en": ("day", "days", "week", "weeks", "month", "months", "year", "years",
           "business day", "working day", "hour", "hours", "free", "no charge",
           "no cost", "no extra cost", "complimentary", "unlimited"),
    "es": ("dia", "dias", "semana", "semanas", "mes", "meses", "ano", "anos",
           "habiles", "gratis", "gratuito", "gratuita", "sin coste"),
    "fr": ("jour", "jours", "semaine", "semaines", "mois", "an", "ans",
           "ouvrable", "ouvrables", "gratuit", "gratuite", "sans frais"),
    "de": ("tag", "tage", "tagen", "woche", "wochen", "monat", "monate",
           "jahr", "jahre", "werktag", "werktage", "kostenlos", "gratis"),
    "pt": ("dia", "dias", "semana", "semanas", "mes", "meses", "ano", "anos",
           "uteis", "gratis", "gratuito", "gratuita", "sem custo"),
    "it": ("giorno", "giorni", "settimana", "settimane", "mese", "mesi",
           "anno", "anni", "lavorativi", "gratis", "gratuito", "gratuita"),
    "nl": ("dag", "dagen", "week", "weken", "maand", "maanden", "jaar",
           "jaren", "werkdag", "werkdagen", "gratis", "kosteloos"),
    "pl": ("dzien", "dni", "tydzien", "tygodnie", "miesiac", "miesiecy",
           "rok", "lat", "robocze", "darmowa", "bezplatnie", "gratis"),
    "sv": ("dag", "dagar", "vecka", "veckor", "manad", "manader", "ar",
           "arbetsdagar", "gratis", "kostnadsfri", "fri frakt"),
    "da": ("dag", "dage", "uge", "uger", "maned", "maneder", "ar",
           "hverdage", "gratis", "uden beregning"),
    "nb": ("dag", "dager", "uke", "uker", "maned", "maneder", "ar",
           "virkedager", "gratis", "uten kostnad"),
    "tr": ("gun", "gunu", "hafta", "ay", "yil", "is gunu", "ucretsiz",
           "bedava", "masrafsiz"),
}

ANTI_PHRASES: Dict[str, Tuple[str, ...]] = {
    "payment": (
        # A privacy or terms page discussing how payment data is handled is not
        # a statement of which methods are accepted.
        "payment data", "payment information is processed", "payment processor",
        "payment service provider", "payment card industry",
    ),
    "returns": (
        "return to top", "return to the top", "back to top", "return to shop",
        "return to store", "return to home", "return to homepage",
        "return to previous", "return on investment", "returns on investment",
        "carriage return", "return to search", "return visit", "returning customer",
        "exchange rate", "exchange server", "stock exchange",
    ),
    "shipping": (
        # Return-window phrasing. "…within 365 days of delivery…" is a
        # statement about returns that happens to contain a shipping word, and
        # quoting it as the site's answer to "where does this ship to, and what
        # does it cost?" shows the reader a sentence that answers neither.
        "days of delivery", "days from delivery", "of delivery, unused",
        "after delivery", "from the delivery date", "since delivery",
        "upon delivery", "on delivery date",
        "content delivery network", "project delivery", "service delivery",
        "delivery model", "delivery team", "delivery manager", "delivery pipeline",
        "continuous delivery", "delivery of care", "care delivery",
        "course delivery", "delivery method for training",
    ),
    "reviews": (
        "energy rating", "efficiency rating", "credit rating", "rating agency",
        "peer review", "peer reviewed", "peer-reviewed", "code review",
        "review of the literature", "literature review", "annual review",
        "performance review", "under review",
    ),
    "compare": (
        "compare the market", "comparison to last year", "by comparison",
        "in comparison", "compared to last",
    ),
}

_COMBINING = re.compile(r"[̀-ͯ]")
_PATTERN_CACHE: Dict[str, "re.Pattern"] = {}
_ANTI_CACHE: Dict[str, Optional["re.Pattern"]] = {}


def fold(text: str) -> str:
    """Lowercase and strip diacritics so 'Envío' matches 'envio'."""
    decomposed = unicodedata.normalize("NFKD", text or "")
    return _COMBINING.sub("", decomposed).lower()


def _compile_phrases(phrases: Iterable[str]) -> Optional["re.Pattern"]:
    """Build one alternation over ``fold``-ed phrases.

    Folding the vocabulary here (rather than expecting each entry to be
    pre-folded) is what lets the tables be written in ordinary orthography -
    ``sıkça sorulan sorular``, ``återbetalning``, ``najczęściej`` - and still
    match the folded page text.
    """
    folded = sorted({fold(p) for p in phrases if p}, key=len, reverse=True)
    if not folded:
        return None
    alternation = "|".join(re.escape(p).replace(r"\ ", r"[\s\-]+") for p in folded)
    return re.compile(r"(?<![\w])(?:" + alternation + r")(?![\w])")


def _pattern(concept: str) -> "re.Pattern":
    """One regex per concept, across every supported language."""
    cached = _PATTERN_CACHE.get(concept)
    if cached is not None:
        return cached
    compiled = _compile_phrases(
        phrase for terms in VOCABULARY.get(concept, {}).values() for phrase in terms)
    if compiled is None:
        compiled = re.compile(r"(?!x)x")  # matches nothing
    _PATTERN_CACHE[concept] = compiled
    return compiled


def _anti_pattern(concept: str) -> Optional["re.Pattern"]:
    if concept in _ANTI_CACHE:
        return _ANTI_CACHE[concept]
    compiled = _compile_phrases(ANTI_PHRASES.get(concept, ()))
    _ANTI_CACHE[concept] = compiled
    return compiled


def mentions(concept: str, text: str) -> bool:
    """True when the text mentions the concept in any supported language."""
    folded = fold(text)
    anti = _anti_pattern(concept)
    if anti is not None:
        folded = anti.sub(" ", folded)
    return bool(_pattern(concept).search(folded))


def _fold_with_offsets(text: str) -> Tuple[str, List[int]]:
    """Fold, keeping a map from each folded index back to the original index.

    :func:`fold` is not length-preserving - NFKD splits "é" into two code
    points and the combining mark is then dropped - so a match found in folded
    text cannot be sliced out of the original. Folding character by character
    and recording where each folded character came from makes the mapping
    exact, which is what lets a quotation be anchored to the phrase it claims
    to contain rather than to the top of the page.
    """
    folded: List[str] = []
    origin: List[int] = []
    for index, char in enumerate(text):
        piece = _COMBINING.sub("", unicodedata.normalize("NFKD", char)).lower()
        folded.append(piece)
        origin.extend([index] * len(piece))
    return "".join(folded), origin


def find(concept: str, text: str) -> Optional[Tuple[int, int, str]]:
    """Locate the concept in ``text``: ``(start, end, matched_phrase)`` or None.

    Coordinates are into the *original* text, so the caller can quote the real
    words, diacritics and all. Anti-phrases are blanked with spaces of equal
    length rather than substituted, so masking them cannot shift the offsets of
    everything after them.
    """
    if not text:
        return None
    folded, origin = _fold_with_offsets(text)
    anti = _anti_pattern(concept)
    if anti is not None:
        folded = anti.sub(lambda m: " " * (m.end() - m.start()), folded)
    match = _pattern(concept).search(folded)
    if match is None:
        return None
    start = origin[match.start()] if match.start() < len(origin) else 0
    end = (origin[match.end() - 1] + 1) if match.end() - 1 < len(origin) else len(text)
    return start, end, text[start:end]


def normalize_language(lang: Optional[str]) -> str:
    """'en-IN' -> 'en'. Empty when nothing was declared."""
    if not lang:
        return ""
    return re.split(r"[-_]", str(lang).strip().lower())[0]


def language_supported(lang: Optional[str]) -> bool:
    """Is this page's prose in a language the vocabularies cover?

    An undeclared language is treated as supported: most undeclared pages are
    English, and the concepts are also matched language-agnostically, so the
    cost of being wrong is one soft finding rather than a missed audit.
    """
    code = normalize_language(lang)
    return (not code) or code in SUPPORTED_LANGUAGES


def concepts() -> List[str]:
    return sorted(VOCABULARY)


def languages_for(concept: str) -> Iterable[str]:
    return VOCABULARY.get(concept, {}).keys()
