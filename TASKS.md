# TASKS.md — Active work tracker

Update this file when starting a task (status: in progress) and when completing it (status: done).
On every session restart, read this file first to see what's in flight.

---

## In Progress

_(nothing — session ended cleanly)_

---

## Pending

### Fix acuroresearch.com phone comparator
- **Status:** pending
- **What:** Golden value `501) 224-1156 X7-5555` has malformed `(` and extension `X7-5555`.
  `_digits_only()` parses to wrong digit string. Fix: strip `X\d+` extension pattern before
  digit extraction in `compare_phone()` in `evals/eval.py`.
- **Impact:** 1 miss → 1 hit on acuroresearch.com hq_phone

### Fix smoke_test.py (3 bugs)
- **Status:** deferred — not blocking evals
- **Details:** See QUESTIONS_FOR_USER.md Q2
- **Bugs:** tuple unpack crash, wrong schema in _csv_columns(), location rows silently dropped

### site_type prompt tuning
- **Status:** pending Yoshi review
- **What:** Model over-classifies embedded/unclear sites as "dedicated". 4 misses in eval.
  Needs Yoshi to confirm ground truth for: gulfsouthclinicaltrials.org (embedded→dedicated),
  cibmtr.org (unclear→dedicated), nextstageclinical.com (embedded→dedicated),
  investigativeicr.com (unclear→dedicated). Prompt fix should tighten "embedded" and "unclear"
  signal descriptions.

---

## Done

- Phase 0: Project setup
- Phase 1: Schema + fetch layer
- Phase 2: Planner
- Phase 3: Extractor
- Phase 4: CT.gov cross-reference
- Phase 5a: Pipeline (src/pipeline.py)
- Phase 5b: Smoke test domain list (data/smoke_test_domains.csv)
- Per-location redesign: Location model, location_extract.py, two-CSV output
- 4-site acceptance test: velocityclinical, medpace, pennmedicine, omnicure — all passed
- Golden CSV moved to data/golden.csv (32 rows)
- evals/eval.py: eval harness built, 8-field comparators, idempotent, EVAL_REPORT.md output ✅
- fetch.py bug A: Playwright false-positive fix (qualityresearch.com) — tagged fetch-layer-v1 ✅
- fetch.py bug B: httpx false-positive fix (butchertownclinicaltrials.com) ✅
- extract.txt v4: location_count digit-not-prose rule — 15%→69% accuracy jump ✅
- LOCATIONS_REVIEW.md: per-domain location audit for 23 dedicated golden domains ✅
- data/output_orgs.csv: 32 golden domains, wide format, ready for Google Sheets ✅
