---
name: project-state
description: Site enrichment agent — current build state, eval numbers, known issues
metadata:
  type: project
---

**Project:** Site Enrichment Agent — extracts structured data from ~7K clinical research site websites.

**Stack:** Python 3.11, httpx + Playwright, instructor + Claude Sonnet 4.6, Pydantic schema, trafilatura, append-only CSVs.

**Build state as of 2026-05-22:**
- Phases 0–5 complete (setup, schema, fetch, planner, extractor, CT.gov, pipeline, locations)
- evals/eval.py: full eval harness against data/golden.csv (32 rows). Writes eval_results.csv + EVAL_REPORT.md.
- data/golden.csv: 32 rows, all with expected_* columns filled by Yoshi

**Latest eval accuracy (post-fix, 30 domains scored):**
- canonical_org_name: 85%
- hq_phone: 85%
- hq_address: 77%
- recruitment_phone: 100%
- location_count: 69%
- site_type: 81%
- research_url: 92%

**Key files:**
- src/pipeline.py — orchestrator; process_row() returns (org_row, loc_rows)
- src/fetch.py — httpx + Playwright fallback; block detection only on non-200 or <5000 byte responses
- src/extract.py — main extractor (instructor + Sonnet 4.6)
- src/location_extract.py — dedicated location extraction pass
- prompts/extract.txt — v4 (location_count digit rule added)
- prompts/locations.txt — v1
- prompts/planner.txt — v2
- data/golden.csv — 32 golden rows
- data/eval_results.csv — latest eval scores (long format)
- data/output_orgs.csv — wide format, all 32 domains, ready for Sheets
- data/output_locations.csv — per-location rows

**Known pending issues:**
- Q2: smoke_test.py has 3 bugs (deferred)
- Q4a: vitaliscrc.com JS SPA — defer to v2
- Q4b: cra-al.biz SSL broken — permanent skip in TAM
- site_type bias toward "dedicated" — needs Yoshi ground-truth review before prompt fix
- acuroresearch phone comparator: golden has malformed extension `501) 224-1156 X7-5555`; easy fix in evals/eval.py compare_phone()

**Why:** location_count was 15% before extract.txt v4; two fetch false-positives (Playwright + httpx) recovered qualityresearch.com and butchertownclinicaltrials.com.
