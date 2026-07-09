# Golden Dataset Workflow

You're hand-verifying 50 sites to create the ground truth that the agent gets measured against.

**Target:** 5-10 minutes per row. Total: ~5-8 hours.

If a row is taking more than 12 minutes, mark it `unclear` and move on. Edge cases are valuable data, not roadblocks.

---

## Before you start

1. Pick 50 domains from your TAM. Stratify roughly:
   - **12 dedicated research sites** (SMOs, CROs, "Clinical Research" in name)
   - **12 embedded sites** (hospitals/clinics with a research arm)
   - **8 academic medical centers** (universities, teaching hospitals)
   - **8 multi-location chains** (health systems with 5+ sites)
   - **10 edge cases** (acquired, rebranded, possibly defunct, international, Cloudflare-protected, ambiguous)

2. Open `golden_template.csv` in Numbers/Excel/Sheets.
3. Paste the 50 domains + their CT.gov-sourced names/cities into the first 5 columns.

## For each row, in order

### Step 1: Open the website (30 sec)
Just `domain` → browser. If it 404s, redirects to a parent company, or shows a Cloudflare/Akamai block page, **mark a note and skip to the next row**. Don't fight it — that's an "edge case" data point.

### Step 2: canonical_org_name (30 sec)
Look at the homepage title, logo alt text, footer copyright (e.g., "© 2026 Sharp HealthCare"). Use what the org calls itself, not the CT.gov name.

### Step 3: hq_phone + hq_address (1-2 min)
Usually in the footer or on a `/contact` page. If they list multiple addresses (e.g., a chain), use the one labeled "headquarters", "corporate office", or "main office". If none labeled, use the first one listed.

**Source URL is mandatory.** Paste the exact URL where you found it.

### Step 4: recruitment_phone (1 min)
Check pages like `/research`, `/clinical-trials`, `/participate`, `/patients`. Many sites use the same number for everything — in that case leave `expected_recruitment_phone` blank (or write "same as hq").

### Step 5: location_count (1 min)
Look for a `/locations` page or "find a doctor" / "find a location" feature. Count distinct physical addresses (not specialties, not departments).

- "Single location" → write `1`
- A range like 5-7 sites visible → write `5-7`
- Hundreds (large systems) → write your best estimate, e.g. `100+`

### Step 6: site_type (2-3 min — THE judgment call)

Use this decision tree:

```
Does the homepage's primary nav focus on patient care services (find a doctor, services, locations, urgent care)?
├── YES → primarily a healthcare provider
│    Does it ALSO have meaningful clinical research presence (more than a single buried page)?
│    ├── YES → "embedded"
│    └── NO → "embedded" (research is incidental)
│
└── NO, the nav focuses on clinical trials / studies / research
     Is the org name or primary tagline about research?
     ├── YES → "dedicated"
     └── NO → "unclear" (might be an org that's transitioning)
```

**`expected_site_type_rationale`** — write 1 sentence explaining your call. This is the most important column in the file. The agent's prompt definitions get written from these rationales later.

If genuinely 50/50, write `unclear`. Don't force a call.

### Step 7: research_url (30 sec)
The single most canonical URL on the site that talks about their research. Usually `/research` or `/clinical-trials` or similar. If they don't have one → leave blank.

### Step 8: trials_status (skip for now)
We'll fill this from ClinicalTrials.gov API later automatically. Leave blank.

### Step 9: verified_at, verifier_initials
Today's date and your initials. So you remember when this was done.

---

## Edge cases — how to record them

**Cloudflare blocked or won't load:** Set `expected_canonical_org_name` to whatever shows in the title bar of the block page if available, mark all other fields with `BLOCKED` in the notes column. This is valuable — it tells the agent's Playwright fallback what to expect.

**Site is gone (404 / domain for sale):** Mark `notes = DEFUNCT`. Leave most fields blank. The agent should handle this case.

**Acquired / rebranded:** Use the CURRENT canonical name. Note the old name in `notes`. E.g., `Acquired by Mayo Clinic in 2024 — was Mid-State Health`.

**Site is in a foreign language or international:** If you can't read it, mark `notes = INTL` and skip. The agent will handle later.

**Ambiguous site_type:** Mark `unclear` and write a thorough rationale. These are the rows that teach the prompt the most.

---

## What NOT to do

- **Don't rely on the CT.gov-sourced name or address.** It's stale. The website is truth.
- **Don't research beyond the website.** No NPI lookups, no LinkedIn, no Crunchbase. The agent only sees the website, so your ground truth should be sourced the same way.
- **Don't perfect every cell.** "Looks like 12 locations from their dropdown" is fine; you don't have to count them precisely.
- **Don't pre-judge based on the CT.gov name.** "M3 Wake Research" sounds dedicated, but verify on the site.
- **Don't skip the rationale for site_type.** That column is the prompt's calibration data.

---

## When you're done

Save as `data/golden.csv` in `~/site-agent/`. Tell me; we'll wire it into the eval script.
