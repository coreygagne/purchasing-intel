# Purchasing Research: Phase 1

A research tool for Midcontinent Terminal (Thunder Bay) that helps anyone find a better deal on almost any
item without giving up essential quality, reliability or safety. Type a product name, model number, plain
description or product link. The tool asks a few optional questions where the answer would change the
results, then searches Thunder Bay first and works outward (Northwestern Ontario, Canada, the US, overseas)
across the buying channels that fit the item: local suppliers, distributors, dealers, manufacturers,
wholesale/trade, B2B marketplaces, used listings, auctions and completed sales. It follows the leads it finds,
lists suppliers with sourced contact details, and shows a sourced comparison: the best-supported option first,
the lowest comparable price and the best overall value, picks by channel where the evidence supports them,
the market value range, what each option really costs for your quantity, and what was and wasn't covered.

It is a research tool, not a chatbot, and it never invents results. Every price shows where it came from and
when, and each number carries a mark:

| Mark | Meaning |
|---|---|
| **Quoted** | Stated by the source: schema.org price data on the supplier's page, a Google Shopping listing, or (with AI on) seller-page text whose exact wording, including the model number next to the price, was verified. |
| **Snippet** | Seen only in a search-result snippet. Possibly outdated; open the page to confirm. Snippet prices never win "lowest" when a better-evidenced price exists. |
| **Calculated** | Arithmetic on quoted values: unit price, currency conversion (Bank of Canada rate), order totals. |
| **Estimated** | Uses *your* stated assumptions (import shipping, duty %, surtax %, brokerage). Nothing is assumed for you. |
| **Quote required** | The supplier doesn't publish a price ("call for price", "sign in to see price"). |

If no search provider is configured, the app shows setup steps and refuses to research. There is no demo
mode and no offline fallback.

---

## Quick start

**New to this? Follow [GETTING-STARTED.md](GETTING-STARTED.md)**: plain-language steps, no coding.

