# Site Enrichment Agent — Build Plan

## What we're building

A pipeline that takes ~7,000 clinical research site domains, visits each website, and extracts structured data with evidence (source URL + quoted snippet) for every field. Output is a local CSV that a human reviews before any downstream use.

**Downstream use:** internal directory, sales prospecting, GTM strategy.

## Read this first: how this build is staged

The user is asleep while you (Claude Code) work overnight. Your job is to **build and polish the agent code so the user can wake up, build the golden dataset, and start measured iteration immediately.** You are NOT trying to run on 7K rows overnight, and you cannot meaningfully tune extraction *accuracy* without ground truth, which only the user can produce.

The plan is split into **two halves**:

- **Overnight (Claude Code, autonomous)** — Phases 0-5: build code, smoke test on ~20 self-picked domains, polish.
- **With user (after wake-up)** — Phases 6-10: golden set, accuracy iteration, scale up, ship.

There are explicit **STOP** markers. Do not cross them.

## Why we're building it this way

- The input names come from ClinicalTrials.gov and are messy. The input addresses are stale. **The website is the source of truth, not the input row.**
- The hard fields (dedicated vs embedded, recruitment mentions, research URL) cannot be answered by any structured API. They must come from a real visit to the site.
- Validation is **per-field evidence**, not a separate Twilio/Places stage. Every extracted value carries its own source URL + snippet so a human can verify in one glance.
- We use an **orchestrator-worker pattern** with up to 3 LLM roles (planner → extractor → verifier), NOT a Fruityo-style multi-agent peer-review system. See "Architecture decisions" below.

## Architecture decisions (do not relitigate without asking)

### Use: orchestrator-worker (up to 3 LLM calls per row)

1. **Planner** — given homepage HTML, picks 3-5 internal URLs worth crawling and explains why each.
2. **Extractor** — given cleaned text from all fetched pages, produces the structured `SiteProfile` with evidence per field.
3. **Verifier** (conditional, not in v1) — given the extractor's output, checks each snippet appears verbatim in the source text and each `source_url` was actually fetched. Returns pass/fail + corrections per field. Extractor re-runs once with verifier feedback if anything fails. Max 2 retries total per row.

Build **v1 = planner + extractor only**. Only add the verifier (Phase 8, with user) if accuracy on golden misses targets.

### Do NOT use: Fruityo-style multi-agent peer review

Multiple specialist agents with personalities critiquing each other works for subjective creative output (tweets, blog posts). It does not work for objective factual extraction. There is nothing to roast about a phone number — it's either on the page or it isn't. Peer-review theater on 7K rows × 5+ reviewer calls would cost $2-4K per pass with no accuracy gain over the planner→extractor→verifier pattern above.

Do NOT introduce: additional agent roles, personalities, peer-review queues, message buses, cron heartbeats, Telegram notifiers, PocketBase/SQLite state stores, LangGraph, CrewAI, AutoGen, Prefect, Celery, Redis, or any orchestration framework. If you think you need one, **stop and write the question in `QUESTIONS_FOR_USER.md`** instead of proceeding.

## Tech stack (locked)

| Component | Choice | Notes |
|---|---|---|
| Language | Python 3.11+ | |
| HTTP | `httpx` (async) | |
| Browser fallback | `playwright` | Headless Chromium for blocked sites |
| HTML cleanup | `trafilatura` | Strips nav/footer junk before LLM sees it |
| LLM | Claude Sonnet 4.6 (`claude-sonnet-4-6`) | |
| Structured output | `instructor` + `pydantic` | |
| Tracing | `langsmith` (optional) | Free tier; if no key set, fall back to local JSONL log |
| Trials cross-ref | ClinicalTrials.gov API v2 | Free, no auth |
| Output | Local CSV (append-only) | |
| Review UI | `streamlit` | |

## File layout

