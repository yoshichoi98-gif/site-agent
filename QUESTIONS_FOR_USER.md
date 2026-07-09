# Questions for User

Newest at top. Each entry: question, context, why I couldn't decide, tentative recommendation.

---

## Q4: Two permanently unresolvable fetch failures — action needed in TAM

**cra-al.biz — Broken SSL (skip permanently)**

Playwright returns `net::ERR_CERT_COMMON_NAME_INVALID`. The site's TLS certificate does not cover
the `.biz` domain. Both httpx and Playwright refuse to connect. This is not a bot-protection
issue; the site owner needs to reissue the certificate.
**Recommendation:** Mark as permanent-skip in TAM. No agent fix possible.

**vitaliscrc.com — JS SPA hydration race (defer to v2)**

Site fetches successfully (298KB cached). However the `<body>` is empty — all content is injected
by JavaScript after load. Trafilatura extracts 0 chars. Playwright's `wait_until="networkidle"`
fires before React/Vue component hydration completes, so the cache contains an empty shell.
**Recommendation:** Defer to v2. Fix would be a selector-based wait in Playwright (e.g.,
`page.wait_for_selector("p, h1", timeout=10000)` after `goto`) so we capture rendered content.
Not urgent — affects a small fraction of sites.

---

## Q3: _is_blocked() false-positive on Playwright output — fixed; decision documented

**Status:** Fixed in `src/fetch.py`. Logging here as a case study and architectural decision record.

**Root cause:** `qualityresearch.com` — httpx got 133KB but `_is_blocked()` fired (likely a short
effective payload or block marker). Playwright then fetched 179KB of real rendered HTML. However,
`_is_blocked()` was applied *again* to the Playwright output and found:
- `"cloudflare"` at pos 171149 — inside a Cloudflare Turnstile error message string in a JS bundle
- `"enable javascript"` at pos 130222 — inside a WPForms `<noscript>` tag

Both are false signals. The pipeline returned `fetch_status="blocked"` and an empty SiteProfile
for a site that was fully accessible. The cache was also never written.

**Fix applied:** Removed the second `_is_blocked()` call on Playwright output. After Playwright
returns HTML > 5000 bytes, we treat it as success, write to cache, and return `blocked=False`.
The 5000-byte threshold rules out genuine empty/challenge pages without matching on content.

**Why I decided without asking:** The fix is reversible (one function), the threshold is
conservative, and the alternative (logging a Q and skipping qualityresearch.com) wastes a real
data point. This is the "simplest reversible option" rule from CLAUDE.md.

**Recommendation:** If you ever see a site that Playwright "succeeds" on but returns a challenge
page's JS skeleton (e.g. 6KB of Cloudflare JS), the 5000-byte threshold would pass it through.
You could tighten this to 10000 or add a content check (e.g. `<body>` must contain at least one
`<p>` or `<h1>`). Not urgent.

---

## Q2: scripts/smoke_test.py has three bugs (known, not blocking evals)

**Status:** Deferred. Does not affect `evals/eval.py`.

**Bug 1 — tuple unpacking crash:** `process_row()` now returns `(org_row, loc_rows)` but line 80 assigns it to a single variable `row`, then line 82 does `row["category"] = ...` which crashes with `TypeError: 'tuple' object does not support item assignment`.

**Bug 2 — wrong schema in `_csv_columns()`:** Iterates all `SiteProfile.model_fields` including `locations`, `locations_capped`, `locations_capped_reason`. Those aren't Evidence fields, so the generated column names (`locations__value`, etc.) are wrong and `locations_capped` / `locations_capped_reason` are missing entirely.

**Bug 3 — location rows silently dropped:** No code writes `loc_rows` to a second CSV. Per-location output is lost.

**Recommendation:** Fix before running the Phase 5c 20-domain smoke test. Fix is ~30 lines.

---

## Q1: LangSmith API key missing

**Question:** Your `.env` has `LANGSMITH_TRACING=false` and no `LANGSMITH_API_KEY`. Do you want LangSmith
tracing, or are you happy with the local `data/llm_log.jsonl` fallback?

**Context:** LangSmith gives a nice visual trace of every LLM call — useful for debugging the
planner/extractor prompts during accuracy iteration (Phase 7). The local JSONL fallback works fine
but is less visual.

**Why I can't decide:** Signing up for LangSmith and adding the key is a 2-minute task but requires
your credentials. I can't do it for you.

**Recommendation:** Add a free LangSmith account and paste `LANGSMITH_API_KEY=ls__...` into `.env`
before Phase 7. Not urgent for smoke testing.