Requirements: Python 3.11+ and internet access to the hosts listed under [Network](#network-access).

- **Mac:** double-click `Start Purchasing Research.command`. It needs Python 3.11+ from python.org, and opens
  the download page if it's missing. It sets up `.venv` on the first run, starts the app and opens the browser.
- **Windows:** double-click `run.bat`. It installs Python with winget if it's missing, sets up `.venv` on the
  first run, starts the app and opens the browser.
- **Linux (or a Mac terminal):** run `./run.sh`.
- **Updating:** download the new ZIP from GitHub and start the app as usual. The starter finds the download in
  `~/Downloads` (the zip, or the folder Safari unzips it to), asks, and copies it over the install. It keeps
  `.env`, `data/` and `.venv/` and mirrors `app/`, `scripts/` and `tests/` (`scripts/update_from_download.py`,
  tested in `tests/test_updater.py`).

The app runs at http://127.0.0.1:8000. With no key configured, it shows a setup screen where you paste an
Anthropic key (and optionally a Tavily key). The key is checked with Anthropic using a free model-list call,
then saved to `.env` on this computer. It is never sent back to the browser. Keys can only be saved from the
computer running the app, from the app's own page. You can also edit `.env` directly (see `.env.example`).
The badge at top right names the active search, e.g. "Ready: Anthropic web search + AI reading".

**Low-cost defaults.** The app is set up to spend little:
- **Model:** Claude Haiku 5.5 (US$0.10 / US$0.50 per million input/output tokens).
- **Depth:** Quick is preselected.
- **Monthly limit:** the app refuses new research once the estimated Anthropic spend for the month reaches
  `PI_MONTHLY_BUDGET_USD` (default US$10). This month's spend is shown under the search bar, and each
  research shows its estimated cost.

Estimated cost per research with only an Anthropic key (Anthropic web search):
- about US$0.10–0.15 for Quick (8 to 11 searches) and US$0.17–0.27 for Standard (14 to 22), so the US$10
  default covers roughly 40–90 researches a month;
- most of it is the US$0.01 fee per web search. An expensive or higher-risk item is searched one level deeper
  than chosen (see "What a research does"), which costs more.

These figures are estimates from the per-search costs and token counts measured in earlier live runs,
priced for Haiku; the multi-round search plan hasn't been measured live yet. With Tavily for search the
Anthropic spend was about US$0.01 per research. Each research shows its own estimate.

For stronger reading, set `PI_ANTHROPIC_MODEL`. Only the Opus Quick figure was measured live:

| Model | Quick | Standard |
|---|---|---|
| `claude-sonnet-5-5` | about US$0.60–0.80 (estimate) | about US$1.00–1.50 (estimate) |
| `claude-opus-5-5` | about US$1.00–1.40 (estimate; US$0.72 measured with the earlier 6-search plan) | about US$1.80–2.80 (estimate) |

Also set a spend limit in the Anthropic Console: Anthropic enforces it, so it holds even if the app's
estimate is off. Adding a Tavily key (free plan) moves searching off Anthropic.

**The app has no login in Phase 1.** It binds to `127.0.0.1` (this computer only) by default. Only set
`HOST=0.0.0.0` on a trusted internal network, or behind your company's sign-in proxy.

---

## Search providers, keys and costs

At least one search provider is required: Tavily, SerpApi, or an Anthropic key (Anthropic web search).
With several keys set, the order is Tavily, then SerpApi, then Anthropic, unless `PI_SEARCH_PROVIDER` says
otherwise. Prices below are from public pricing pages and third-party
summaries checked on 2026-10-20. **Verify on each vendor's site before committing; they change.**

| Service | Needed? | What it adds | Free tier | Paid (as published) |
|---|---|---|---|---|
| **Tavily** (`TAVILY_API_KEY`), https://app.tavily.com | Recommended primary | Web search across manufacturers, distributors, marketplaces, reviews, forums; returns page text | 1,000 credits/month, no card | ~$30/mo for 4,000 credits; pay-as-you-go ~US$0.008/credit |
| **SerpApi** (`SERPAPI_API_KEY`), https://serpapi.com | Optional (or the only provider) | Google Shopping **Canada** listings with structured prices, ratings and delivery terms; Google web results if Tavily isn't set | 250 searches/month | from ~US$25/mo for 1,000 searches |
| **Anthropic Claude** (`ANTHROPIC_API_KEY`), https://console.anthropic.com | Optional | Understands plain-language requests, extracts prices from page text, summarizes reviews. Every extracted fact is checked word-for-word against the source; failures are discarded and counted. | none | Default Claude Haiku 5.5: US$0.10 / US$0.50 per million input/output tokens. Claude Sonnet 5.5 US$2 / US$10; Claude Opus 5.5 US$4 / US$20 |
| **Anthropic web search** (same `ANTHROPIC_API_KEY`) | Alternative primary | Claude's server-side `web_search` tool (`web_search_20250305`, which returns citations). Anthropic runs the search, so only `api.anthropic.com` must be reachable. Used automatically when no Tavily/SerpApi key is set, or force it with `PI_SEARCH_PROVIDER=anthropic`. Snippets are built only from the citations' verbatim `cited_text`. | none | US$10 per 1,000 searches plus tokens for the results read. Measured: about US$0.09 per query on Claude Opus 5.5, about US$0.72 for a quick research including AI reading |
| **Bank of Canada Valet** | Built in | Daily FX rates (USD, EUR, CNY…→CAD) | free, no key | n/a |
| **Anthropic web fetch** (same `ANTHROPIC_API_KEY`) | Automatic fallback, on by default | Reads a supplier page or the Bank of Canada rate **only when this server can't connect to it** (DNS, network or timeout). See "Fallback reading" below. | none | Tokens only (the page text is billed as input). Measured on Claude Opus 5.5: see Status. `PI_FETCH_MODEL=claude-haiku-5-5` costs far less per page |

**Cost per research** (Tavily: basic search = 1 credit, advanced = 2):

| Depth | Web searches (round 1 + follow-ups) | Tavily credits | + SerpApi | Typical use |
|---|---|---|---|---|
| Quick (preselected) | 8 + up to 3 | 8–11 | 1 Shopping + 1 Maps | fast price check |
| Standard | 14 + up to 8 | 14–22 | 1 Shopping + 2 Maps | normal purchase |
| Deep | 20 + up to 12 + up to 8, advanced | 40–80 | 1 Shopping + 3 Maps | larger or riskier buys |

Follow-up rounds stop early when a round finds no new supplier or price. An expensive item (about CAD 5,000
or more, from your budget or the snippet prices) or a higher-risk category (vehicles, machinery, property,
PPE, lifting and high-voltage items) is searched one level deeper than chosen, and the result says why. So
the Tavily free tier covers roughly 90–120 Quick or 45–70 Standard researches per month, and the SerpApi
free tier 60–125 researches. Pay-as-you-go Tavily works out to about US$0.11–0.18 per Standard research. With AI on, add roughly 15–25k input tokens and 2–8k output tokens
(including thinking) per research. That's about **US$0.01 on the default Claude Haiku 5.5**, or
US$0.10–0.30 on Claude Opus 5.5. This is an estimate; each research's details show its tokens and estimated
cost. Use `PI_ANTHROPIC_MODEL` / `PI_ANTHROPIC_EFFORT` to change it.

Re-running a search for the same item within 12 hours (`DUPLICATE_WINDOW_HOURS`) offers the saved result
first, so credits aren't spent by accident. Changing import assumptions recalculates without searching.

Supplier pages are also read directly (no credits) for schema.org price data and contact details. This
respects robots.txt and is limited to `FETCH_MAX_PAGES` (10) product pages for Quick, 1.5x for Standard and 2x
for Deep, plus 2/5/8 local or regional suppliers' own home and contact pages for missing emails. Many large retailers block automated reads; when that
happens the source shows "page read: no (blocked)" and the price relies on search data.

**Safety:** pasted links and search results are fetched only if they meet all of these, checked on every
redirect hop:
- http(s) only, on ports 80/443, with no embedded credentials;
- the host resolves (via the server's DNS) to public internet addresses only, so localhost, the office LAN and
  cloud-metadata addresses are refused.

If the server can't resolve a host name, that page isn't read. On proxy-only networks, where an HTTPS proxy
resolves names for the server, set `FETCH_TRUST_PROXY_DNS=true` to allow public-looking names; internal
names and IP addresses stay blocked. Each page read and each whole research job also has a time limit
(`FETCH_TIMEOUT_S`, `JOB_TIMEOUT_S`).

**Fallback reading through Anthropic web fetch** (`FETCH_VIA_ANTHROPIC=true`, needs the Anthropic key). Some
networks (a locked-down office firewall, a cloud sandbox) let the server reach `api.anthropic.com` but not
supplier sites or the Bank of Canada. Then the app asks Anthropic's server-side `web_fetch` tool to fetch the
same URL. The rules:
- It is used **only when our side couldn't connect**: the host name didn't resolve, the connection failed, or
  it timed out. A site's own answer (403 blocked, 404, login required, robots.txt "no") is final and never
  routed around.
- The site's robots.txt is fetched the same way and obeyed. If it can't be read, the page isn't read.
- At most `FETCH_VIA_ANTHROPIC_MAX` (4) pages per research. IP addresses, internal names and non-standard
  ports are refused as for direct reads.
- The tool returns the page's text, not its HTML, so there's no schema.org data. The text goes only to the
  AI reading step, where every price must be quoted word-for-word from it (the usual verification).
  Such sources show "page read: yes, as text via Anthropic web fetch".
- Anthropic's fetcher may return a **cached copy** of a page. The copy's date is shown on the source, and
  prices read from it carry that date. A copy 3 or more days older than the research is flagged and treated as
  low-confidence evidence.
- Bank of Canada data fetched this way is still parsed by the app (the AI never writes the rate). The rate
  is labelled "Bank of Canada daily exchange rate (fetched via Anthropic web fetch)". A copy whose rate is
  more than 10 days old is rejected.
- The model that issues the fetch is `PI_FETCH_MODEL` (default: `PI_ANTHROPIC_MODEL`). It only calls the
  tool; nothing it writes is used.

---

## What a research does

0. **Clarify first** (`POST /api/clarify`, free: rules only, no search or AI). At most four questions, only
   where the request leaves something open that changes the results: how much (length for cable, rope or
   hose; quantity otherwise), voltage and conductor material for cable, whether used/auction is acceptable,
   intended use, a budget for vehicles/machinery/property, and when it's needed. Every question can be
   skipped. Answers are stored per request and not asked again; skipped questions become stated
   assumptions in the result ("Quantity not given: ...").
1. **Understand the request.** It extracts model/part numbers (e.g. `2767-20`, `DCF887B`). For a pasted link
   it reads the product page (schema.org name/brand/MPN), falling back to the URL's words if the page can't
   be read. With AI on, it also suggests key specs, up to 3 extra queries and up to 3 alternative trade names
   (search terms only, never evidence). The item's category (`app/discovery.py`) decides which buying
   channels apply; channels that don't (wholesale for property, used for PPE) are listed with the reason.
2. **Search in rounds** (`app/discovery.py`).
   - Round 1: Thunder Bay first ("<item> Thunder Bay", local suppliers of the category, Yellow Pages), then
     Canadian price, wholesale/bulk and manufacturer/dealer searches (always included), reviews,
     Northwestern Ontario/Ontario suppliers, problems/recalls, used listings, B2B marketplaces (Alibaba,
     Made-in-China, Global Sources), US prices, auctions/surplus, completed sales and specs, as far as the
     depth's budget allows. Property requests search listings and completed sales instead. Google Shopping
     Canada and Google Maps local business listings (SerpApi) run alongside.
   - Later rounds follow leads: each local business's own website, suppliers seen without a price, brand
     dealer networks near Thunder Bay, manufacturers' where-to-buy pages and alternative names, using
     site-restricted searches. A round that finds no new supplier or price ends the research.
3. **Read supplier pages** for structured price, currency, availability, condition, ratings, specs and contact
   details (tel:/mailto: links, schema.org business data, page text). Local and regional suppliers without an
   email are read on their own home and contact pages.
4. **Build offers**, each labeled by evidence: page data > shopping listing > AI-verified page text > snippet.
   Quote-only suppliers are recorded as such.
5. **Check equivalence.** Exact model, different variant/kit (e.g. `2767-22` vs `2767-20`),
   compatible/aftermarket/accessory ("replacement for 2767-20", "battery for 2767-20"), or different model.
   The following are flagged and **excluded from the comparison**, but stay visible with the reason:
   - refurbished/used/open-box items (condition is read from the title or page data only);
   - price ranges and "from" prices;
   - pages listing several prices for one product (variants or sellers);
   - unconvertible currencies;
   - out-of-stock or discontinued items;
   - minimum orders above your quantity.

   Pack sizes are read from product titles only ("Socket set (28 pcs)" is one set, not 28 items). Prices are
   compared per unit only when at least two comparable listings state a pack size; listings that don't
   state one then count as single units, with a flag. Otherwise listing prices are compared.
6. **Convert currencies** with the Bank of Canada daily rate (date shown). If the rate is unavailable, foreign
   prices are excluded, not guessed.
7. **Recommend.**
   - *Lowest comparable price*: the lowest CAD price, or per-unit price when pack sizes differ, among
     comparable offers with page- or listing-level evidence. A cheaper snippet-only price is mentioned as
     "possibly lower, unverified".
   - *Best overall value*: a transparent points table, never "cheapest wins". Price (40), price evidence
     (10), supplier type (15), domestic supply (15), and availability, warranty, shipping terms and customer
     rating (5 each). Every factor shows its evidence.
8. **Surface** conflicts (e.g. page says $339.99, snippet says $349.99), outliers, gaps, recall mentions,
   wholesale/bulk/quote channels, spec differences, and Canadian import considerations.
9. **Supplier records** (`app/vendors.py`): every seller, local first, with its location (Thunder Bay,
   Northwestern Ontario/Ontario, elsewhere in Canada, US, international) and what that's based on; address,
   phone and email each copied from a named source (Google Maps listing, the supplier's own site, a directory
   listing or search text) with the date seen; products seen; price status (published, quote on request, no
   price seen); trade terms; and whether to ask for a quote. Quote-request drafts (`app/rfq.py`) are
   prepared for those suppliers; nothing is sent.
10. **Market value and true cost** (`app/market.py`): price ranges kept apart for new retail, new trade /
    wholesale, used, auction bids in progress and completed sales, each with its count, low, median (only
    from 3+ observations), high, dates, sources and differences. Order totals show unit price, the total for
    your quantity or length, shipping/duty/brokerage as quoted, your assumption or unknown, and HST
    separately (pre-tax totals are compared, since registrants recover GST/HST).
11. **Plain recommendation** (`app/picks.py`): the best-supported option first, with how it compares on total
    cost, evidence, delivery, warranty, compatibility and risk; then local, wholesale, used/auction and
    international picks only where a same-item price supports one, and what quote or information is still
    needed.
12. **Coverage report** (`app/coverage.py`): channels and markets searched with their results, distinct
    suppliers and offers, verified vs snippet-only prices, quote-only suppliers, pages that couldn't be
    reached, channels ruled out and why, rounds and why it stopped, and next steps. It reports what the
    searches found; it never claims every supplier was found or gives a completeness percentage.
13. **Save** the comparison and every observed price (supplier, price, currency, CAD, URL, timestamp, pack
   size, specs, MOQ, shipping, warranty) to SQLite for price history.

### Canadian import handling

Duty, CUSMA eligibility and surtaxes depend on the goods' **country of origin** and HS classification, which
search results rarely establish. So they are never assumed. In the Import tab you can enter your own duty %,
surtax %, import shipping and brokerage; totals using them are marked **Estimated**. The tab also explains:

- the 5% GST at the border, generally recoverable for registrants;
- Ontario HST;
- an import checklist: currency and rate, country of origin, HS classification, duty/surtax, freight and
  insurance (ask for a DDP Thunder Bay quote or the Incoterm), brokerage, taxes, delivery to Thunder Bay,
  warranty, and Canadian compliance for the category (CSA/cUL/cETL marks and ESA for electrical, CSA Z195 /
  Z94.1 / Z96 and NIOSH for PPE, Transport Canada RIV for vehicles, WHMIS for chemicals, ISED for radios,
  CRN for pressure parts). Unknown items stay unknown;
- the US-origin surtaxes in force since 2026-09-08 (15/25/50% by classification; United States Surtax Order
  (2026), CBSA Customs Notices 26-23 and 25-11);
- other-origin measures and brokerage fees;
- links to CBSA and the Canada Gazette.

That guidance text was reviewed 2026-10-20 and needs periodic re-checking (`app/import_costs.py`).
Recommendations are always based on observed prices, never on speculative import figures.

### Quality evidence

- **Ratings** from page data or Google Shopping are listed with their source and never averaged.
- **Themes** group the verbatim mentions (overheating, breakage, build quality, warranty...). A theme is
  *recurring* only when two or more independent sites mention it; one site's mention is labelled *isolated*.
  AI summary points carry the same label, counted from the sites whose quotes verified. Mentions of the
  exact model are counted separately.
- **Marketplace badges** ("Amazon's Choice", "Verified Supplier", "Trade Assurance") are flagged as the
  marketplace's own labels: they don't prove quality, that an item is genuine, or who the seller is.
- **Reported problems, praise and recall mentions** are shown as *verbatim sentences* with links, labeled by
  source type: professional review, user discussion (anecdotal), video, complaints site, government.
- **With AI on**, recurring praise, criticism and reliability issues are summarized. A point is dropped if:
  - none of its quotes is substantial (20+ characters) and found word-for-word in a cited source; or
  - it contains a number or percentage that doesn't appear in its quotes.

  The free-text note on evidence strength is labeled as AI commentary and dropped if it contains any figures.
  The tab shows how many points were dropped.
- **AI-read prices** are accepted only from seller pages, and only when the requested model number is named
  shortly before the price in the verbatim page text. They are rejected if another price, another model
  number or "related products" wording sits in between, so accessory and sibling-kit prices don't pass. The
  title, seller, pack size and condition come from the page itself, never from the AI. If the AI is slow, it
  is skipped and the search results are kept.

---

## Using the app

- **Search**: pick Quick / Standard / Deep, and optionally a quantity (used for MOQ checks and order totals).
  Answer or skip the questions that appear (all optional), then research.
- **Results**: the recommended (best-supported) option, the lowest-price and best-value cards, an "Options
  side by side" table (best value, lowest cost, local, wholesale, used/auction, international), the market
  value panel, "Watch out for" (conflicts, recalls, gaps), "Ways to pay less, and what to ask for", and what
  was assumed. Below that, the comparison table: choose **Details** on any row for the evidence text, FX and
  cost breakdown. "Not compared" lists every excluded listing with its reason.
- **Tabs**: Suppliers & quotes (local first, sourced contacts, quote drafts with "Open in email" and "Copy
  request"), Quality & reliability, Buying channels, Import & landed cost (assumptions form and import
  checklist), Coverage, Price history (chart only with ≥3 comparable observations on ≥2 days; otherwise the
  raw observations), Sources & method (queries with channel, market and round, provider errors,
  credits/tokens used, pages read, limits).
- **Save** names the comparison and pins it to the home page. **Search again** re-researches the same
  comparison and adds new price observations. **Export CSV / Excel**: the Excel file has Summary, Offers,
  Sources, Quality evidence, Price history, Suppliers, Market value, Coverage and Import & assumptions sheets.

---

## Tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q            # 178 tests; 6 live-network tests are skipped unless enabled (below)
```

**Live provider check** (real credits: about 5 Tavily credits and 3 SerpApi searches). It confirms that
each provider's current response format still parses, that a bad key is reported as such, and that one full
research completes on Tavily alone and is saved:

```bash
PI_NETWORK_TESTS=1 python -m pytest -q tests/test_live_providers.py   # keys from .env or the environment
```

Each test is skipped when its provider's key isn't set.

The tests never call real providers. They run the real HTTP, parsing and analysis code against a
**simulated web** in `tests/fakeweb.py`: fictional "Acme TX-4400" products, used only by tests. Covered:

- provider success and errors (bad key, quota 432/433, rate limit, 5xx, timeout, malformed JSON, network
  refusal);
- the full research → save → reopen → export flow;
- partial provider failure, no results, FX outage;
- conflicting prices, refurbished/variant/compatible exclusion, quote-only suppliers;
- URL input (readable and unreadable), robots.txt, the duplicate guard, assumptions recalculation and
  history charting rules;
- AI verification: fabricated prices, accessory prices, invented pack sizes, conditions and statistics, and
  review-page "offers" are all rejected;
- the code-review regression suite (`tests/test_review_fixes.py`): aftermarket pages, multi-price pages,
  decimal commas, SSRF attempts, spreadsheet formula injection, and more;
- the Anthropic web fetch fallback (`tests/test_anthropic_fetch.py`): it is used only for network failures,
  never for 403/503/robots refusals; robots.txt is obeyed; the page limit holds; a garbled Bank of Canada
  response is an error, not a rate; and an end-to-end research reads an unreachable page and the FX rate
  through it;
- browser tests of the UI (`tests/test_ui.py`, skipped if Playwright/Chromium is missing).

To click through the UI with simulated data (a red banner marks it as a test harness):

```bash
python -m tests.serve_fake --port 8765          # or --unconfigured to see the setup screen
```

**Live check with your real keys** (uses real credits; doesn't touch your database unless `--save`):

```bash
python -m scripts.smoke_test "Milwaukee 2767-20" --depth quick
```

---

## Network access

The server needs outbound HTTPS to:

- `api.tavily.com` and/or `serpapi.com` (or only `api.anthropic.com` when using Anthropic web search)
- `www.bankofcanada.ca`
- `api.anthropic.com` (if AI is on)
- supplier websites (for page reading; optional, `FETCH_PAGES=false` disables it)

If only `api.anthropic.com` is reachable, the Bank of Canada rate and up to 4 supplier pages per research
are read through Anthropic web fetch instead (see "Fallback reading" above).

The browser also loads the Archivo font from Google Fonts and falls back to a system font if blocked.

---

## Data

Everything is stored in one SQLite file, `data/purchasing.db` by default (`DATABASE_PATH`). Back it up like
any file. Tables: `searches` (recent searches, including failures), `comparisons` (saved snapshot of each
research plus your assumptions), `price_observations` (every observed price, for history), `fx_rates` (cached
Bank of Canada rates).

---

## Project layout

```
app/
  main.py          FastAPI routes, background research jobs
  research.py      workflow orchestration; analyze() is pure and re-runnable
  clarify.py       clarify-first questions, stored answers, stated assumptions
  guides.py        built-in buying guides for broad terms (radios, work lights, air compressors, safety glasses)
  discovery.py     research plan: categories, channels, markets (Thunder Bay first), follow-up rounds
  vendors.py       supplier records with sourced contacts and location tiers
  market.py        market value groups and order totals (tax shown separately)
  picks.py         plain recommendation, channel picks, side-by-side comparison
  coverage.py      what was searched, found and unreachable; next steps
  rfq.py           quote-request drafts (never sent)
  providers/       Tavily, SerpApi (Shopping, web, Google Maps), Anthropic web search, Anthropic web fetch
                   fallback (+ shared error taxonomy). Add a provider here.
  fetch.py         polite page fetcher (robots.txt, size/time limits)
  extract.py       prices, currencies, pack sizes, MOQ, warranty, schema.org parsing, model matching
  evidence.py      sources and offers with evidence labels
  analysis.py      comparability, recommendations, quality, channels, conflicts, gaps
  import_costs.py  Canadian import notes and delivered/landed cost arithmetic
  fx.py            Bank of Canada rates (cached)
  llm.py           optional Claude layer with verbatim verification
  export.py        CSV / Excel
  db.py            SQLite repository (the only module with SQL)
  static/          single-page UI (vanilla JS, no build step)
tests/             pytest suite + simulated web + UI harness
scripts/smoke_test.py   live check with real keys
```

---

## Status and limits (honest)

**Scope decision (2026-10-22): a dependable work tool, not a platform.** After an audit, the tool was
narrowed to what saves time on real purchases: finding Thunder Bay and Canadian suppliers with sourced
contacts, comparing like-for-like prices where they're published, and drafting quote requests where they
aren't. The changes:
- **Never recommended as an offer:** pages that list many ads or products ("118 ads for…", "Page 2 of 3"),
  price guides and value calculators, and news, government or school pages. Their prices stay as labelled
  market evidence. The used pick takes a fixed asking price over an auction bid in progress.
- **Vehicles, equipment, property and used items aren't ranked by price.** Listings differ in condition,
  hours or mileage, options and location, so the app lays out the listing pages and local dealers for a
  person to judge, with a before-you-buy checklist. A model year in the request ("2019 F-150") is checked
  against each listing's title.
- **Broad terms get a short built-in guide** (`app/guides.py`): radios, work lights, air compressors and
  safety glasses. It shows the main types and what each is for (click one to search for it), the 2-3
  questions that change the answer (what you use now, where, hazardous areas), a "confirm with the
  supplier" checklist that also goes into quote requests, and safety flags. It's rule-based (no AI call,
  no cost), names no products or prices, and is labelled "general guidance - verify".
- **A type is not a model.** A search such as "portable two-way radio" returns different makers' models, so
  the app gives a shortlist instead of a "best value", and keeps consumer products (camping walkie-talkies)
  out of it.
- **Live check (2026-10-22, Tavily, quick depth):** "portable two-way radio" first ranked a Best Buy camping
  walkie-talkie pack against commercial radios; it now shows a shortlist with the camping set excluded.
  "Milwaukee 2767-20" behaved as before (exact-model prices compared). "safety glasses" gave a shortlist of
  five priced options with the checklist in 8 quote drafts; it first listed "Canadian Tire Roadside
  Assistance" as an option, so shortlist options must now name the product type. Saved earlier runs re-analysed under
  the new rules: no loss of comparable prices for exact-model items.
- **Search by photo** (with the Anthropic key): the page shrinks the photo, Claude reads what it shows and the
  text printed on its label or nameplate, and you confirm or edit the suggested search before anything is
  searched. A brand or model number is kept only if it's in the text read from the photo. The photo goes only
  to Anthropic and isn't stored; each reading's cost counts in the month's spend. "Try Google Lens" opens Lens
  in a new tab to upload the photo yourself (Lens can't be connected directly: its API needs the photo posted
  publicly online first).
- **Vehicles (live check 2026-10-22, "f250 or f350 truck"):** model numbers now match however a listing writes
  them ("f250" = "F-250" = "F 250"), "X or Y" accepts either model, and vehicle searches look for the vehicles
  (each model asked for, used-vehicle sites, dealers and fleet pricing, auctions) instead of wholesale and
  manufacturer searches, which found parts shops. Parts and accessories (lift kits, bumpers) and other models
  are left off the list.
- **Where to look:** "In Thunder Bay" and "Outside Thunder Bay" toggles next to the search (both on by
  default). Thunder Bay only runs the local searches and compares only sellers placed in Thunder Bay; outside
  only skips them.
- **Listing pictures:** hovering a listing link (marked with a small frame) shows the picture from that
  listing's page or its Google Shopping entry. Pictures appear only where the app could read the page or the
  listing came from Google Shopping; there's no hover on phones.
- **Recent searches** can be cleared from the home page; saved comparisons, price history and the month's
  spend record are kept.
- **Out of scope on purpose:** price ranking for vehicles and property, worldwide coverage, deeper import
  modelling, dashboards and forecasting.

**Built and tested against the simulated web:** everything described above. An independent code review
(two rounds) found accuracy and safety issues. They were fixed and covered by regression tests
(`tests/test_review_fixes.py`), and mutation checks confirm the key tests fail if a fix is reverted. One
residual risk is accepted for Phase 1 and listed under limitations (DNS rebinding).

**Live end-to-end test (2026-10-20, Anthropic web search + Claude Opus 5.5, quick depth).** The full workflow
ran against the live provider: request → 6 real web searches → 40 real sources → evidence extraction with
verbatim checks → comparison and recommendation → saved to SQLite → shown in the UI. For "Milwaukee 2767-20":
- **Recommendation:** Amazon.ca at CAD 299.89, flagged as low-confidence evidence because the price came from
  a site search-results page ("confirm the price on the listing itself").
- **USD listings** (Walmart, eBay) were found but left out of the ranking, because the Bank of Canada rate
  couldn't be fetched from that sandbox. The app says so; no rate was guessed.
- **AI review summary:** 6 points, each with verbatim quotes and links, including Milwaukee's H96B service
  issue.

The live runs also exposed real bugs, now fixed and covered by tests using the captured real snippets:
- `web_search_20260209` returns no citations, so there is no verbatim evidence; the app uses
  `web_search_20250305`;
- results from AI-suggested queries were never treated as sellers;
- a review sentence ("more torque than my $800 Snap On") was read as a price;
- "Retail price", "Approximately C $…" and "+ $X shipping" were read as listing prices, and the eBay
  "C $235.20" format was not read at all;
- "Unavailable" wasn't treated as out of stock;
- search-results pages were treated like product pages.

**Second live run, with the Anthropic web fetch fallback (2026-10-20, same item, quick depth).** That sandbox
can reach only `api.anthropic.com`, so this run verified FX conversion and page reading through the fallback:
- **FX:** USD→CAD 1.4097 for 2026-10-19, from the Bank of Canada Valet JSON fetched via Anthropic web fetch
  and parsed by the app. USD listings (Walmart, eBay) were converted and compared this time.
- **Pages:** 10 supplier pages attempted directly; all failed DNS. Up to 4 were retried through the fallback.
  3 were read (Walmart, an eBay catalogue page, Tenaquip). Global Sources was refused by Anthropic's
  fetcher (`url_not_allowed`), and that was reported, not routed around. robots.txt was read the same way for
  each site and obeyed.
- **Evidence from fallback text:** Walmart's price (USD 246.80) was read from the fetched page text and passed
  the word-for-word check.
- **Result:** 43 sources, 14 listings, 9 comparable. Lowest and best value: eBay.ca at CAD 235.20 (verified
  from the listing text). An eBay USD 51.89 snippet from a multi-seller catalogue page was flagged
  "unusually low" and as low confidence, and kept out of the recommendation pool.
- **Found and fixed:** Anthropic's fetcher can return a **cached copy**: Walmart's page came back dated
  2026-09-24. Prices read from fallback text now carry the copy's date, and a copy 3+ days older than the
  research is flagged and drops to low confidence, so it can't be recommended as today's price. A
  fallback FX copy older than 10 days is rejected.

**First live run on the user's MacBook (2026-10-21; Tavily + Claude Haiku 5.5, quick depth).**
- **Setup:** the Mac starter, the key setup screen and Tavily all worked live. The request was
  "300 ft of 3-conductor 500 MCM copper Teck cable": 3 Tavily credits, about US$0.01 of Anthropic spend
  (estimate).
- **What it exposed:** the run recommended solexpower.ca at **CAD 8.42** as both lowest price and best
  value. That's 89% below the median (CAD 76.75), and the app flagged it but still let it win. For
  comparison, Gerrie Electric's listing for this cable is CAD 251.02 per metre (about CAD 76.51 per foot).
- **Fixed since, and covered by `tests/test_length_and_specs.py`:**
  - Prices are read per foot or metre: "/ ft", "per foot", "/ Meter", "per 1000 ft", and "sold by the
    foot" on the page. They're compared per foot, never against per-item prices, and a "300 ft of …"
    request gets an order total. A bare "/ M" is marked unclear, because in the wire trade it can mean
    per 1,000 ft.
  - Plain-language requests are checked against each listing's own wording: size (500 kcmil, 4/0 AWG,
    12/3), conductor count, copper or aluminum, and number+unit specs like 3/8 in or 50 ft. A listing that
    states a different value is excluded; aluminum armour isn't read as an aluminum conductor.
    Recommendations prefer listings that state every requested spec.
  - A price below 35% of the median of comparable listings is set aside from both recommendations, with
    a note to check it.
  - "Regular price" / "list price" amounts are no longer read as the selling price.
  - Major Canadian electrical distributors were added to the supplier list.
  - Comparisons saved by an older version are re-analysed under the current rules when opened. This uses
    the stored evidence, so it's free and runs no searches. Per-length units need the page text, so they
    apply to new searches only.
- **Second live run after the update (same request; Tavily + SerpApi Google Shopping + Haiku 5.5):**
  - Verified live: the update path (keys and saved research copied automatically), SerpApi's Google
    Shopping search, and the spec checks ("The listing states: 500 kcmil, 3-conductor").
  - The CAD 8.42 listing was no longer recommended.
  - New problem: none of the 8 comparable listings said whether its price was per foot, per metre or per
    reel. The app compared them as plain prices and recommended CAD 321.32 (57% below a CAD 747.93
    median).
  - Fixed since: when a request names a length to buy, a price that doesn't state what length it covers
    isn't compared. If no listing states one, there's no recommendation and the app says to check the
    listings or ask for a quote. A reel or spool size in the title ("250 ft reel") is read as the length
    the price covers.
- **Haiku 5.5 reading:** this run is its first live use. Its results looked usable, but one search isn't
  enough to judge the model.

**Live verification of the market research build (2026-10-22, Tavily, quick depth, AI reading off).** Run in
the cloud build sandbox, where the Tavily key comes from an environment network secret, supplier pages
can't be reached (DNS), and SerpApi and Anthropic weren't available (see below). `tests/test_live_providers.py`
passed for Tavily: a real search parses, a search limited to one site stays on it, and a full research
completes. Then two real researches, 11 Tavily credits each:
- **"Milwaukee 2767-20"**: 62 sources. Found Thunder Bay suppliers McEachern's Tool House and Nova-Pro
  Industrial Supply, with phone numbers and emails copied from their own sites and search results.
  Comparable prices: CAD 389.00 to 464.55 (4 new asking prices, all from search snippets). A 2767-22R kit
  and a 2666-20 were kept out of the comparison.
- **"300 ft of 300 MCM 3-conductor copper teck cable 1000V"**: 45 sources, 21 suppliers. These included Gescan,
  Westburne and National Cable Specialists (quote on request), EECOL, Guillevin, Nedco, Lumen, Texcan,
  Noramco and Wesco. No recommendation: no listing stated a price that could be compared for 300 ft. The
  prices seen were for other sizes, or ended in "/ M", which can mean per metre or per 1,000 ft. The result
  asks for quotes from named suppliers instead.
- **Fixed from these runs, with tests:**
  - searches used the whole request ("300 ft of …"); they now use the item;
  - the Quick plan spent two searches each on wholesale and manufacturer, crowding out reviews and other
    channels;
  - the Thunder Bay electricity utility, the IESO, a university thesis, a trade-news site, an association
    member page, a careers page and a file host holding a supplier's PDF were listed as suppliers;
  - one shop appeared twice (its site and its Facebook page; "McEachern's" vs "McEachern"; "Nova Pro" vs
    "Nova-Pro Industrial Supply Ltd");
  - a 2767-22R kit whose snippet said "Includes: (2767-20)" counted as the bare tool;
  - "available from #14 to 500 kcmil" was read as the listing's size;
  - catalogue names like "300/3C" and "3/0/3C" weren't read as sizes;
  - "$279.00 (USD)" lost its currency;
  - an email domain containing "example" was dropped as a placeholder;
  - a seller of unknown country was called "outside Canada";
  - each manufacturer site got its own where-to-buy search;
  - Gescan, Wesco, City Electric Supply, Noramco, SB Simpson and Nassau National Cable were added to the
    supplier list.
- **Still not verified live:**
  - SerpApi: Google Shopping and Google Maps. It authenticates with a URL parameter, so a header-type network
    secret can't carry its key.
  - Reading supplier pages directly: unreachable from the sandbox. Works on a normal network such as the
    Mac runs.
  - Claude reading: network secrets are never added to api.anthropic.com. It was used live on the Mac
    earlier.

**Market research build (2026-10-21): built and tested against the simulated web.**
Clarify-first questions, the multi-round search plan (Thunder Bay first, channels by category, follow-up
rounds), Google Maps local listings, contact capture, supplier records, market value groups, order totals
with HST, channel picks, quote drafts, quality themes, the import checklist and the coverage report are
covered by `tests/test_discovery.py` and `tests/test_clarify.py` (and the browser test). Not yet confirmed
against real responses:
- SerpApi's Google Maps results: no real response has been seen yet, but the parser was run on the example
  response in SerpApi's own documentation (fetched 2026-10-21) and read all four businesses' name, address,
  phone, website, category, rating and Maps link. The `ll` format (`@lat,lon,12z`) matches the docs. The
  docs warn that results aren't guaranteed to stay near the position given, so map searches also name
  "Thunder Bay ON", and a map result's own address decides whether it's local;
- site-restricted searches: Anthropic `allowed_domains` takes bare domains, as sent (checked against
  Anthropic's web search docs, 2026-10-21); Tavily `include_domains` restricts results to the listed
  domains (per LangChain's Tavily reference; Tavily's own docs site couldn't be reached); SerpApi adds
  `site:` terms;
- how often real supplier pages publish contacts in a readable form, and the per-research cost of the
  larger search plan (the figures above are estimates).

**Real-data check of the search plan (2026-10-21).** Six round-1 searches for "300 MCM 3-conductor teck
cable" were run with the development assistant's own search tool. That tool returns titles and URLs, not
page text, so this checked what the searches find and how the app classifies it, not prices:
- The local supplier search found Thunder Bay electrical distributors (EECOL Electric, MGM Electric,
  Westburne, Guillevin, Gescan, City Electric Supply), mostly through Yellow Pages business pages and trade
  news. The item search with "Thunder Bay" found no local listing for this cable.
- Yellow Pages business pages (`/bus/…/Thunder-Bay/…`) match the one-business pattern; its search pages
  don't. Kijiji category pages and Alibaba / Made-in-China showroom and search pages list many ads.
- Product pages for other sizes (10/3, 12/3, 4 AWG Teck) came back for the 300 MCM search, which the spec
  checks exclude; B2B listings were for 350 kcmil and other sizes, not 300 MCM.
- Fixed from this: trade-news pages that don't name the item are no longer followed up as suppliers;
  businesses named on a Thunder Bay directory page (or on a map listing without their own website) get a
  follow-up search by name with the item; Kijiji category and B2B showroom/search pages are treated as
  search-results pages (low confidence); "audited supplier/manufacturer" is flagged as a marketplace badge.

**Not verified live:**
- **Tavily and SerpApi from the build sandbox.** That sandbox's network policy refuses `api.tavily.com` and `serpapi.com` (proxy
  403), and no keys for them were available. Their documentation sites couldn't be opened from there, but
  search excerpts of the current docs (checked 2026-10-20) confirm two things:
  - Tavily's `country` takes a lowercase English name ("canada", as sent) and applies only to the
    `general` topic. `include_usage` returns the credits used, which the app now requests and reports.
  - SerpApi's Google Shopping results carry `product_link`, `price` and `extracted_price`. The app uses a
    direct merchant `link` when one is present and falls back to `product_link` when not.

  What is tested:
  - the parsing, error and credit code against simulated responses in their documented formats;
  - the real network-refusal path (reported as "network unreachable", no results invented);
  - a one-time retry without the optional `country` (Tavily) or `num` (SerpApi) parameter if the API rejects
    it.

  `tests/test_live_providers.py` is the one-command live check once a key and network access are available
  (see Tests).

  **Partial live check (2026-10-21).** After both hosts were allowed, the real APIs were called with an
  invalid key (no credits used):
  - Tavily's real 401 body (`{"detail": {"error": "Unauthorized: missing or invalid API key."}}`) has the
    same shape as the simulated one and is reported as "API key rejected".
  - SerpApi's real 401 ("Invalid API key…") is reported the same way, for Google Shopping and web search.
  - A full research stops after the first rejected request and shows the reason.

  Parsing of real *successful* results still needs a valid key.
- Direct (non-fallback) Bank of Canada and supplier-page reads: the code is the same as in tests, but that
  sandbox can't reach those sites. On a normal office network they are used first and the fallback stays idle.

**Measured cost (Claude Opus 5.5, quick depth = 3 planned + 3 AI-suggested searches):**
- First run: about 93k input and 14k output tokens plus 6 web searches, roughly US$0.72 per research.
- Second run, with the fallback: about US$1.01. That's US$0.55 for search, US$0.19 for AI planning and
  reading, and US$0.26 for 9 web fetches (62k input tokens: 4 pages, their 4 robots.txt files, 1 FX rate).
  That's about US$0.06 per fallback page including its robots.txt. `PI_FETCH_MODEL=claude-haiku-5-5` would
  make that part a small fraction of this, at Haiku 5.5's US$0.10 per million input tokens.
- Expect roughly US$1.00–1.30 for standard depth with Anthropic search.
- Using Tavily for search removes the US$0.55 search part. With direct page and FX access (a normal network)
  the fallback cost is zero, leaving roughly US$0.15–0.20 per research for AI reading.

**Real-data dry run (development environment, 2026-10-20).** Three real web searches for "Milwaukee
2767-20" were captured with the development assistant's own search tool and fed through the full engine:
page reading, FX, analysis, saving and Excel export. That tool returns titles and URLs but no verbatim page
text, so snippets were left empty, and every supplier page was unreachable from that sandbox. The app
correctly reported:
- no usable prices ("7 results name model 2767-20, but none showed a usable price");
- the exact reason pages couldn't be read (host names couldn't be resolved);
- deal-forum posts as past deals rather than offers;
- the manufacturer's service notice for 2022 "H96B" units as a manufacturer statement.

The run also exposed three bugs that the simulated web hadn't (a misleading gap message, a generic
page-failure reason, deal forums treated as sellers); they are fixed and covered by tests. A run with a live
provider key is still needed to see real prices.

**Known limitations:**

- **Search coverage.** Search engines don't index every distributor, and many industrial distributors only
  show prices after login or by quote. Those appear as "Quote required" or "No price seen", with a quote
  draft. The coverage report lists what was searched; it can't list what search engines don't index.
- **Local businesses without a website or map listing** can't be found online. Without a SerpApi key there
  are no Google Maps listings, so local discovery relies on web search only (the result says so).
- **Contacts** are only those written on a supplier's page, map listing, directory listing or search result.
  A phone number on a national retailer's page is its general line, not a local branch.
- **Categories and channels** are chosen by keyword rules (`app/discovery.py`). An item that matches no rule
  is treated as a general purchase and searched across all channels.
- **Price evidence without AI.** Prices come from page data, Google Shopping or single-price snippets.
  Pages that show prices only in free text aren't read unless AI is on.
- **Equivalence by model number.** A model-number match is strong evidence, but kit contents,
  certifications (CSA/UL) and specs still need a human check.
- **Plain-language requests** (no model number): only specs written in the listing's own title or quoted
  text are checked. A page that offers several sizes but shows one price can still mislead, so check the
  size on the page before ordering.
- **Supplier labels.** The supplier directory (`app/suppliers.py`) labels site *types* (distributor,
  retailer, marketplace…). It makes no quality claims; unknown sites are flagged for verification.
- **Shipping.** Used only when a listing states it. A foreign seller's "free shipping" is not assumed to apply
  to Canada; Google Shopping Canada delivery terms are. Otherwise shipping is unknown, or your assumption.
- **No login or user accounts.** Saved comparisons are shared by everyone using the server.
- **Page-fetch safety.** Host names are checked against private/internal addresses before each request, but
  the connection resolves the name again, so a deliberately "rebinding" DNS server could still slip through.
  Keep the server on a trusted network.
- **Pure-number model numbers** (e.g. `8210`) can match unrelated numbers in a listing, such as an item
  number. Use the brand plus model ("3M 8210") for best results.

**Out of scope for Phase 1:** accounting, automatic emails or purchasing, payments, ERP integration.

**Suggested next steps:**

1. Add a Tavily key (and optionally SerpApi) and run the smoke test on the office network with a few
   typical purchases; tune the supplier directory and queries.
2. Add your preferred/approved suppliers and any negotiated account pricing as a first-class source.
3. Add sign-in, or put the app behind your company's SSO proxy, before sharing it beyond one machine.
4. Scheduled re-checks of saved comparisons to build price history automatically.
5. Optional additional providers (e.g. Brave Search) behind the same provider interface.
