# Purchasing Research: Phase 1

A research tool for Midcontinent Terminal (Thunder Bay) that helps anyone find a better deal on almost any
item without giving up essential quality, reliability or safety. Type a product name, model number, plain
description or product link. The tool searches the web for suppliers, prices, reviews and wholesale channels,
then shows a sourced comparison with two separate, explained recommendations: the lowest comparable price and
the best overall value.

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

- **Windows:** double-click `run.bat`. It installs Python with winget if it's missing, sets up `.venv` on the
  first run, starts the app and opens the browser.
- **Linux/macOS:** run `./run.sh` (on a Mac it also opens the browser).

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

Estimated cost per research with only an Anthropic key:
- about US$0.08–0.10 for Quick and US$0.12–0.15 for Standard, so the US$10 default covers roughly 70–100
  researches a month;
- most of it is the US$0.01 fee per web search.

These figures come from the token counts measured in the Opus live runs, priced for Haiku. Haiku itself
hasn't been run live in this app yet, so the first research is its live test; its details show the actual
estimate.

For stronger reading, set `PI_ANTHROPIC_MODEL`. Only the Opus Quick figure was measured live:

| Model | Quick | Standard |
|---|---|---|
| `claude-sonnet-5-5` | about US$0.40 (estimate) | about US$0.55–0.70 (estimate) |
| `claude-opus-5-5` | about US$0.72 (measured) | about US$1.00–1.30 (estimate) |

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

| Depth | Web searches | Tavily credits | + SerpApi | Typical use |
|---|---|---|---|---|
| Quick (preselected) | 3 (price, reviews, wholesale) | 3 | +1 search | fast price check |
| Standard | 6 (+ suppliers, problems/recalls, specs) | 6 | +1 search | normal purchase |
| Deep | 8, advanced (+ alternatives, cross-border USD) | 16 | +1 search | larger or riskier buys |

So the Tavily free tier covers roughly 160 standard researches per month. Pay-as-you-go works out to about
US$0.05 per standard research. With AI on, add roughly 15–25k input tokens and 2–8k output tokens
(including thinking) per research. That's about **US$0.01 on the default Claude Haiku 5.5**, or
US$0.10–0.30 on Claude Opus 5.5. This is an estimate; each research's details show its tokens and estimated
cost. Use `PI_ANTHROPIC_MODEL` / `PI_ANTHROPIC_EFFORT` to change it.

Re-running a search for the same item within 12 hours (`DUPLICATE_WINDOW_HOURS`) offers the saved result
first, so credits aren't spent by accident. Changing import assumptions recalculates without searching.

Supplier pages are also read directly (no credits) for schema.org price data. This respects robots.txt and
is limited to `FETCH_MAX_PAGES` (10) per research. Many large retailers block automated reads; when that
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

1. **Understand the request.** It extracts model/part numbers (e.g. `2767-20`, `DCF887B`). For a pasted link
   it reads the product page (schema.org name/brand/MPN), falling back to the URL's words if the page can't
   be read. With AI on, it also suggests key specs and up to 3 extra queries.
2. **Search** with Tavily (Canada-weighted for price/supplier queries) and optionally Google Shopping Canada.
3. **Read supplier pages** for structured price, currency, availability, condition, ratings and specs.
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
9. **Save** the comparison and every observed price (supplier, price, currency, CAD, URL, timestamp, pack
   size, specs, MOQ, shipping, warranty) to SQLite for price history.

### Canadian import handling

Duty, CUSMA eligibility and surtaxes depend on the goods' **country of origin** and HS classification, which
search results rarely establish. So they are never assumed. In the Import tab you can enter your own duty %,
surtax %, import shipping and brokerage; totals using them are marked **Estimated**. The tab also explains:

- the 5% GST at the border, generally recoverable for registrants;
- Ontario HST;
- the US-origin surtaxes in force since 2026-09-08 (15/25/50% by classification; United States Surtax Order
  (2026), CBSA Customs Notices 26-23 and 25-11);
- other-origin measures and brokerage fees;
- links to CBSA and the Canada Gazette.

That guidance text was reviewed 2026-10-20 and needs periodic re-checking (`app/import_costs.py`).
Recommendations are always based on observed prices, never on speculative import figures.

### Quality evidence

- **Ratings** from page data or Google Shopping are listed with their source and never averaged.
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
- **Results**: two recommendation cards, then "Watch out for" (conflicts, recalls, gaps) and "Ways to pay
  less". Below that, the comparison table: choose **Details** on any row for the evidence text, FX and cost
  breakdown. "Not compared" lists every excluded listing with its reason.
- **Tabs**: Quality & reliability, Buying channels, Import & landed cost (assumptions form), Price history
  (chart only with ≥3 comparable observations on ≥2 days; otherwise the raw observations), Sources & method
  (queries, provider errors, credits/tokens used, pages read, limits).
- **Save** names the comparison and pins it to the home page. **Search again** re-researches the same
  comparison and adds new price observations. **Export CSV / Excel**: the Excel file has Summary, Offers,
  Sources, Quality evidence, Price history and Import & assumptions sheets.

---

## Tests

```bash
python3 -m venv .venv && . .venv/bin/activate
pip install -r requirements-dev.txt
python -m pytest -q            # 136 tests; 6 live-network tests are skipped unless enabled (below)
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
  providers/       Tavily, SerpApi, Anthropic web search, Anthropic web fetch fallback
                   (+ shared error taxonomy). Add a provider here.
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

**Not verified live:**
- **Tavily and SerpApi.** That sandbox's network policy refuses `api.tavily.com` and `serpapi.com` (proxy
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
  show prices after login or by quote. Those appear as "Quote required".
- **Price evidence without AI.** Prices come from page data, Google Shopping or single-price snippets.
  Pages that show prices only in free text aren't read unless AI is on.
- **Equivalence by model number.** A model-number match is strong evidence, but kit contents,
  certifications (CSA/UL) and specs still need a human check. For plain-language requests (no model number),
  equivalence is explicitly "not verified".
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
