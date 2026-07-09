# Site Enrichment Agent

Extracts structured data + evidence from ~7,000 clinical research site websites using a planner → extractor → optional verifier pipeline.

## Documents

- `BUILD_PLAN.md` — architecture, phased build order, acceptance criteria
- `CLAUDE.md` — project conventions, loaded by Claude Code every session
- `PROGRESS.md` — work log (Claude Code writes this)
- `QUESTIONS_FOR_USER.md` — questions Claude Code couldn't resolve alone
- `OVERNIGHT_SUMMARY.md` — recap written when overnight work stops
- `SMOKE_TEST_REPORT.md` — smoke test findings

## Setup (one time)

```bash
# Python 3.11+
pip install -e .
playwright install chromium

# Create .env from .env.example, fill in keys:
cp .env.example .env
# Edit .env with: ANTHROPIC_API_KEY, LANGSMITH_API_KEY, LANGSMITH_PROJECT=site-agent
```

## Overnight build (Claude Code, autonomous)

Tell Claude Code:

> Read `BUILD_PLAN.md` and `CLAUDE.md`. Start at Phase 0. Work autonomously through Phase 5, then stop. You have hard limits: 50 domains, $20, 5 smoke-test iterations. Write progress to `PROGRESS.md` and questions to `QUESTIONS_FOR_USER.md`. Do not cross the Phase 5 stop marker.

## When you wake up

1. Read `OVERNIGHT_SUMMARY.md`
2. Read `QUESTIONS_FOR_USER.md`
3. Read `SMOKE_TEST_REPORT.md`
4. Launch review UI on smoke output: `streamlit run scripts/review.py -- --csv data/smoke_output.csv`
5. Based on what you see, decide whether to start building the golden dataset (Phase 6)

## Running the full pipeline (later, with you driving)

```bash
# Once Phase 6 (golden) is built and Phase 7 (accuracy iteration) has hit targets:
python -m src.main --input data/input.csv --output data/output.csv
# Optional: --limit 100 to test on a slice first
```

## Cost reference

- Overnight smoke test: capped at $20
- Full 7K-row pass (single call per row): ~$210-250
- Full pass with verifier: ~$600-700
- Budget for ~3 iterations of full pass: ~$700 worst case