```
~/site-agent/
  .env                    # API keys (never commit; .gitignore it)
  .env.example            # Template with keys blanked out (commit this)
  CLAUDE.md               # Project conventions
  BUILD_PLAN.md           # This file
  README.md               # Setup + run instructions
  QUESTIONS_FOR_USER.md   # Anything you couldn't decide alone — top of file = most recent
  PROGRESS.md             # What you completed overnight, in chronological order
  pyproject.toml
  src/
    __init__.py
    schema.py             # Pydantic models — THE CONTRACT
    fetch.py              # httpx + playwright fetcher
    planner.py            # LLM call 1: which pages to crawl
    extract.py            # LLM call 2: structured extraction
    verify.py             # LLM call 3 (Phase 8, conditional)
    ctgov.py              # ClinicalTrials.gov v2 client
    pipeline.py           # Per-row orchestration
    config.py             # Cost caps, concurrency, model, etc.
    main.py               # CLI entry point
  data/
    smoke_test_domains.csv  # 20 domains you pick for overnight smoke test
    cache/                # Raw fetched HTML, keyed by domain
    # input.csv, golden.csv, output.csv added by user later
  prompts/
    planner.txt
    extract.txt
    verify.txt            # Phase 8
  scripts/
    review.py             # Streamlit review UI
    smoke_test.py         # Runs pipeline on smoke_test_domains.csv
  tests/
    test_schema.py        # Pydantic schema sanity checks
    test_fetch.py         # Hits httpbin.org / example.com
    test_ctgov.py         # Hits CT.gov API
```

## The schema

`src/schema.py`:

```python
from pydantic import BaseModel, Field
from typing import Optional, Literal

Confidence = Literal["high", "medium", "low", "not_found"]
SiteType = Literal["dedicated", "embedded", "unclear"]

class Evidence(BaseModel):
    value: Optional[str] = None
    source_url: Optional[str] = None
    snippet: Optional[str] = Field(None, max_length=300)
    confidence: Confidence = "not_found"

class SiteProfile(BaseModel):
    canonical_org_name: Evidence
    hq_phone: Evidence
    hq_address: Evidence
    recruitment_phone: Evidence
    location_count: Evidence
    site_type: Evidence  # value must be one of "dedicated" | "embedded" | "unclear"
    research_url: Evidence
    trials_status: Evidence  # populated from CT.gov, not the site
```

**Critical:** every field is `Optional` and defaults to `not_found`. The model MUST be allowed to say "I don't know." Forcing non-null values causes hallucination.

---

# Overnight phases (you, Claude Code, autonomous)

Work through these in order. After each phase, write a one-paragraph entry to `PROGRESS.md` with the timestamp, what you did, what was observed, and any decisions made. At any STOP, halt and wait for the user.

## Phase 0: Project setup (~20 min)

- Create the file layout above. Empty stubs are fine where actual code comes later.
- `pyproject.toml` with deps from the tech stack table. Use `uv` or plain `pip` — your call.
- Create `.env.example` with `ANTHROPIC_API_KEY=`, `LANGSMITH_API_KEY=`, `LANGSMITH_TRACING=true`, `LANGSMITH_PROJECT=site-agent`. Leave values blank.
- Real `.env` already exists from user setup; verify keys load with a 1-line script.
- `playwright install chromium` (chromium only, not all browsers).
- Smoke checks: one `httpx.get("https://example.com")`, one Claude API "hello" call, one LangSmith trace verified visible in dashboard.

**Done when:** smoke checks pass, `PROGRESS.md` has Phase 0 entry.

## Phase 1: Schema + fetch layer (~45 min)

- `src/schema.py` — Pydantic models exactly as above. Add tests in `tests/test_schema.py` that exercise `Evidence(confidence="not_found")` defaults.
- `src/fetch.py`:
  - Async function `fetch(domain: str) -> FetchResult`.
  - httpx with 15s timeout, 3 retries with exponential backoff, rotating User-Agents (use 3-4 realistic ones).
  - Cache raw HTML to `data/cache/{domain}.html`. On rerun, hit cache first.
  - "Blocked" detection: 403/429/503 OR body < 500 bytes OR contains Cloudflare/PerimeterX/Akamai challenge markers.
  - On blocked: try `fetch_with_playwright(domain)` — headless Chromium, 30s timeout, screenshot on failure.
  - Concurrency: `asyncio.Semaphore(10)` for httpx, `Semaphore(3)` for playwright (heavier).
