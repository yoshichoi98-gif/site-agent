# CLAUDE.md — Project Conventions

This file is loaded by Claude Code on every session. Keep it current.

## Project

**Site Enrichment Agent** — extracts structured data + evidence from ~7,000 clinical research site websites. See `BUILD_PLAN.md` for the full plan.

## Operating context — READ FIRST

You are working **autonomously overnight** while the user (Yoshi) sleeps. Your job is to build and polish the agent code so he wakes up to a working, smoke-tested pipeline ready for him to build the golden dataset and start measured iteration.

**You are NOT trying to:**
- Run on the full 7K-row input file (it may not even exist on disk yet)
- Iterate on extraction *accuracy* (impossible without ground truth, which only Yoshi can produce)
- Decide architectural questions that need his input (write them to `QUESTIONS_FOR_USER.md` instead)
- Push results to Attio/Airtable
- Make external API calls beyond Anthropic, LangSmith, and ClinicalTrials.gov

**Hard overnight ceiling:**
- Max 50 total domains processed (smoke testing only)
- Max $20 spent
- Max 5 iterations of the smoke test
- HARD STOP at the end of `BUILD_PLAN.md` Phase 5

## About the user

Yoshi is Head of GTM at Alleviate Health. He vibe-codes — can read code, copy-paste-modify, but does not debug complex stack traces. He's awake about 7 hours from now.

Optimize for code he can read and change. Prefer:
- Fewer files
- Flat structure over deep nesting
- Simple control flow (async/await, not callbacks)
- Inline comments explaining *why*, not what
- Helpful error messages
- A `--verbose` flag he can toggle

Avoid:
- Clever metaprogramming
- Abstract base classes for things with one implementation
- Premature optimization
- Configuration sprawl (one `config.py`, not multiple TOML/YAML files)

## Architecture rules

- **Orchestrator-worker pattern** (planner → extractor → optional verifier). NOT multi-agent peer review.
- **One Python script per logical step.** No frameworks (LangGraph, CrewAI, Prefect, Airflow, etc.). If you think you need one, write the question and skip.
- **Async with `httpx`, not `requests`.** Concurrency matters at 7K rows.
- **Pydantic schema is the contract.** Never let raw JSON from the LLM enter the pipeline. Always go through `instructor`.
- **Append-only writes to output CSVs.** Every row writes immediately. No in-memory accumulation.
- **`langsmith.traceable` on every LLM call** IF `LANGSMITH_API_KEY` is set in `.env`. Tag each call with role: `planner`, `extractor`, `verifier`. If the key is not set, fall back to writing each LLM call's input/output/duration/cost to `data/llm_log.jsonl` (one JSON object per line). Pipeline must work either way.
- **Idempotent reruns.** On startup, read existing output CSV, skip processed domains.

## Things to NEVER do

- Never use `json.loads()` on LLM output. Use `instructor`.
- Never `print(...)` for status. Use `logging`.
- Never store API keys in code or commit `.env`. Use `.env.example` for the template.
- Never overwrite an output CSV wholesale. Always append.
- Never use Tavily, Serper, or any other web search API. We have the domain; we go directly to it.
- Never call NPI Registry or Google Places as a primary source. They are unreliable for this dataset.
- Never assume input fields (name, city, state, zip) are correct. Treat as hints. Trust the website.
- Never force a non-null value on the schema. `not_found` is a valid answer.
- Never run on more than 50 domains overnight.
- Never spend more than $20 overnight.
- Never cross the Phase 5 stop marker without the user's go-ahead.
- Never introduce a new agent role (no "Sandor", no "Daenerys", no critic agents, no boss agents). The architecture is planner + extractor + optional verifier. That's it.

## Things to ALWAYS do

- Every extracted field has: `value`, `source_url`, `snippet` (≤30 words verbatim), `confidence`.
- Every LLM call wrapped with `@traceable(name="...", run_type="llm")`.
- Every fetch cached to `data/cache/{domain}.html`. Reruns hit cache first.
- Every change to a prompt = bump a version tag in the prompt file's first line comment (`# v1`, `# v2`, ...). Note the change in `PROGRESS.md`.
- When iterating, change ONE thing at a time. Document each in `PROGRESS.md` with timestamp.
- When uncertain, append to `QUESTIONS_FOR_USER.md` (newest at top) and proceed without that piece.

## When to use Claude Code subagents (Task/Agent tool)

You can spawn subagents via the Task/Agent tool. Each runs in isolated context and returns a single final message. They cost the same per token as you do — speed gain is real, cost reduction is not. Since the user is asleep, wall-clock speed gains are not valuable to him. The only reason to use a subagent overnight is **context isolation**.

**Use subagents for:**

