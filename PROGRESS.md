# Progress Log

Newest entries at TOP.

---

## 2026-06-02 — locations.txt v9 → v10 (full-street emphasis)

Fix incomplete street addresses (Yoshi: "we need the full street ... only when it actually finds it
then return city/state"). `extract_page_sections` already emits FOOTER / GOOGLE_MAPS_ADDRESS(ES) /
RAW_TEXT / JSON-LD / microdata, but the prompt only listed PAGE/.../BODY and said "Partial addresses
(city + state only) are fine." v10:
- documents GOOGLE_MAPS_ADDRESS(ES) / RAW_TEXT / structured blocks; tells model to check ALL sections
  before deciding a street is missing;
- `address_street` REQUIRED when a street appears anywhere (assemble number + street + suite); null
  only if truly absent;
- rule 5 flipped: must use street if present in any section; city/state-only only as last resort,
  confidence=low.
No schema change. Also `scripts/smart_location_recount.py`: `--domains-file` synthesizes rows for
domains not in output_org_value_match.csv (resolved final_urls now run); URL-selector prompt filled via
`.replace` not `.format` (literal `{slug}` raised KeyError). Firecrawl-fetch fallback + union-with-basic
still pending.

---

## 2026-05-29 (later) — Fixed the dedupe over-count (105 → 86)

**What:** Tightened `dedupe()` in `scripts/firecrawl_locations.py`. Old key was
`(normalized_street, normalized_city)`, which missed both documented gaps. New key is
**`(zip, street-number, normalized-first-street-word)`** plus explicit street-less handling.

- **Street-less rows:** a row with no street is dropped only if a street-bearing row exists in
  the same zip OR city (homepage city/zip dupes). Sole-location street-less rows are KEPT —
  New Brunswick (08901) and Marlboro (07746) correctly survived; Somerset/Edison/Old Bridge dropped.
- **Near-dups:** first-word is abbreviation-normalized (`St↔Street`, `Rd↔Road`, `Blvd↔Boulevard`,
  `Rt↔Route`, `W↔West`, `Sq↔Square`) and punctuation is ignored (`U.S. 9 ↔ US-9`). A leading
  building name before a comma is stripped (`Village Square at Howell, 59 Kent Rd` → `59 Kent Rd`),
  but only when the pre-comma text is a NAME — a trailing `, 2nd Floor` / `, Suite 5` no longer
  clobbers the street (this was a bug caught mid-validation on the 08690 Whitehorse pair).
- **Street number is load-bearing:** keeps genuinely distinct same-zip offices apart —
  473 vs 477 Lakehurst (08755), 614 vs 181 Franklin (07110), 1488 vs 2155 Wantagh (11793).

**Validated OFFLINE — no credits spent.** Wrote `scripts/validate_dedupe.py`, which applies the new
logic to the existing 105-row `data/output_locations_firecrawl.csv` and prints every merge/drop
decision + every remaining multi-row zip for eyeballing. Result: **105 → 86 unique** (matches the
original ~87 estimate). All 15 merges are true spelling variants; all remaining same-zip clusters are
genuinely distinct offices. No false merges, no missed dups. Real-script `dedupe()` reproduces 86.

**Refreshed outputs (Yoshi chose the FREE in-place option, no credits):**
  - Backed up the 105-row file → `data/output_locations_firecrawl.csv.bak-105`.
  - Re-deduped the existing CSV in place → `data/output_locations_firecrawl.csv` now holds **86 rows**.
  - Re-pushed: cleared + rewrote the `locations_firecrawl` tab in "Site Agent Data" → **86 data rows**.

**NEXT:** validate the dedupe + workflow on more flagged domains before any full ~3,982-domain batch.
DO NOT run the full batch without Yoshi's explicit go-ahead.

---

## 2026-05-29 (later still) — Flagged-domain test run + concurrency + HUB-PAGE FIX (PAUSED mid-test)

**Goal:** run the location workflow on all domains in `data/output_orgs_research.csv` flagged
`location_count_status` ∈ {over, under} — **665 unique domains** (465 over + 200 under). Yoshi asked
to TEST 25 first before the full 665.

**Inputs built:**
  - `data/flagged_over_under_input.csv` — all 665 flagged domains (the eventual run).
  - `data/test25_flagged_input.csv` — representative 25 (17 over + 8 under, spread A–Z).

**Concurrency added to `scripts/firecrawl_locations.py`** (Firecrawl plan = Standard, so 8 is safe):
  - `--concurrency N` flag (default 1 = sequential, unchanged). Thread pool across domains.
  - `_call_with_backoff()` wraps every map/scrape — retries 429/transient w/ exponential backoff.
  - `append_rows()` now lock-guarded (`_write_lock`) so parallel workers don't interleave rows.
  - Full-run command: `.venv/bin/python -m scripts.firecrawl_locations --input data/flagged_over_under_input.csv --concurrency 8 --verbose`

**KEY FINDING from the test (this is why we test before batching):** the old `candidate_pages()`
only scraped mapped URLs, and Firecrawl's `map()` frequently OMITS the bare hub index (e.g.
`/locations`). On **bostonivf.com** it scraped all 22 individual `/locations/<clinic>` subpages —
which render their address via JS and returned EMPTY even after the 12s retry → **0/22 extracted**
after ~13 min + ~22 wasted scrapes. Yoshi confirmed `bostonivf.com/locations` lists them all.

**FIX (applied + validated, NOT yet re-run on the 25):**
  - `candidate_pages()` now returns ordered `(kind, url)` and, when ≥2 mapped subpages share a parent
    (`/locations/<x>` ×22), synthesizes that parent as a **hub** and scrapes it FIRST.
  - `process_domain()`: if a hub returns a complete list (≥ expected), it SKIPS the redundant
    individual subpages — fixes correctness AND the wasted-credit blowup.
  - **Validated on bostonivf:** new top candidate = `https://www.bostonivf.com/locations` (hub),
    scraping it alone yields **21 unique addresses** (vs 0 before). expected hint = 22.

**STATE AT PAUSE:**
  - Test run was KILLED at ~7/25 domains (old buggy code). Process stopped; nothing running.
  - `data/output_locations_firecrawl.csv` currently = allied 86 rows + ~7 test domains' rows appended
    with the OLD logic (incl. bostonivf=0). ⚠ These test rows are STALE/buggy.
  - Test results seen (old code): 1sturology 2 (⚠<4), 3sync 1, arkansasurology 20, bismarck 1,
    **bostonivf 0 (⚠<22)**, ccare 11, **clinnovaresearch 0 (⚠<1)**.