- Tests in `tests/test_fetch.py` — hit `example.com` and one known-blocking site if you can find one.

**Done when:** `python -m src.fetch example.com` prints clean HTML; tests pass.

## Phase 2: Planner sub-agent (~45 min)

- `src/planner.py`:
  - Function `plan_crawl(homepage_html, domain) -> CrawlPlan` returning ordered list of `{url, reason, priority}`.
  - Uses `instructor.from_anthropic` with Sonnet 4.6.
  - Wrapped with `@traceable(name="planner", run_type="llm")`.
  - Input: cleaned homepage text (use `trafilatura.extract`) + extracted internal links (use `BeautifulSoup` to pull `<a href>` from raw HTML).
  - Output: up to 5 internal URLs the model thinks are most likely to contain the target fields.
- `prompts/planner.txt`:
  - Tell the planner what fields downstream will extract (so it picks the right pages).
  - Constrain output: must be URLs that appear in the provided links list.
  - Bias toward: `/research`, `/clinical-trials`, `/about`, `/contact`, `/locations`, `/patients`, `/recruit`.
- Pydantic model for planner output:

  ```python
  class PlannedPage(BaseModel):
      url: str
      reason: str = Field(max_length=150)
      priority: int = Field(ge=1, le=5)

  class CrawlPlan(BaseModel):
      pages: list[PlannedPage] = Field(max_items=5)
  ```

**Done when:** planner runs on `mayoclinic.org` and returns a plausible 3-5 URL list including their research/contact pages; LangSmith shows the trace.

## Phase 3: Extractor (~1 hour)

- `src/extract.py`:
  - Function `extract(domain, homepage_text, additional_pages: dict[url, text]) -> SiteProfile`.
  - One Sonnet 4.6 call via `instructor`, enforced against `SiteProfile`.
  - Wrapped with `@traceable(name="extractor", run_type="llm")`.
- `prompts/extract.txt` — see "Extraction prompt skeleton" below. Iterate on it later with the golden set; don't try to perfect it now.

### Extraction prompt skeleton

```
You are extracting structured facts about a clinical research site from its website.

You will receive cleaned text from up to 5 pages of the site, each prefixed with its URL.

For EACH field in the SiteProfile schema, return:
- value (or null if not found on any provided page)
- source_url (one of the URLs in the provided text)
- snippet (≤30 words, VERBATIM substring of the provided text)
- confidence: high | medium | low | not_found

HARD RULES:
1. Use ONLY the provided page text. Do not use prior knowledge of the organization.
2. If a fact is not stated on any provided page, set value=null and confidence=not_found.
3. The source_url MUST be one of the URLs that appears in the provided text.
4. The snippet MUST be a verbatim substring of the provided text. Do not paraphrase, summarize, or invent.
5. canonical_org_name = the name the organization uses to refer to itself on its own site.
   Do NOT use the name from the input row; that comes from ClinicalTrials.gov and is unreliable.

FIELD DEFINITIONS:
- canonical_org_name: org's preferred name as shown on its own site
- hq_phone: main phone number, prefer E.164 if you can parse it (e.g., +15551234567), otherwise as-shown
- hq_address: full mailing address of headquarters
- recruitment_phone: distinct phone for "participate in a study" / "patient recruitment" pages; null if same as hq_phone or absent
- location_count: number of physical locations (e.g., "12 clinics", "single location"). String, not int.
- site_type:
    "dedicated" = primary business is running clinical trials.
                  Signals: trials front-and-center on homepage; "we conduct clinical research" framing;
                  org name contains "research" or "trials".
    "embedded"  = primarily a healthcare provider (hospital, clinic, practice) that also runs trials.
                  Signals: trials buried under /research; primary nav is care-focused.
    "unclear"   = ambiguous. Use freely; do not force a call.
- research_url: a URL ON THIS SITE that prominently mentions clinical research/trials.
                If multiple, pick the most canonical (e.g., /research over /about#research).
- trials_status: leave null. Filled separately from ClinicalTrials.gov.

[Then: the 5 pages of text, each prefixed with "PAGE: <url>\n\n"]
```

