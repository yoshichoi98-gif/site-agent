# Claude Code Kickoff (Interactive Mode)

## Pre-launch checklist

```bash
cd ~/site-agent
echo "Shell key: '$ANTHROPIC_API_KEY'"
# Must print blank. If not, run: unset ANTHROPIC_API_KEY
```

## Launch (interactive, NOT skip-permissions)

```bash
claude
```

## Inside Claude Code, FIRST run /status

You need to see one of these:
- "Team Premium" / "claude.ai" / "OAuth login" → ✅ proceed
- "API Usage Billing" → ❌ stop and run `/logout` then `/login`, pick claude.ai

## Then paste this kickoff prompt

```
Read BUILD_PLAN.md and CLAUDE.md completely before doing anything else. Then start Phase 0.

Important context:
- I am watching interactively. You will need my approval for bash commands and file edits.
- I am ALSO working on the golden dataset (data/golden.csv) in parallel. Do not depend on it existing; it will be available later in our session.
- We are starting Phase 0 today. We may not get all the way to Phase 5 in this session.

Hard limits (still apply):
- Maximum 50 domains processed in total smoke testing
- Maximum $20 total API spend in smoke testing
- Maximum 5 smoke-test iterations
- Do NOT cross the Phase 5 stop marker without my explicit approval
- Do NOT run on the 7K input file (it doesn't exist yet)

Before any work, confirm to me:
1. You have read both BUILD_PLAN.md and CLAUDE.md
2. The four hard limits above
3. Which phase you're starting on
4. Your plan for the next 30 minutes

Do not proceed past confirmation until I approve.
```

## What to watch for in its response

✅ **Good signs:**
- Reads both docs via `view` or `read` tool calls
- Echoes back the limits explicitly (50 domains, $20, 5 iterations, Phase 5 stop)
- Lays out the next 30 min plan
- Asks for your approval before starting

❌ **Red flags — stop and re-prompt:**
- Says "got it, starting" without echoing limits
- Skips reading the docs
- Starts running bash commands before you approve the plan
- Asks YOU to make decisions that should be in CLAUDE.md's "decide and document" category

## Working alongside Claude Code

While Claude Code builds in one terminal tab, work on the golden dataset in your browser + CSV editor:

1. Pick 50 domains from your TAM
2. Open `golden_template.csv` in Numbers / Sheets / Excel
3. Paste those 50 domains into the first column
4. Follow `GOLDEN_WORKFLOW.md` step by step

Roughly 5-10 min per row. Total ~5-8 hours, can be split across multiple sessions.

## When to break from Claude Code and come back to chat

Ping me here if:
- Claude Code asks a question that's not in BUILD_PLAN or CLAUDE.md
- You hit an edge case in the golden dataset and want a second opinion
- Phase 0-3 wraps up and you want to discuss what to do next
- Anything looks weird

Don't ping me for routine progress. Trust the build.