**RESUME PLAN:**
  1. Strip the ~7 test-domain rows out of `output_locations_firecrawl.csv` (keep allied 86 only) so
     the buggy bostonivf=0 etc. don't linger. (allied-only filter, or restore from a clean copy.)
  2. Re-run the 25 with the FIXED code at `--concurrency 8`; review counts vs over/under flags,
     paying attention to remaining shortfalls (1sturology, clinnovaresearch) — may need more candidate
     tuning before the 665.
  3. Only then launch the 665 (with Yoshi's go-ahead).

  ✅ Step 1 done (stale rows stripped; CSV back to allied 86, backup `.bak-130-stale`).

---

## 2026-05-29 (later) — Three discovery/efficiency fixes after bostonivf + 3sync diagnosis

Diagnosing the two zero-result domains exposed three real bugs, all now FIXED in
`scripts/firecrawl_locations.py` and validated end-to-end:

1. **map() `search=` filter was crippling recall.** A multi-keyword `search="locations offices
   sites contact address"` made Firecrawl's map semantically over-filter: 3sync.com returned **4**
   links with it vs **28** without. FIX: dropped `search=` entirely; map broadly, filter locally
   with LOCATION_HINT/SKIP_HINT. (3sync: 1 → 6 locations.)

2. **Hub index pages were never scraped.** map() omits the bare `/locations` index, so bostonivf
   only saw the per-clinic subpages (all JS-empty) → 0/22. FIX: `candidate_pages()` now synthesizes
   a HUB from any parent shared by ≥2 location subpages and scrapes it FIRST. (bostonivf: 0 → 22.)

3. **Early-stop depended on the unreliable `expected` count.** Yoshi: ignore expected, not 100%
   accurate (hub had 21 vs expected≈22 → kept scraping 20 empties). FIX: **deleted
   `expected_count_hint()` and all shortfall logic.** New stop rule: bail on the subpage tail after
   `EMPTY_TAIL_STOP=3` consecutive empties once locations are in hand. Only failure flag kept is the
   unambiguous "NO LOCATIONS FOUND" (zero). (bostonivf 769s → 80s.)

Also added (this session, earlier): **adaptive map cap** — `MAP_LIMIT=500` start, ×4 escalation up
to `MAP_LIMIT_MAX=10000` whenever the map returns exactly the cap (truncation signal), so big
networks aren't silently cut. Plus **concurrency** (`--concurrency`, thread pool, 429 backoff,
lock-guarded writes).

**Validated:** 3sync → 6 (28s), bostonivf → 22 (80s), empty-tail-stop confirmed firing.

---

## 2026-05-29 (later) — Plural-regex bug + street-address enforcement (from 1sturology diagnosis)

Yoshi: `1sturology.com/about/locations` has 14 locations but we returned 1. Scoped it:

- **ROOT CAUSE — LOCATION_HINT regex didn't match plural "locations".** Pattern was
  `(location|office|...|sites?)\b` — only "site" was pluralized, so `location\b` failed on
  "locations" (n→s isn't a word boundary). `/about/locations` was MAPPED but never selected as a
  candidate → never scraped. The page itself scrapes fine (not JS-hidden). **HIGH IMPACT:**
  "/locations" is the most common location-page URL, so this silently under-counted many domains.
  FIX: pluralized every keyword → `(location|office|clinic|center|centre|contact|find-a|where|
  visit|direction|site)s?\b`; also pluralized SKIP_HINT (careers/providers/doctors/jobs).

- **STREET ADDRESS NOW REQUIRED (Yoshi: "very important", and "keep trying to find it, 99% of the
  time it's there").** Three coordinated changes:
  1. PROMPT: demand the full street; if truly absent leave address_street EMPTY — never substitute
     city/landmark (the model was stuffing "Jeffersonville, IN" / "Dupont Square" into street).
  2. RETRY: escalate (longer wait) not just on EMPTY pages but on pages returning rows MISSING a
     street — street misses usually mean the page hadn't finished rendering. Keep whichever pass
     recovered more real-street rows (`_score`).
  3. FILTER: new `has_street()` = street must contain a building number (a digit). Used in the
     retry trigger, scoring, and a final drop of any row without a real street (logged, not silent).

**Validated:** 1sturology → **14, all real streets, 0 junk** (was 1). 3sync → 7 all-real-street
(true 6; one Kingwood near-dup survives because "US-59" tokenizes to "us" vs "U.S. Hwy" → "u" —
known punctuation edge; fix = strip periods before tokenizing in _street_signature).

**⚠ OPEN ITEM (do before the 665):** Firecrawl SDK calls have NO timeout — a network blip (e.g.
Yoshi switching wifi) HANGS the call instead of raising into `_call_with_backoff`, stalling the
worker. Add a per-call timeout so it fails fast and retries. Otherwise one hung worker stalls a
concurrency slot indefinitely on the 665 run.

**STATE:** Sheet/CSV still hold the PRE-fix 25-run (stale: under-counted, before plural+street
fixes). Need a fresh 25 re-run with ALL fixes before trusting accuracy.

---

## 2026-05-29 (evening) — SDK timeout, homepage-link harvest, hallucination guard

Guiding principle Yoshi set: **err toward pulling TOO MUCH — get ALL locations; over-discovery
beats missing any.** Three more fixes, all validated:

1. **SDK request timeout.** `Firecrawl(timeout=REQUEST_TIMEOUT_S=90)` — calls have NO timeout by
   default, so a network blip (wifi switch) HUNG a worker forever instead of failing into our
   backoff. 90s exceeds a legit 12s-wait scrape (~30-60s) but bounds dead sockets.

2. **Homepage-link harvest** (`harvest_home_links`). map() relies on sitemap/crawl and MISSES pages
   the homepage plainly links to — epilepsygroup.com's `/epilepsy-treatment-offices3-8/offices.htm`
   (10 real addresses) was absent from all 93 mapped links but present in the homepage's 65 links.
   We now union homepage links into discovery (candidate_pages handles mixed link objects/strings
   via `_link_url`). epilepsygroup: 0 → 9.

3. **Hallucination guard** (`street_on_page`). The aggressive street-retry on thin pages sometimes
   FABRICATES an address (epilepsygroup homepage produced a fake "170 Dr. Arla Way" = a DIFFERENT
   org's address). scrape_page now also pulls page markdown (same call, no extra credit) and drops
   any extracted street whose number + a street-name word don't both appear on the page. Lenient
   (keeps when it can't verify). Caught the fake NY row + two others; epilepsygroup → 9 all-real.

**FULL FIX SET NOW IN `scripts/firecrawl_locations.py`:** no-search map · adaptive map cap
(500→10k) · hub detection + scrape-first · hub-gated empty-tail-stop · concurrency + 429 backoff ·
plural LOCATION/SKIP regex · street-required (prompt + missing-street retry + has_street filter) ·
SDK timeout · homepage-link harvest · street-on-page hallucination guard.

**Decisions:** (a) hallucination guard = tighten (done); (b) SKIP the 25 v4 re-run — trust the
fixes, go to 665 prep (the 665 gets all fixes anyway). Known minor open items Yoshi will handle
later: U.S.-punctuation dedup edge (3sync Kingwood), same-building different-suite merge.

**NEXT — 665 PREP (DO NOT LAUNCH WITHOUT EXPLICIT GO-AHEAD):**
  - Input ready: `data/flagged_over_under_input.csv` (665 domains, 465 over + 200 under).
  - CSV decision: current `output_locations_firecrawl.csv` = allied 86 + v3's stale 25. For a clean,
    consistent 665 (all latest fixes), start the 665 output fresh (the 25 are a SUBSET of the 665 and
    should be re-run, not skipped by idempotent resume). allied is NOT in the 665 (wasn't flagged).
  - Command: `.venv/bin/python -m scripts.firecrawl_locations --input data/flagged_over_under_input.csv --concurrency 8 --sheet <id> --verbose`
  - Rough cost/time: ~12-20 scrapes/domain × 665 ≈ 8-13k Firecrawl calls; at concurrency 8, ~2-4 hrs
    (big networks like tnoncology = 30+ subpages each dominate the tail). Confirm $ vs plan first.

---

## 2026-05-29 — Firecrawl location extraction: new engine + script + Google Sheets push

**Decision:** Adopted **Firecrawl** (MCP server installed this session) as the location-extraction
engine, replacing the flaky httpx+Playwright+LLM-on-raw-HTML path for completeness. Ruled out
Google Maps (no GMB for many research sites; can't link domain→listing) and CT.gov facility-name
matching (facility names too inconsistent to map to domains).

**Validated workflow (the key insight):** `map` → pick candidate pages → `scrape` each with a JSON
schema → completeness-check vs an expected-count hint → escalate empties with longer `wait_for`.
Proven by hand on **rcaresearch.com → 62 locations / 18 states** (~107 credits ≈ $0.15). Two failure
modes caught & fixed there:
  - A hub page (`/find-a-research-location`) returned ZERO addresses — they lived on per-state
    subpages. The map `links` array (with `?selected=` params) is what revealed the real structure
    and the expected count. Naive "scrape the obvious page" would have returned nothing.
  - One state page (FL) returned **fabricated placeholder data** ("123 Research Way / (305) 555-1234")
    on first pass; another (CT) returned empty. Both fixed by `wait_for: 8000` + an anti-placeholder
    prompt rule. The expected-count check is the ONLY thing that catches the hallucination silently.

**Built:** `scripts/firecrawl_locations.py` — codifies the above. Features: map→scrape→escalate,
placeholder-row guard, dedupe by street+city, expected-count shortfall WARN, append-only +
idempotent CSV (`data/output_locations_firecrawl.csv`, columns identical to output_locations.csv —
snippet/confidence/validation_status intentionally left blank per Yoshi), optional
`--sheet <url>` push to a Google Sheets tab `locations_firecrawl`. Uses Firecrawl Python SDK v4.28
(`Firecrawl().map(...)`, `.scrape(url, formats=[{"type":"json",...}], wait_for=...)`). Installed
`gspread`; auth via `credentials/google_service_account.json`
(service account `site-agent@strange-cosmos-497818-t9.iam.gserviceaccount.com`).

**Validation run — allieddigestivehealth.com:** 287 mapped links → 6 candidate pages → **105 rows**,
pushed to tab `locations_firecrawl` in the "Site Agent Data" sheet
(13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4). Per-page: /contact 88, /contact-us 81 (80 were dupes
→ collapsed to 1, dedupe working), /find-an-office 23, homepage 5; two /locations/<practice> bio
pages correctly empty after retry. 99/105 rows have full street+city+zip.

**KNOWN ISSUE → next step:** 105 is OVER-counted (true unique ≈ 88–93, matching the original ~87
estimate). Two dedupe gaps: (1) 5 street-less homepage rows that duplicate real /contact rows;
(2) ~12 near-dup clusters (24 rows) with slightly different street spellings that street+city dedupe
missed. **Planned fix (not yet applied):** tighten `dedupe()` in scripts/firecrawl_locations.py to
(a) drop a street-less row when a same-city/zip row has a street, and (b) match near-dups on
`zip + normalized-street-prefix`. Then re-run allieddigestivehealth and re-push (the push overwrites
the tab). After that: validate on more flagged domains before any full ~3,982-domain batch.
DO NOT run the full batch without Yoshi's explicit go-ahead.

---

## 2026-05-25 — 4-tier fetch layer (fetch.py v2)

Added two new bot-evasion tiers to `src/fetch.py`:

- **Tier 2 (curl_cffi):** Chrome TLS fingerprint impersonation via `curl_cffi.requests.AsyncSession(impersonate="chrome120")`. Fires when httpx returns blocked/non-200. Bypasses TLS fingerprint-based WAFs that httpx fails on.
- **Tier 4 (Playwright+stealth):** Applies `playwright_stealth.stealth_async()` to the Playwright page before navigation. Patches `navigator.webdriver`, plugins, languages, etc. Fires when vanilla Playwright (Tier 3) returns < 5000 bytes.

Fetch order: **httpx → curl_cffi → playwright → playwright+stealth**. Cache writes on any successful tier. `fetched_with` field now reports which tier won.

Installed: `curl_cffi==0.15.0`, `tf-playwright-stealth==1.2.0`

Test results on 5 problem domains:

| Domain | Tier | Bytes | Blocked |
|---|---|---|---|
| qualityresearch.com | httpx | 133,934 | No |
| vitaliscrc.com | httpx | 298,283 | No |
| butchertownclinicaltrials.com | httpx | 234,655 | No |
| corpuschristicancer.com | playwright_stealth | 329 | **Yes** — returns 114-byte redirect shell at all tiers; hard block |
| cancercentersofflorida.com | httpx | 15,969 | No |

`corpuschristicancer.com` returns 114 bytes at every tier including stealth — likely a geo-redirect or login wall with no public content. Not a solvable fetch problem.

---

## 2026-05-22 ~17:30 — Eval harness built + 3 fetch bugs fixed + first accuracy numbers

### Eval harness (evals/eval.py) ✅
Built from scratch. Per-field comparators for all 8 fields:
- `canonical_org_name`: case-insensitive substring either direction
- `hq_phone` / `recruitment_phone`: digits-only, strip leading 1 if 11 digits, last-10 compare; null=null counts as match for recruitment
- `hq_address`: lenient — matches if street number OR city (4+ char word) OR state (2-letter) present
- `location_count`: extracts numeric+plus tokens, substring match; soft match on base number
- `site_type` / `trials_status`: exact after lowercase
- `research_url`: normalize (strip protocol/www./trailing slash/lowercase); soft if same domain different path

Idempotent (skips fully-scored domains), per-domain error handling, cost cap $5 / max 30 domains.
Writes `data/eval_results.csv` (long format, one row per domain-field) and `EVAL_REPORT.md`.

### Three fetch bugs fixed in src/fetch.py (all committed)

**Bug A — Playwright false positive (qualityresearch.com):** `_is_blocked()` was re-run on
Playwright output after successful fallback. `"cloudflare"` in a Turnstile `<script>` tag and
`"enable javascript"` in a WPForms `<noscript>` tag caused false positives on real content.
Fix: trust Playwright when HTML > 5000 bytes; skip `_is_blocked()` on Playwright output entirely.
Tagged `fetch-layer-v1`.

**Bug B — httpx false positive (butchertownclinicaltrials.com):** `_is_blocked()` also fired on
httpx 200 responses containing `"cloudflare"` deep in legitimate JS bundles. httpx returned
227KB of real ophthalmology trials content; pattern at byte 217,035 discarded it and fell through
to Playwright which timed out.
Fix: skip `_is_blocked()` pattern check entirely when `status=200` AND `len(html) > 5000`.
Committed separately. butchertown now scores 7/7 fields correctly.

**Rule now:** `_is_blocked()` runs only when `status != 200` OR `body < 5000 bytes`.

### extract.txt v3 → v4 (location_count digit fix)
Added rule: return `location_count.value` as a digit (e.g., "1", "90+"), NOT prose like
"single location". Prose only when count is genuinely ambiguous. This fixed the 15% → 69% jump.

### Eval results (post-fix, 30 domains scored, 2 unreachable):
| Field | Accuracy |
|---|---|
| canonical_org_name | 85% |
| hq_phone | 85% |
| hq_address | 77% |
| recruitment_phone | 100% |
| location_count | 69% |
| site_type | 81% |
| research_url | 92% |
| trials_status | n/a (filled by CT.gov, not scored) |

### Other outputs produced this session
- `LOCATIONS_REVIEW.md` — per-domain location list review for all 23 dedicated golden domains
- `data/fetch_failures.md` — diagnosis of cra-al.biz (SSL), butchertown (fixed), vitaliscrc (SPA)
- `data/output_orgs.csv` — 124-row wide-format CSV of all 32 golden domains, ready for Sheets
- `data/output_locations.csv` — per-location rows for all 23 dedicated domains
- Q3 + Q4 added to QUESTIONS_FOR_USER.md

### Remaining known issues (not fixed, logged in QUESTIONS_FOR_USER.md)
- Q4a: `vitaliscrc.com` — JS SPA, body empty after Playwright. Defer to v2 (selector-based wait).
- Q4b: `cra-al.biz` — SSL cert mismatch, permanently unreachable. Mark skip in TAM.
- Q2: `smoke_test.py` has 3 bugs (tuple unpack, wrong schema, loc rows dropped). Deferred.
- `site_type` bias toward "dedicated" — model over-classifies embedded/unclear sites as dedicated.
  Affects 4 domains. Prompt tuning needed but requires Yoshi ground-truth review first.
- `acuroresearch.com` phone golden data has malformed extension format `501) 224-1156 X7-5555`
  causing comparator to parse wrong digit string. Fix: strip `X\d+` extension before digit compare.

---

## 2026-05-22 ~12:10 — Redesign: per-location extraction implemented + 4-site acceptance test ✅

Implemented REDESIGN_BRIEF.md in full:

**Schema** (`src/schema.py`): Added `Location` model (location_name, address_street/city/state/zip,
phone, source_url, snippet, confidence) and `Locations` wrapper for instructor. Added
`locations: list[Location] = []` to `SiteProfile`. Existing Evidence fields unchanged.

**New prompt** (`prompts/locations.txt` v1): Dedicated location extraction prompt with site_type-
conditional rules — dedicated sites: enumerate all; embedded/unclear: only include locations with
explicit research linkage in snippet.

**New module** (`src/location_extract.py`): `extract_locations(domain, site_type, homepage_html,
additional_pages)` — third LLM call, instructor-enforced against `Locations` wrapper. Uses same
`extract_page_sections()` structured blocks as main extractor.

**Pipeline** (`src/pipeline.py`): Added Step 5 — conditional location extraction after main
extraction. Runs if site_type in {dedicated, embedded, unclear} and location call count under cap.
Returns `(org_row, loc_rows)` tuple. No bare httpx anywhere — all fetches via `fetch()`/`fetch_url()`.

**Two-CSV output** (`src/main.py`): `output_orgs.csv` (one row per domain, Evidence fields) and
`output_locations.csv` (one row per Location). Both append-only, both idempotent.

**Config**: Added `MAX_LOCATION_EXTRACTOR_CALLS_PER_RUN = 50`.

**Planner** (`prompts/planner.txt` v2): Added /our-locations, /sites, /research-sites,
/clinical-research-locations, /clinical-trials/locations, /find-a-trial to URL priority list.

**Bug fixed during test**: `extract.py` field-counting loop called `.confidence` on `locations`
(a list, not Evidence). Fixed by skipping `locations` field in both the log call and the
`fields_found` counter.

---

**4-site acceptance test results** (total est. cost: $0.072):

**pennmedicine.org** (embedded AMC, JS-heavy, playwright for subpages):
- 5/8 Evidence fields found
- site_type: "embedded" [high]
- canonical_org_name: "Penn Medicine" [high], hq_phone: +18007897366 [high]
- hq_address: "Philadelphia, PA" [high] (partial — no street; not on fetched pages)
- research_url: "pennmedicine.org/Research" [high] — NOW high (playwright fetched the page)
- location_count: not_found (Penn doesn't label per-location research prominently)
- locations (1): Penn Medicine | Philadelphia, PA | high | "Explore opportunities to
  participate in clinical trials..." — correct per brief (embedded, small list expected)

**velocityclinical.com** (dedicated CRO, 90+ sites):
- 6/8 Evidence fields found; all high
- locations (20): capped at 20 per prompt rule. Locations span US, Germany, UK — all verbatim
  snippets from the locations-by-state page listing. HQ entry present (Durham, NC). ✅

**medpace.com** (dedicated CRO, global):
- 7/8 Evidence fields found; all high
- locations (20): capped at 20. Includes Cincinnati HQ + full street addresses for Dallas,
  Denver, Mexico City, Belgium, Czech Republic, Denmark, France, Germany, Hungary, Israel,
  Italy, London, Netherlands, Poland, South Africa, Spain, UK (Stirling), Medpace Phase I
  Unit. All high confidence with verbatim street address snippets. ✅

**omnicureresearch.com** (dedicated, small — PRIMARY acceptance criterion):
- 7/8 Evidence fields found; all high
- locations (2): ✅ EXACTLY as expected:
    1. Doral (Main Office) | Doral, FL | high | "8880 NW 20th St Suite M, Doral, FL 33172"
    2. Endocrinology Branch Office in Palm Beach | Palm Beach Gardens, FL | high |
       "New Endocrinology Branch Office in Palm Beach: 11211 P..."
- This was the case that triggered the redesign. v1 prompt passes on first try.

**STOPPED** — awaiting user review before smoke test.

---

## 2026-05-22 ~12:00 — Phase 5a/5b complete, smoke test PAUSED pending schema decision

Phase 5a (pipeline) and 5b (smoke test domain list) are built and import-checked. Smoke test
execution is PAUSED at user request pending a schema decision on per-location data.

**What's built and ready to run:**
- `src/fetch.py` — updated with `fetch_url(url)` for arbitrary subpage fetches. Both `fetch()`
  and `fetch_url()` share the same httpx → blocked-detection → playwright fallback logic and
  cache. Incapsula added to block-pattern list.
- `src/pipeline.py` — fully wired: fetch → planner → fetch planned pages via fetch_url() (no
  bare httpx) → extract → ctgov. Cost accumulator tracks estimated spend per run and aborts if
  cap is reached. All errors captured in output row, never raised.
- `src/main.py` — CLI entry point: reads input CSV, skips processed domains (idempotent),
  runs with asyncio.Semaphore, appends each row immediately, logs cost.
- `scripts/smoke_test.py` — smoke test runner with summary table; hardcoded $5 cap, 20-domain
  limit, concurrency=5 per user spec.
- `data/smoke_test_domains.csv` — 20 domains across 5 categories:
    - 5 dedicated CROs: velocityclinical.com, medpace.com, iconplc.com, ppd.com, clinipace.com
    - 5 large AMCs: pennmedicine.org, clevelandclinic.org, hopkinsmedicine.org, ucsfhealth.org,
      mountsinai.org
    - 5 small practices: ctifairfax.com, orlandoclinicalresearch.com, anchorclinical.com,
      floridaclinicalresearch.com, suncoastresearch.com
    - 3 multi-location: javara.com, corevitasclinicalresearch.com, segaltrials.com
    - 2 likely broken: clinicaltrialsnetwork.com, synexus.com

**Pending schema decision:**
User is reconsidering whether to add per-location address/phone extraction for multi-location
organizations. Current schema has `location_count` (a string like "90+ sites") but no
structured per-location data. This is a meaningful architectural question:
- Adding per-location data changes `SiteProfile` structure (Evidence can't hold a list)
- It would require a new `locations: list[LocationEvidence]` field or similar
- It affects prompt design, output CSV column count, and review UI layout
- Changing schema after smoke test runs means reprocessing all rows

Waiting for user confirmation before running smoke test.

---

## 2026-05-22 ~11:15 — Prompt fix: extract.txt v1 → v2 (per user review)

User observed that the v1 prompt allowed non-null values without snippets (research_url returned
with confidence=low and snippet=None on pennmedicine.org). Fixed in v2:
- Rule 4 now states: snippet is MANDATORY for any non-null value. No snippet → value=null,
  confidence=not_found. No exceptions.
- Rule 5 now clarifies: confidence=low is for "snippet exists but inference is weak," NOT for
  missing snippets.

Re-ran extractor on cached pennmedicine.org homepage with v2 prompt. Result:
- research_url: now correctly not_found (no verbatim snippet in page text)
- canonical_org_name: high → medium (snippet supports name indirectly, not explicitly)
- All other fields unchanged

Also diagnosed why hq_phone/hq_address came back not_found in prior run:
- /Contact-us was fetched via bare httpx in the __main__ test harness (not via fetch())
- httpx got 200 but body was Incapsula bot-challenge: "Request unsuccessful. Incapsula incident ID..."
- That fake content was passed to the extractor as if real
- Fix needed in pipeline.py: planned-page fetches must go through fetch() (with playwright
  fallback), not bare httpx. Logged as a known issue for Phase 5.

---

## 2026-05-22 ~10:55 — Phase 4: CT.gov cross-reference ✅

Built `src/ctgov.py`. Async function `get_trials_status(canonical_org_name)` queries the
ClinicalTrials.gov API v2. Discovered during testing that the API does NOT return a `totalCount`
field — it returns a `studies` list + optional `nextPageToken`. Fixed the parsing to use
`len(studies) > 0` and `bool(nextPageToken)` for display counts.

Logic: ≥1 active study → value="active"/confidence="high"; 0 active but ≥1 historical →
value="inactive"/confidence="medium"; 0 total → value="unknown"/confidence="low".

Tests in `tests/test_ctgov.py` — 3 tests, all pass:
- `test_mayo_clinic_has_active_trials` → value="active", confidence="high" ✅
- `test_empty_name_returns_not_found` → confidence="not_found" ✅
- `test_fake_org_returns_unknown` → value="unknown", confidence="low" ✅

**"Done when" met:** CT.gov lookup runs for a known org and returns plausible status.

---

## 2026-05-22 ~10:50 — Phase 3: Extractor ✅

Built `src/extract.py` and `prompts/extract.txt` (v1). Extractor cleans page HTML with
trafilatura, builds a multi-page prompt block (each page prefixed with "PAGE: <url>"), and
makes one Sonnet 4.6 call via instructor enforced against `SiteProfile`.

Also built `src/pipeline.py` (not yet tested end-to-end; that's Phase 5).

Live test on pennmedicine.org (homepage + 3 planned pages via httpx, all from cache):
- 4 pages passed to extractor, 3,251 prompt chars, LLM call took 5.0s
- 3/8 fields found:
  - canonical_org_name: "Penn Medicine" / high / snippet: "First then. First now. From the
    nation's first chartered hospital to firsts in cell and gene therapy..."
  - site_type: "embedded" / medium / snippet: "Our teams provide compassionate, coordinated
    care for individuals and families across Pennsylvania, New Jersey, and beyond."
  - research_url: "https://pennmedicine.org/Research" / low / no snippet (URL found in links
    list but no verbatim supporting text in extracted page content)
- 5/8 fields correctly returned not_found (phone, address, recruitment phone, location count,
  trials_status) — model did not hallucinate values for fields absent from the page text

**Known issue observed:** research_url has low confidence and no snippet. The planner selected
the /Research URL but when httpx fetched it the page returned enough text for the extractor to
see it as a candidate, yet the extractor couldn't find a verbatim snippet to support it. Likely
because trafilatura extracted very little from that page (heavily JS-rendered). Worth examining
when smoke test runs with playwright fallback.

**"Done when" met:** valid SiteProfile produced from a real domain; LLM log written to
`data/llm_log.jsonl`.

---

## 2026-05-22 ~10:45 — Phase 2: Planner ✅

Built `src/planner.py` and `prompts/planner.txt` (v1). Planner uses BeautifulSoup to extract
internal links from raw HTML and trafilatura to get clean homepage text, then asks Sonnet 4.6
to pick up to 5 URLs. Post-filtering enforces that returned URLs must have appeared in the
extracted link list (prevents hallucinated URLs).

First test on mayoclinic.org: httpx got 403, playwright timed out after 30s — site is fully
blocked. Switched test domain to pennmedicine.org.

pennmedicine.org: httpx returned 212 bytes (blocked), playwright returned 706KB. From that
page, 44 internal links were extracted. Planner returned 5 URLs:

  [1] https://pennmedicine.org/Research — "Directly covers clinical research/trials activity..."
  [2] https://pennmedicine.org/About — "Likely contains org name, HQ address..."
  [3] https://pennmedicine.org/Contact-us — "Primary source for main phone number..."
  [4] https://pennmedicine.org/About/Pioneering-the-future-of-medicine — "May detail research
      mission, number of locations..."
  [5] https://www3.pennmedicine.org/departments-and-centers — "Could reveal number of physical
      locations..."

All 5 URLs verified to exist in the extracted link list (no hallucinations). One URL from an
earlier jhmi.edu run was hallucinated and correctly dropped by the post-filter.

Decision: planner prompt does not ask the model to explain when it finds no useful pages — added
a graceful empty-list return path for sites with no internal links (e.g. jhmi.edu gateway).

**"Done when" met:** planner runs on a real domain and returns plausible 3-5 URL list; LangSmith
trace/local JSONL log written.

---

## 2026-05-22 ~10:40 — Phase 1: Schema + fetch layer ✅

Built `src/schema.py` exactly per BUILD_PLAN.md spec. `Evidence` with value/source_url/snippet/
confidence; `SiteProfile` with 8 fields all defaulting to not_found.

Built `src/fetch.py`: async `fetch(domain)` with httpx (3 retries, exponential backoff),
blocked-site detection (403/429/503 status OR body < 500 bytes OR Cloudflare/PerimeterX/Akamai
markers in body), playwright fallback (headless Chromium, 30s timeout), cache to
`data/cache/{domain}.html`.

Schema tests (5/5 pass):
- Evidence defaults to not_found ✅
- All confidence values accepted ✅
- SiteProfile all fields default to not_found ✅
- Snippet max_length=300 enforced ✅
- SiteProfile with partial data ✅

Fetch tests (7/7 pass):
- example.com fetches successfully ✅
- Cache file created on first fetch ✅
- Cache hit on second call (fetched_with="cache") ✅
- 403/429/503 detected as blocked ✅
- Body < 500 bytes detected as blocked ✅
- Cloudflare marker in body detected ✅
- Normal page not flagged as blocked ✅

CLI smoke: `python -m src.fetch example.com` prints clean HTML — ✅

**"Done when" met:** fetch returns clean HTML; schema tests pass.

---

## 2026-05-22 — Phase 0: Project setup ✅

Created full directory and file skeleton per BUILD_PLAN.md spec:
`src/`, `data/cache/`, `prompts/`, `scripts/`, `tests/` directories; all stub files in place.

Wrote `pyproject.toml` with all deps from tech stack (anthropic, instructor, httpx, playwright,
trafilatura, beautifulsoup4, pydantic, python-dotenv, langsmith, streamlit, tenacity).

Installed `uv` (Astral) to manage Python — system only had Python 3.9.6; uv downloaded Python
3.11.15 and created `.venv`. Decision: use `uv` as the local Python/package manager going forward.

`playwright install chromium` succeeded; chromium launch verified.

Three smoke checks all pass:
- httpx GET example.com → 200 / 528 bytes
- Claude Sonnet 4.6 "hello" call → responded correctly
- LangSmith: no API key in .env → confirmed will use local `data/llm_log.jsonl` fallback

Note: `.env` has `ANTHROPIC_API_KEY` and `LANGSMITH_TRACING=false` but no `LANGSMITH_API_KEY`.
All LLM traces will go to `data/llm_log.jsonl`. Pipeline will work fine either way.

**Done when** criteria met. Moving to Phase 1.

---

## 2026-05-31 — 665 run completed + merged into canonical locations

**665 flagged run:** completed overnight (network blip at ~22:13 only broke the final Sheets push,
not extraction — re-pushed). Then a targeted re-run of the 89 empties recovered **57/89** (outage
casualties + flaky). Final Firecrawl set: **633 domains / 7,538 rows**. 32 flagged domains still
empty → candidates for a systematic-miss investigation (like epilepsygroup's offices.htm).

**MERGE (scripts/merge_locations.py):** (1) re-deduped Firecrawl per-domain on a tightened
**(state, city, street-number, street-name-word)** key — anchored on city+state instead of zip,
since inconsistent/missing zips across a site's pages left the same office as 2-3 rows
(ascendvision "1611 State Road 60" with zip ''/33859/33853). Collapsed **289** dups (7,538→7,249).
(2) Per-domain REPLACE into canonical: 624 domains' old rows dropped + Firecrawl rows substituted,
9 brand-new domains added (flagged sites that had 0 rows in the canonical before). Sanity: 0 replaced
domains still carry old rows.

**Result:** canonical `output_locations.csv` and the `locations` sheet tab → **17,308 rows / 3,927
domains** (+1,381 vs old). Backups: `output_locations.csv.bak-20260531_142235`,
`output_locations_firecrawl.csv.bak-*`. The 12-col schemas of the CSV and the `locations` tab match.

**NOTE:** the canonical CSV uses quoted multi-line fields (snippets), so `wc -l` overcounts — use a
CSV parser (true record count 17,308, not the ~34k physical lines).

**OPEN:** 32 still-empty flagged domains (list derivable: in flagged input, not in firecrawl CSV).
The tightened (state,city) dedupe key is NOT yet ported into firecrawl_locations.py's live dedupe()
— only applied in the merge. Port it if more runs are planned.

---

## 2026-05-31 (cont.) — Diagnosed the 32 still-empty + tightened hallucination guard + re-merge

**Investigated the 32** (scripts/diagnose_empty.py — per-domain map/harvest/candidate + raw scrape,
bucketed). NOT a pipeline bug. Findings: (a) several were transient high-concurrency (c30) timeouts
on big domains — recover at lower concurrency; (b) many domains' reachable pages have NO real street,
so the LLM FABRICATES and the guard (correctly) zeros them; (c) some are Firecrawl-blocked or JS
store-locators.

**KEY FIX — hallucination guard hardened.** The LLM fabricates SERIES reusing one number
(universitygi: "2025 West River", "2025 Warren", "2025 Smithfield"… — real # is 148; it reused the
year 2025). Old `street_on_page` checked number and street-word INDEPENDENTLY, so a fake passed when
the year + some real place-name both appeared anywhere on the page. NEW: require the number and its
first DISTINCTIVE (non-road-type) street word to be ADJACENT (≤50 chars) on the page. Validated:
universitygi 12→0 (all fake), retina-doctors→15 & bostonivf→20 (real kept), aigmedical 3 kept (real
"101" suites), baptistcancernetwork 6→2 (4 fakes dropped). Fabrication signature scan found only 3
polluted domains total — old guard wasn't leaking broadly.

**Re-merged cleanly from the ORIGINAL canonical backup** (not compounding on merge-1) with the
de-faked firecrawl set: canonical `output_locations.csv` + `locations` tab → **17,320 rows / 3,927
domains** (627 replaced + 9 new, 286 cross-page dups collapsed, 0 stale rows).

**FINAL COVERAGE: 636 / 665 flagged domains have locations.** 29 residual still-empty
(`data/still_empty_final.csv`) — genuinely hard: Firecrawl-blocked sites, JS store-locators, or sites
listing locations with no street address on any reachable page. These need bespoke handling, not a
code fix. Backups: output_locations.csv.bak-20260531_142235 (original), *.bak-precleanup-*.

---

## 2026-05-31 (final) — Residual sweep + practical ceiling

Probed the 29 residuals: each has a DIFFERENT cause (no single fix) — transient Firecrawl blocks,
cross-domain redirects (nyoh.com → newyorkoncology.com), and JS-only shells (sunrisepractices
/locations = 143-char shell). One more pass recovered just 1 (evolutionclinicaltrials.com) →
diminishing returns. STOPPED here.

**FINAL: 637/665 flagged domains covered.** Canonical `output_locations.csv` + `locations` tab =
**17,318 rows / 3,927 domains**, fabrication-cleaned (hardened street_on_page adjacency guard).
28 residual need bespoke handling (browser automation for JS locators, redirect-following, or they
genuinely don't publish street addresses) — not worth automated chasing. `data/still_empty_final.csv`.

---

## 2026-05-31 — ZIP enrichment via US Census geocoder

Filled missing address_zip from street+city+state using the free US Census geocoder
(geocoding.geo.census.gov, no API key). scripts/fill_zips.py. Of 522 rows missing zip, 204 were
geocodable (had street+city+state); **145 filled (71%)**. Missing zip 522 → 377 (59 geocoder
no-match + 318 missing more than zip). Canonical output_locations.csv + `locations` tab updated
(17,318 rows). Backup: output_locations.csv.bak-prezip-*.

---

## 2026-05-31 — Normalized states/zips + dropped international (scripts/normalize_locations.py)

On output_locations.csv: (1) DROPPED 34 truly international rows (Canada/UK/Mexico/Australia/NZ/
Germany/LatAm/etc. — foreign state values); (2) NORMALIZED 609 state values to 2-letter US codes
(full names "Florida"→FL, punctuated "N.C."→NC/"D.C."→DC; lagunaclinicaltrials "US"→TX from zip;
elevateclinical "USA" had no address→blank); (3) NORMALIZED 279 zips to exactly 5 digits (zip+4→
first5, 840101→84010, <5 digits→blank). Result: 17,318 → **17,284 rows**, sanity = 0 non-US states,
0 non-5-digit zips. Canonical CSV + `locations` tab updated. Backup: output_locations.csv.bak-prenorm-*.

---

## 2026-05-31 — Within-domain dedupe + street normalization (scripts/street_norm.py, dedupe_within.py)

Step 1 of dedupe (within-domain). (1) Rewrote address_street to a canonical display form — expand
directionals + street types (St→Street, Ave→Avenue, N→North), Title-case, standardize unit marker,
PRESERVE suite. Handled ordinals (88th), '#'→Suite (no "Suite Suite"), floor-before-marker ("4th
Floor"), and St-as-State ("St Rd 60"→"State Road 60"). 11,681 streets rewritten. (2) Collapsed
within-domain rows with identical normalized street (incl suite) + city + state, keeping the
most-complete row — suites kept DISTINCT (Yoshi's call). 175 dup rows removed. 17,284 → **17,109
rows**. ~9 rows retain an abbreviation (malformed suite-first source addresses). Canonical CSV +
`locations` tab updated. Backup: output_locations.csv.bak-prededup-*. NEXT (if wanted): cross-domain
dedupe.

---

## 2026-05-31 — Location existence verification (Census + Google hybrid) + St->Saint fix

Cheap existence check (no name matching). STAGE 1: free US Census batch geocoder
(scripts/verify_locations.py) -> 88.1% confirmed (Match/Tie); 1,803 No_Match (~20% Census
false-negative rate). STAGE 2: Google Geocoding API on the 1,803 (scripts/verify_google.py; user
enabled Geocoding API + added it to the GOOGLE_PLACES_API_KEY's allowlist). Google resolved 1,486
more. **FINAL: 16,566 verified (96.8%), 315 suspect (1.8%), 226 no-address (1.3%), 2 error.**
Report: data/location_verification_final.csv (per-row census/google/final verdict). Suspect = Google
partial_match or ZERO_RESULTS (e.g. fake "170 Dr Arla Way" -> partial; "Wonderland NJ 00057"
placeholder). Verdict ignores org-name (pure existence).

The suspect list exposed a bug from the earlier dedupe step: canonical_display had expanded
"St"->"Street" even when it meant SAINT ("820 Street Sebastian Way", "St Andrews"->"Street Andrews").
FIXED street_norm.py: "St"+name->Saint, "St"+road-type/dir/end->Street (suffix), "St"+Rd/Hwy->State.
Re-derived from the prededup backup; 33 corrupted rows -> 108 correct "Saint" rows, 0 bug rows remain
(the 3 flagged are real numbered streets). Re-ran within-domain dedupe (still 175 removed, 17,109
rows). Canonical CSV + `locations` tab updated.

---

## 2026-06-01 — Verified user's manual review + promoted 11 needs_review->passed

Yoshi manually reviewed the validation_status in the `locations` sheet (cleared most needs_review,
fixed some addresses). Verified via Google geocoding: all 52 of his needs_review->passed flips are
real addresses (the 1 flagged "suspect", nislabs 1437 Esplanade, is real — geocoder just needed
"Ave"). Of the 87 still needs_review, 11 had real verified addresses -> promoted to 'passed' via
targeted cell updates (scripts/verify_user_review.py, update_validation.py). 76 remain needs_review
(all blank-street — no address to verify). Sheet = local now in sync (pulled sheet as authoritative
since Yoshi also edited addresses there, e.g. moved city out of street field). Final
validation_status: passed 9,775 | needs_review 76 | blank 7,257 (firecrawl). Local backup:
output_locations.csv.bak-presync-*. NOTE: the sheet is now the source of truth for validation_status
+ manual address edits — pull it before future edits rather than pushing the old local CSV over it.

## 2026-06-01 — Reconciled CSV <-> sheet (now identical)

Diff revealed: (1) the sheet's header cell K1 read 'confidence' (dup) instead of 'validation_status'
— fixed in place; (2) Yoshi deleted the axisclinicalsusa.com 'AXIS India' blank-address row from the
sheet, which local still had (caused a 1-row offset cascade). Made local := sheet (authoritative,
has Yoshi's address+status edits), correct header. Cell-by-cell re-diff: 0 differences, 17,107 data
rows both sides. validation_status: passed 9,775 | needs_review 76 | blank 7,257. Backup:
output_locations.csv.bak-prereconcile-*.

## 2026-06-01 — Added revivalresearch.org locations (manual, from Yoshi)

revivalresearch.org had 8 blank-street stub rows (state-only, was flagged UNPARSEABLE "25+"). Yoshi
pasted the real provider/location list. Parsed -> 13 unique addresses (deduped repeats), canonicalized
streets (street_norm.canonical_display), geocode-verified all 13 = exists/passed, source='manual'.
Replaced the 8 stubs. output_locations.csv 17,107 -> 17,112 rows. Pushed to `locations` tab (safe full
push since local==sheet after reconcile); re-diffed = 0 differences. Backup: bak-prerevival-*.

## 2026-06-01 — Added rcaresearch.com locations from "Manual Locations Fill In" Google Doc

Read the Google Doc (Drive MCP) "Manual Locations Fill In" (id 1Lg43...) — Yoshi confirmed it's all
rcaresearch.com (Retina Consultants of America network). Parsed 62 blocks (scripts/parse_rca.py from
data/rca_manual.txt): dropped noise (RGF/RCTX logos, Directions), stripped building-name prefixes,
canonicalized streets, captured phones, mapped full state names->abbr, geocode-verified (60 passed,
1 needs_review = Edina "Suite 300 & 325" formatting). Within-domain dedup collapsed 1 exact dup
(4100 N Mulberry KC) -> 61. REPLACED the 38 old blank-street stubs. output_locations.csv 17,112 ->
17,135. Pushed to `locations` tab, re-diffed = 0 differences. 18 states (added TN/TX/UT/WA). Backup:
bak-prerca-*.

## 2026-06-01 — akdhc.com: scraped all 48 location pages

Yoshi: click through every location link on akdhc.com/locations/ and update the sheet. Scraped the
hub for links -> 48 /locations/<x>/ detail pages (scripts/scrape_akdhc.py, concurrency 8). Extracted
+ canonicalized + geocode-verified each. The street_on_page guard false-dropped 3 (avondale,
deer-valley, westgate-surgery — real addresses it couldn't string-match); recovered via direct
geocode (scripts/recover_akdhc.py). Final: 48 unique (47 passed, 1 needs_review = 655 S Dobson Rd
Phoenix city/zip mismatch). source='firecrawl'. Replaced the 19 old akdhc rows. Pulled sheet fresh
first, pushed (commit_akdhc.py), re-synced local: 0 diffs. Sheet 17,135 -> 17,164 rows.
Backup: bak-preakdhc-*.

## 2026-06-01 — hand2shouldercenter.com from Manual Locations doc (16 locations)

Parsed 16 PA/NJ locations from the doc (scripts/parse_h2s.py). Handled building-name + suite on
separate lines (before/after street): "The Franklin, Suite G114"+"834 Chestnut Street" -> "834
Chestnut Street, Suite G114"; "950 Pulaski Drive"+"Suite 100" merged. Fixed the broken West Chester
row (was ", Suite 1 B-a" -> "915 Old Fern Hill Road, Suite 1 B-a"); added 5 missing (Glen Mills,
Ridley Park, Paoli, Exton, Cherry Hill). All 16 geocode-verified passed, source=manual. Replaced
11 old rows. Pulled sheet fresh, pushed, re-synced: 0 diffs. Sheet 17,164 -> 17,169. Backup:
bak-preh2s-*.

## 2026-06-01 — headlandsresearch.com network (20 US/PR sites) from Manual Locations doc

Parsed the Headlands Research network from the doc (scripts/parse_headlands.py): 23 sites with their
own names (Artemis, Clinvest, JEM, Headlands Research - X, Summit, TMA x2, CMR Center PR, etc.).
Canonicalized, geocode-verified -> 20 US/PR all passed; 3 Canada (Okanagan/Kelowna, Richmond,
Toronto) flagged international and DROPPED per Yoshi. location_name = site name. source=manual.
Replaced 21 old headlandsresearch.com rows. Pulled fresh, pushed, re-synced: 0 diffs. Sheet
17,169 -> 17,168. Backup: bak-prehl-*.

## 2026-06-01 — advancedderm.com: filled 3 missing locations

Doc had 152 named locations, data had 149. Diffed by location_name (scripts/diff_adv.py) -> 3 truly
missing (Englewood 9570 Kingston Ct; Westminster Federal Blvd Ste 210; Winter Park Aesthetic Center
1801 Lee Rd Ste 175). 4th flagged ("St. Petersburg" vs "St Petersburg") = name-period mismatch, same
existing row, not added. Added the 3 (canonicalized, geocode-verified passed, source=manual). Pulled
sheet fresh, appended, re-synced: 0 diffs. advancedderm.com 149 -> 152. Backup: bak-preadv-*.

## 2026-06-01 — advancedurologyinstitute.com: filled 2 missing (Oxford Leesburg/Ocala)

Doc (markdown format, 35 FL locations) vs data: 33 matched by name, 2 missing -> added Oxford Leesburg
(12109 County Road 103 Ste 2) + Oxford Ocala (Ste 1), both geocode-verified passed, source=manual.
AUI 35 -> 37. Pulled fresh, appended, re-synced: 0 diffs. Backup: bak-preaui-*.
FLAGGED FOR YOSHI (not in doc, blank name, firecrawl): "1490 S Magnolia Ave Ste 1, Ocala 34471" and
"80 Doctors Drive, Panama City 32405" — possibly closed/relocated; awaiting keep-or-remove decision.

  -> Yoshi decided KEEP the 2 not-in-doc rows (Ocala Magnolia, Panama City Doctors Dr); left as-is (blank name).

## 2026-06-01 — unitedgi.com replaced with doc as source of truth (85 locations) + zip_check column added

Earlier: added zip_check column (13th col) flagging zip<->city/state mismatches via offline `zipcodes`
DB (scripts/zip_check.py): 17 state_mismatch, 16 zip_invalid (high-conf), 331 city_mismatch (fuzzy/
USPS-city noise). Blank state/city not flagged.

unitedgi.com (United GI / United Medical Doctors, ~90 multi-specialty offices, markdown doc): parsed
85 with addresses (scripts/parse_unitedgi.py, scripts/unitedgi_raw.txt), handled malformed addresses
(missing-comma "Ste. 100 Riverside", plural Stes). Geocode-verified (83 passed, 2 review), zip_check
computed, source=manual. REPLACED the 28 old rows (source of truth). Pulled fresh, pushed (13-col
schema preserved), re-synced: 0 diffs. Total 17,222 rows. Backup: bak-preugi-*.

## 2026-06-01 — rainier-research.com: extracted 9 sites from "Learn More" sell-sheet PDFs

/our-sites links to 9 site sell-sheet PDFs (squarespace). Address is in the PDF footer. 6 had it in
the text layer (pypdf extract, phone-anchored; Firecrawl markdown garbled it) — RCRC, SCRC, PRRC,
NCRC, Altoona, SRC; 3 image-only footers (WCRC, SVRC, DSA) read VISUALLY via the Read tool (renders
PDF). Installed pypdf. Fixed source quirks: "Jeerson"->Jefferson (ligature), "249 E, 249 NC-54"->
"249 NC-54". All 9 geocode-verified passed, 0 zip_check flags, source=manual, phones captured.
REPLACED the 10 messy old rows (several wrongly stamped 800 SW 39th St). Pulled fresh, pushed (13-col),
0 diffs. Total 17,221. Backup: bak-prerainier-*. Scripts: parse_rainier.py.

## 2026-06-01 — medvinresearch.com: replaced with doc's 12 locations
12 CA locations from the doc, canonicalized + geocode-verified (all passed, 0 zip flags), phones
normalized, source=manual. Replaced the existing 12. Pulled fresh, pushed (13-col), 0 diffs. Note:
"Menifee" office's city is Sun City CA 92586 per doc. Backup: bak-premedvin-*.

## 2026-06-01 — biopharmainfo.net 32 locations + STOPPED street normalization (Yoshi pref)

biopharmainfo.net: parsed 32 (city from each block's region header; street/zip from block lines).
First push used canonical_display which corrupted streets (Mccoll, Goodlette-frank, Suitesuite) ->
Yoshi: "stop normalizing the address streets, keep it how it is." Saved memory
site_agent_no_street_normalization. RE-PUSHED with RAW street text (verbatim, only strip glued city/
whitespace). All 32 geocode-verified exists. Replaced 21 old -> 32. Total 17,232. 0 diffs.
FLAG: San Antonio Stone Oak zip 77258 = zip_check city_mismatch (likely typo for 78258; awaiting
Yoshi). NOTE: street_norm.py canonical_display still exists (used the Suite# fix) but is NO LONGER
applied to incoming streets per the new preference. Backup: bak-prebiopharma-*.

## 2026-06-01 — alabamaoncology.com 9 locations (verbatim streets)
9 Birmingham-area oncology locations from doc. Streets kept VERBATIM (no normalization) per new
pref — multi-line street/suite/building lines joined as-is (Women's Medical Plaza, Grandview Cancer
Center, POB III Suite105-A preserved). state->AL, zip kept. Geocoded (6 passed, 3 review = Brookwood
2022/2006 Medical Center Dr + Princeton, real but no rooftop match), 0 zip flags, source=manual.
Replaced 9. 0 diffs. Total 17,232. Backup: bak-prealox-*.
