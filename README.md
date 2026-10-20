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
| **Quoted** | Stated by the source: schema.org price data on the supplier's page, a Google Shopping listing, or (with AI on) page text whose exact wording was verified. |
| **Snippet** | Seen only in a search-result snippet. Possibly outdated; open the page to confirm. Snippet prices never win "lowest" when a better-evidenced price exists. |
| **Calculated** | Arithmetic on quoted values: unit price, currency conversion (Bank of Canada rate), order totals. |
| **Estimated** | Uses *your* stated assumptions (import shipping, duty %, surtax %, brokerage). Nothing is assumed for you. |
| **Quote required** | The supplier doesn't publish a price ("call for price", "sign in to see price"). |

If no search provider is configured, the app shows setup steps and refuses to research. There is no demo
mode and no offline fallback.

---

## Quick start

Requirements: Python 3.11+ and internet access to the hosts listed under [Network](#network-access).

```bash
cp .env.example .env          # then put your TAVILY_API_KEY in .env
./run.sh                      # Linux/macOS: creates .venv, installs, starts http://127.0.0.1:8000
```

On Windows, copy `.env.example` to `.env`, edit it, and double-click `run.bat`. (`run.bat` doesn't read `.env`
itself; the app does on startup.)

Open http://127.0.0.1:8000. The badge at top right turns green ("Ready: Tavily…") when a provider is configured.

**The app has no login in Phase 1.** It binds to `127.0.0.1` (this computer only) by default. Only set
`HOST=0.0.0.0` on a trusted internal network, or behind your company's sign-in proxy.

---

## Search providers, keys and costs

At least one search provider is required. Prices below are from public pricing pages and third-party
summaries checked on 2026-10-20. **Verify on each vendor's site before committing; they change.**

| Service | Needed? | What it adds | Free tier | Paid (as published) |
|---|---|---|---|---|
| **Tavily** (`TAVILY_API_KEY`), https://app.tavily.com | Recommended primary | Web search across manufacturers, distributors, marketplaces, reviews, forums; returns page text | 1,000 credits/month, no card | ~$30/mo for 4,000 credits; pay-as-you-go ~US$0.008/credit |
| **SerpApi** (`SERPAPI_API_KEY`), https://serpapi.com | Optional (or the only provider) | Google Shopping **Canada** listings with structured prices, ratings and delivery terms; Google web results if Tavily isn't set | 250 searches/month | from ~US$25/mo for 1,000 searches |
| **Anthropic Claude** (`ANTHROPIC_API_KEY`), https://console.anthropic.com | Optional | Understands plain-language requests, extracts prices from page text, summarizes reviews. Every extracted fact is checked word-for-word against the source; failures are discarded and counted. | none | Claude Opus 5.5: US$4 / US$20 per million input/output tokens |
| **Bank of Canada Valet** | Built in | Daily FX rates (USD, EUR, CNY…→CAD) | free, no key | n/a |

**Cost per research** (Tavily: basic search = 1 credit, advanced = 2):

| Depth | Web searches | Tavily credits | + SerpApi | Typical use |
|---|---|---|---|---|
| Quick | 3 (price, reviews, wholesale) | 3 | +1 search | fast price check |
| Standard (default) | 6 (+ suppliers, problems/recalls, specs) | 6 | +1 search | normal purchase |
| Deep | 8, advanced (+ alternatives, cross-border USD) | 16 | +1 search | larger or riskier buys |

So the Tavily free tier covers roughly 160 standard researches per month. Pay-as-you-go works out to about
US$0.05 per standard research. With AI on, add roughly 15–25k input tokens and 2–8k output tokens
(including thinking) per research: about **US$0.10–0.30 on Claude Opus 5.5**. This is an estimate; the
Sources tab shows the actual tokens used for each research. Use `PI_ANTHROPIC_MODEL` / `PI_ANTHROPIC_EFFORT`
to choose a cheaper setting.

Re-running a search for the same item within 12 hours (`DUPLICATE_WINDOW_HOURS`) offers the saved result
first, so credits aren't spent by accident. Changing import assumptions recalculates without searching.

Supplier pages are also read directly (no credits) for schema.org price data. This respects robots.txt and
is limited to `FETCH_MAX_PAGES` (10) per research. Many large retailers block automated reads; when that
happens the source shows "page read: no (blocked)" and the price relies on search data.

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
   compatible/aftermarket, or different model. Refurbished/used/open-box, price ranges, unclear prices and
   unconvertible currencies are flagged and **excluded from the comparison**, but stay visible with the reason.
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
- **With AI on**, recurring praise, criticism and reliability issues are summarized. Each point must carry at
  least one exact quote from a cited source or it is dropped. The tab shows how many were dropped.

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
python -m pytest -q            # 62 tests
```

The tests never call real providers. They run the real HTTP, parsing and analysis code against a
**simulated web** in `tests/fakeweb.py`: fictional "Acme TX-4400" products, used only by tests. Covered:

- provider success and errors (bad key, quota 432/433, rate limit, 5xx, timeout, malformed JSON, network
  refusal);
- the full research → save → reopen → export flow;
- partial provider failure, no results, FX outage;
- conflicting prices, refurbished/variant/compatible exclusion, quote-only suppliers;
- URL input (readable and unreadable), robots.txt, the duplicate guard, assumptions recalculation and
  history charting rules;
- AI verification (fabricated prices, quotes and statistics are rejected);
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

- `api.tavily.com` and/or `serpapi.com`
- `www.bankofcanada.ca`
- `api.anthropic.com` (if AI is on)
- supplier websites (for page reading; optional, `FETCH_PAGES=false` disables it)

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
  providers/       Tavily, SerpApi (+ shared error taxonomy). Add a provider here.
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

**Built and tested against the simulated web:** everything described above.

**Not verified against the live providers from the development environment.** The build environment's
network policy blocked api.tavily.com, serpapi.com and bankofcanada.ca. The provider code follows each
API's documented request/response format, and network refusals are handled (tested for real). But the first
real run should be `scripts/smoke_test.py` with your keys. If a provider has changed its response format,
the error appears as "unexpected response format" rather than as wrong data.

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
- **Shipping.** Stated only when a listing states it; otherwise it's shown as unknown.
- **No login or user accounts.** Saved comparisons are shared by everyone using the server.

**Out of scope for Phase 1:** accounting, automatic emails or purchasing, payments, ERP integration.

**Suggested next steps:**

1. Run the smoke test with real keys on a few typical purchases and tune the supplier directory and queries.
2. Add your preferred/approved suppliers and any negotiated account pricing as a first-class source.
3. Add sign-in, or put the app behind your company's SSO proxy, before sharing it beyond one machine.
4. Scheduled re-checks of saved comparisons to build price history automatically.
5. Optional additional providers (e.g. Brave Search) behind the same provider interface.