1. **Smoke test execution** — fan out across the 20 smoke-test domains. Each row's processing is independent. This is the legitimate parallelism case. Cap at 10 concurrent.
2. **Isolated research tasks** that would otherwise bloat your context. Examples:
   - "Spike: what's the best Cloudflare-bypass strategy for sites X, Y, Z in the smoke test? Return a brief, no code changes."
   - "Investigate CT.gov API v2 fuzzy-match behavior for org names with abbreviations. Return findings."
3. **Red-team review** after building a module. Example: "Review the extractor prompt in `prompts/extract.txt`. Find 5 failure modes a real clinical research site could trigger. Return a list, do not modify files."
4. **Exploring options** without commitment. Example: "Compare 3 Streamlit layout patterns for the review UI. Recommend one with rationale. Don't write the UI yet."

**Do NOT use subagents for:**

- Parallel building of the main pipeline modules (`schema`, `fetch`, `planner`, `extract`, etc.). These have dependencies and integration risk. Build them sequentially yourself. There is no time pressure.
- Testing prompt variants in parallel (no ground truth to score against until Yoshi builds the golden set tomorrow).
- Anything that writes to shared files like `output.csv`, `PROGRESS.md`, `QUESTIONS_FOR_USER.md`. Only the main agent writes those.
- Cosmetic "let's make this faster" delegation. Speed isn't valuable to a sleeping user.

**Subagent hygiene:**

- Give each subagent only the context it needs (subagent prompts are paid tokens).
- Specify deliverable format clearly ("return X as a Markdown brief, no code changes").
- Restrict tool access where possible (research subagents don't need Edit/Write).
- After a subagent returns, summarize its finding into `PROGRESS.md` so the work is visible.

## How to handle ambiguity

When you hit a decision point not covered above:

1. Pick the simplest reversible option.
2. Note the decision and reasoning in `PROGRESS.md`.
3. If it's NOT reversible (touches data, costs money, changes architecture), STOP and add to `QUESTIONS_FOR_USER.md` instead.

Examples of "do not decide alone overnight":
- Choosing a different LLM model
- Adding a new external API
- Changing the schema
- Skipping the cost cap
- Running on more than 50 domains
- Changing the orchestrator-worker pattern

Examples of "decide and document":
- Picking a User-Agent string
- Choosing the smoke test domain mix
- Tuning concurrency from 10 → 8
- Improving the planner prompt's wording

## Files you maintain

- `PROGRESS.md` — chronological log of what you did, newest at TOP. Every meaningful action gets a timestamped paragraph.
- `QUESTIONS_FOR_USER.md` — anything you couldn't decide alone. Newest at top. Each entry: question, context, why you couldn't decide, your tentative recommendation.
- `OVERNIGHT_SUMMARY.md` — written at the very end, before stopping. Recap of what's built, what was learned from smoke testing, recommended next actions in priority order.
- `SMOKE_TEST_REPORT.md` — written after smoke tests. Fetch success rate, per-field fill rate, hallucinated snippets, latency, cost, top failure patterns.

## Decisions log

Newest at top.

- **2026-05-22:** Subagents authorized for: smoke test parallelism, research/exploration briefs, red-team reviews. NOT authorized for: parallel main-module building, prompt variant testing (no ground truth yet), or writes to shared files.
- **2026-05-22:** Overnight scope = build + smoke test only. Max 50 domains, max $20, hard stop at Phase 5.
- **2026-05-22:** Orchestrator-worker pattern (planner + extractor [+ optional verifier]) chosen. Fruityo-style multi-agent peer review explicitly rejected — wrong fit for factual extraction.
- **2026-05-22:** Model locked to Claude Sonnet 4.6.
- **2026-05-22:** Playwright fallback for blocked sites; chromium only.
- **2026-05-22:** Output is local CSV only. No Attio/Airtable push until manual review of first 100 rows.
- **2026-05-22:** Confidence values: `high | medium | low | not_found`. No multi-source/single-source distinctions.

## Project status

Update at the end of every meaningful work session.

- [ ] Phase 0: Project setup
- [ ] Phase 1: Schema + fetch layer
- [ ] Phase 2: Planner sub-agent
- [ ] Phase 3: Extractor
- [ ] Phase 4: CT.gov cross-reference
- [ ] Phase 5: Pipeline + smoke test + review UI
- [ ] 🛑 STOP HERE OVERNIGHT
- [ ] Phase 6: Golden dataset (Yoshi)
- [ ] Phase 7: Accuracy iteration
- [ ] Phase 8: Verifier (conditional)
- [ ] Phase 9: Scale up
- [ ] Phase 10: Manual review

## When user wakes up

The first thing he'll do is read `OVERNIGHT_SUMMARY.md` and `QUESTIONS_FOR_USER.md`, then probably run the review UI on the smoke test output. Make sure both of those are easy to find and read.