**Done when:** extractor runs against 1 hand-picked domain and produces a valid `SiteProfile`; LangSmith trace looks reasonable.

## Phase 4: ClinicalTrials.gov cross-reference (~30 min)

- `src/ctgov.py`:
  - `get_trials_status(canonical_org_name: str) -> Evidence`.
  - Hits `https://clinicaltrials.gov/api/v2/studies?query.term="<name>"&filter.overallStatus=RECRUITING|NOT_YET_RECRUITING|ACTIVE_NOT_RECRUITING&pageSize=10`.
  - Use the extractor's `canonical_org_name`, not the input row name.
  - Logic:
    - ≥1 active study → `value="active"`, `confidence="high"`, `source_url=` the human-readable CT.gov search URL.
    - 0 active but ≥1 historical → `value="inactive"`, `confidence="medium"`.
    - 0 total → `value="unknown"`, `confidence="low"`.
- Add `tests/test_ctgov.py` — hit the real API for one known org (e.g., "Mayo Clinic").

**Done when:** CT.gov lookup runs for the same hand-picked domain from Phase 3 and returns a plausible status.

## Phase 5: Pipeline + smoke test + review UI (~1.5 hours)

### 5a. Pipeline

- `src/pipeline.py`:
  - `process_row(domain, input_row) -> dict` — chains fetch → planner → fetch planned pages → extract → ctgov → assemble flat dict for CSV row.
  - All LLM calls traced.
  - Cost tracking: keep a running tally per process; abort if > $20 in a single run.
- `src/main.py`:
  - CLI: `python -m src.main --input data/smoke_test_domains.csv --output data/smoke_output.csv [--limit N] [--concurrency N]`.
  - Reads input CSV, reads existing output CSV, skips already-processed domains (idempotent).
  - Async with semaphore.
  - Appends each row's result to output CSV immediately after completion.
  - Logs to stderr; structured (use `logging`, not `print`).

### 5b. Pick 20 smoke-test domains

Generate `data/smoke_test_domains.csv` yourself. Pick a deliberate mix:
- 5 large hospital systems (e.g., mayoclinic.org, clevelandclinic.org, jhmi.edu)
- 5 known dedicated CROs / research sites (search "dedicated clinical research site" — pick real ones)
- 5 mid-size health systems with research arms
- 3 small private clinics with research
- 2 deliberate edge cases (one likely Cloudflare-protected, one international)

Write the list with a one-line rationale per domain so the user can see your sampling.

### 5c. Run the smoke test

`python scripts/smoke_test.py` → runs pipeline on those 20 domains.

After it finishes, examine `data/smoke_output.csv` and write a `SMOKE_TEST_REPORT.md` covering:
- Fetch success rate (httpx vs playwright vs blocked)
- Per-field fill rate (% of rows where field is not "not_found")
- Any rows with hallucinated snippets (run a verbatim-substring check yourself — if a snippet isn't actually in the cached HTML's extracted text, flag it)
- Latency per row
- Total cost
- Top 3 patterns of failure you observed

### 5d. Code iteration based on what you saw

If you find:
- Snippets that don't appear verbatim in source text → improve extractor prompt's hard-rule on this
- Many "not_found" on obvious fields → check if planner is picking the right pages
- Many blocked sites → tune playwright fallback (add stealth headers, longer waits)
- Slow rows → profile and tune concurrency

Make **one change at a time**, re-run smoke test, compare. Note each iteration in `PROGRESS.md`.

Cap yourself at **5 iterations of the smoke test overnight** (budget control). After 5, stop iterating even if you have ideas — write remaining ideas to `QUESTIONS_FOR_USER.md`.

