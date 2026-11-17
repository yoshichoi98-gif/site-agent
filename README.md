# Site Enrichment Agent

An AI research agent that visits thousands of clinical research site websites and turns each one into a clean, verified company profile: official name, headquarters, phone numbers, every location, what kind of business it is, and whether it actively runs trials. Every value comes with the URL and quoted text it was taken from.

## Why I built it

There are roughly 7,000 organizations that run clinical trials in the US. The only list of them comes from ClinicalTrials.gov, where names are messy, addresses are years old, and nothing says whether a site is a dedicated research center or a medical practice that does a little research on the side. That distinction matters in this market, and no data vendor had it. The only way to get it was to read every website.

## What it does

For each domain:

1. **Checks the site is alive** with a cheap probe before spending any AI or scraping credits.
2. **Plans:** Claude looks at the homepage and picks the 3 to 5 pages most likely to hold the answers.
3. **Fetches** those pages, falling back to a headless browser or Firecrawl for sites that block bots.
4. **Extracts** a structured profile, with a source URL and verbatim snippet for every field so a person can verify it at a glance.
5. **Cross-checks** against ClinicalTrials.gov.
6. **Finds every location** for multi-site networks (some have 80+) by walking sitemaps and location pages.
7. **Validates addresses** through geocoding, then dedupes them.
8. **Classifies** the business (10 business types, medical specialties, and how central research is to it).
9. **Exports** results to Google Sheets for review.

## Measuring accuracy

Before scaling up, I hand-built a "golden" set of sites with verified answers ([docs/GOLDEN_WORKFLOW.md](docs/GOLDEN_WORKFLOW.md)) and scored the agent against it field by field ([docs/EVAL_REPORT.md](docs/EVAL_REPORT.md)). On the first scored run: recruitment phone 100%, research page URL 92%, organization name 85%, and HQ phone, HQ address and site type 81% each. Location count was weakest at 65%, so that's where the dedicated location crawler came from.

## Engineering decisions

- **The website is the source of truth.** Input rows are stale, so they are only hints. Every answer must be found on the site itself.
- **Evidence over trust.** Instead of a separate validation stage, each field carries its own source URL and quote, so a reviewer can check any value in seconds.
- **Simple orchestration on purpose.** A planner and an extractor, with a verifier only if accuracy demands it. I deliberately avoided multi-agent frameworks; for factual extraction they add cost and failure points without adding accuracy. The reasoning is in [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md).
- **Cost control.** Dead or parked sites are skipped before any paid call. The bulk classification runs through Anthropic's Batch API at half price, and every run has a hard spending cap.
- **Built with an AI coding agent.** [docs/BUILD_PLAN.md](docs/BUILD_PLAN.md) is the spec I wrote for Claude Code to build the first version overnight: phased, with hard limits on cost and scope and explicit stop points for human review.

## Stack

Python, Anthropic Claude API (structured output with `instructor` + `pydantic`, Batch API), `httpx`, Playwright, Firecrawl, `trafilatura`, ClinicalTrials.gov API, Google Geocoding and Address Validation APIs, US Census geocoder, Google Sheets API, LangSmith tracing.

## Layout

```
src/        the core pipeline: fetch, plan, extract, locations, classify, ClinicalTrials.gov lookup
prompts/    the prompts for each step
scripts/    location crawling, address validation, dedupe, classification and sync tools
evals/      the scoring harness and golden-set template
tests/      unit tests
docs/       build plan, golden-set workflow, eval report
```

## Running it

```bash
pip install -e .
playwright install chromium
cp .env.example .env   # add your API keys
python -m src.main --input data/input.csv --output data/output.csv --limit 100
```

---

Built at Alleviate Health.