### 5e. Build the review UI

`scripts/review.py` — Streamlit app:
- Loads `data/output.csv` (or whichever CSV is passed).
- One row per page. Sidebar: filter by confidence (`low`/`not_found` only), filter by `site_type=unclear`, filter by manually-edited.
- Main pane: show each field's value, snippet (with quotes), and clickable source_url.
- Per-field: Accept / Edit / Reject buttons. Writes back with `<field>_locked=True`.
- "Next row" / "Previous row" nav.
- Aim for clean and functional, not pretty.

**Done when:** smoke test ran ≤5 times; report written; review UI launches and renders the smoke test output.

## 🛑 STOP — Phase 5 is your last autonomous phase

Write a final `OVERNIGHT_SUMMARY.md` covering:

1. What's built and verified working.
2. What the smoke test revealed about likely accuracy issues.
3. Open questions in `QUESTIONS_FOR_USER.md` (link them).
4. **Recommended next actions for the user** in priority order (e.g., "review smoke output, then build golden set").
5. Any architectural deviations from this plan and why.

Then **stop and wait.** Do not proceed to Phase 6+. Do not attempt to scale up. Do not run on more domains.

---

# Daytime phases (with user, after wake-up)

## Phase 6: Golden dataset (4-8 hours of user's time)

User hand-builds `data/golden.csv` — 150 domains, stratified sample, each cell hand-verified with source URL. See `CLAUDE.md` for stratification mix.

**This is the project's load-bearing wall. Everything downstream depends on it.**

## Phase 7: Accuracy iteration

User runs extractor against golden, eyeballs failures in LangSmith, makes ONE prompt change at a time, re-runs. Goal: site_type ≥85%, hq_phone ≥90%, hq_address ≥85%, research_url ≥90%.

## Phase 8: Add verifier (conditional)

ONLY if Phase 7 stalls below targets. Build `src/verify.py` per architecture spec above.

## Phase 9: Scale up

Run on 100 random rows → spot check 20. Run on 1,000 → spot check 30. Run on full 7K.

## Phase 10: Manual review

Filter to low-confidence and unclear rows. Use review UI from Phase 5e.

---

# Operational details

## Cost guardrails (overnight)

Hard limits enforced in `src/config.py`:

- `MAX_ROWS_PER_RUN = 50` overnight (smoke test only)
- `MAX_COST_USD_PER_RUN = 20`
- `MAX_CONCURRENT_LLM_CALLS = 10`
- `MAX_PLANNER_RETRIES = 1`
- `MAX_EXTRACTOR_RETRIES = 1`

If any limit is approached, log loudly and stop. **Never silently exceed these.**

## Idempotency

`main.py` reads existing output CSV first, builds a set of processed domains, skips them. Cache directory persists between runs. Crashes are cheap.

## Logging

Use `logging` with `INFO` to stderr by default, `DEBUG` if `--verbose`. Structure logs as `[domain] phase: message`. No `print` statements anywhere except CLI help text.

## What "done" means per phase

Every phase has an explicit "Done when" line above. Do not declare a phase complete without meeting it. If a phase can't be completed (e.g., a dependency won't install), write the issue to `QUESTIONS_FOR_USER.md` and skip ahead to a phase that doesn't depend on it.

## The non-negotiables

1. **STOP at the Phase 5 stop marker.** Do not run on golden set or scale up — those need user.
2. **Every extracted field has evidence (URL + snippet).** No naked values.
3. **`not_found` is a valid answer.** Better than hallucination.
4. **Smoke test only — max 50 rows total processed overnight.**
5. **Append-only output, resumable runs.**
6. **One change at a time during iteration.** Document each in `PROGRESS.md`.
7. **No frameworks beyond the tech stack table.** No Fruityo-style multi-agent. No Telegram. No state DB.
8. **When in doubt, write to `QUESTIONS_FOR_USER.md` and proceed without that piece.** Better to leave a clear question than to make a wrong call.
