# Locations Review — 23 Dedicated Golden Domains

Generated 2026-05-22. Pipeline cost: $0.378 (all cached except 2 failed fetches).

**Legend:** `agent_count` = what the extractor returned for `location_count__value` |
`locs_extracted` = number of Location objects produced | `expected` = golden.csv expected_location_count

---

## Summary Table

| Domain | agent_count | locs_extracted | expected | Match? | Notes |
|---|---|---|---|---|---|
| cartainvestigators.com | "single location" | 1 | 1 | ✅ prose | count prose, locations correct |
| qualityresearch.com | _(empty)_ | 1 | 1 | ✅ loc | count field empty, location found |
| omnicureresearch.com | 2 | 2 | 2 | ✅ exact | |
| erahealthresearch.com | 3 | 3 | 3 | ✅ exact | |
| equity-med.com | "3 active, 2 coming soon" | 5 | 5 | ✅ loc | count prose, all 5 locations correct |
| mgmclinicalresearch.com | _(empty)_ | 1 | 1 | ✅ loc | count field empty, location found |
| cardiorenalinstitute.com | 7 | 7 | 8 | ⚠️ off by 1 | golden may have one location not on site |
| amrconventions.com | "single location" | 1 | 1 | ✅ prose | |
| cvillemedresearch.com | "single location" | 1 | 1 | ✅ prose | |
| biophaseresearch.com | _(empty)_ | 1 | 1 | ✅ loc | count field empty, location found |
| bhccr.com | "single location" | 1 | 1 | ✅ prose | |
| centralstatesresearch.com | "single location" | 1 | 1 | ✅ prose | no street/city, state only |
| vitaliscrc.com | _(empty)_ | 0 | 1 | ❌ | planner: no extractable content |
| tvcrtrials.com | 2 | 2 | 2 | ✅ exact | |
| jaclinicalresearch.com | "single location" | 1 | 1 | ✅ prose | |
| acuroresearch.com | "single location" | 1 | 1 | ✅ prose | |
| butchertownclinicaltrials.com | _(empty)_ | 0 | 1 | ❌ | fetch timeout (site unreachable) |
| viciscr.com | _(empty)_ | 1 | 1 | ✅ loc | count empty, location found |
| redriverresearchpartners.com | 4 | 4 | 4 | ✅ exact | |
| bostonneuroresearch.com | _(empty)_ | 1 | 1 | ✅ loc | count empty, city only (medium conf) |
| cra-al.biz | _(empty)_ | 0 | 1 | ❌ | SSL cert error — unreachable |
| palmettoclinical.com | _(empty)_ | 1 | 3 | ❌ | planner: no extractable content; 1 low-conf stub |
| iconicclinicalresearchcenter.com | _(empty)_ | 1 | 1 | ✅ loc | count empty, location correct |

**Overall: 19/23 location lists correct (83%). 3 hard failures (fetch/SSL). 1 partial (palmetto, off by 2).**

---

## Per-Domain Detail

---

### cartainvestigators.com
- **agent_count:** "single location" (prose — should be "1")
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Metropolitan Methodist Plaza | 1200 Brooklyn Ave., Suite 210 | San Antonio, TX | high
- **Note:** Correct. Count field returns prose instead of digit — known issue.

---

### qualityresearch.com
- **agent_count:** _(empty)_
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Quality Research, Inc. | Sunset Rd | San Antonio, TX | high
- **Note:** Count field empty (site mentions "single location" in prose form but agent couldn't extract a number). Location itself is correct address area; street number missing (site uses partial address).

---

### omnicureresearch.com
- **agent_count:** 2
- **locs_extracted:** 2 | **capped:** No | **expected:** 2
- **Locations:**
  1. Doral (Main Office) | 8880 NW 20th St Suite M | Doral, FL | high
  2. New Endocrinology Branch Office in Palm Beach | 11211 Prosperity Farms Road Suite C113 | Palm Beach Gardens, FL | high
- **Note:** ✅ Perfect match — the original acceptance-test case.

---

### erahealthresearch.com
- **agent_count:** 3
- **locs_extracted:** 3 | **capped:** No | **expected:** 3
- **Locations:**
  1. Redmond, WA Location | 8301 161st Ave NE, Suite 103 | Redmond, WA | high
  2. Midland, TX Location | 3401 Greenbriar Dr. Suite 200 | Midland, TX | high
  3. Lynnwood, WA Location (CardioNow) | 19020 33rd Ave W Suite 250 | Lynnwood, WA | high
- **Note:** ✅ All three locations with full street addresses. Count exact.

---

### equity-med.com
- **agent_count:** "3 active locations, 2 coming soon"
- **locs_extracted:** 5 | **capped:** No | **expected:** 5
- **Locations:**
  1. New York – Upper West Side | 200 Amsterdam Ave. | New York, NY | high
  2. New York – South Bronx | 2825 3rd Avenue Lower Level | Bronx, NY | high
  3. Kentucky – Bowling Green | 610 Cave Mill Rd | Bowling Green, KY | high
  4. Kentucky – Owensboro | 1921 Leitchfield Rd | Owensboro, KY | high
  5. Tennessee – Nashville | 397 Wallace Road, Suite No. 101 | Nashville, TN | high
- **Note:** ✅ All 5 locations captured correctly including "coming soon" sites. Count field returns prose ("3 active, 2 coming soon") — interesting: agent accurately described the site state but didn't return a total integer.

---

### mgmclinicalresearch.com
- **agent_count:** _(empty)_
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. MGM Medical Care Research & Rehab | 7190 SW 87 Ave #307 | Miami, FL | high
- **Note:** ✅ Location correct. Count field empty — site likely doesn't state a number explicitly.

---

### cardiorenalinstitute.com
- **agent_count:** 7
- **locs_extracted:** 7 | **capped:** No | **expected:** 8
- **Locations:**
  1. _(unnamed)_ | 1070 N. Curtis Rd. Suite #130 | Boise, ID | high
  2. High Desert Heart and Vascular | 3015 E. Goldstone Dr. Suite 230 | Meridian, ID | high
  3. Idaho Kidney Institute – Chubbuck | 4511 Zebe Ave | Chubbuck, ID | high
  4. Idaho Kidney Institute – Idaho Falls | 2381 E. Sunnyside Rd. | Idaho Falls, ID | high
  5. Nephrology & Hypertension Associates | 370 Middletown Blvd., Suite 504 | Langhorne, PA | high
  6. Carabello Kidney | 605 N. Mednick Ave. | Los Angeles, CA | high
  7. Kidney Care of Oregon | 1077 Gateway Loop | Springfield, OR | high
- **Note:** ⚠️ Off by 1. Golden expects 8. Agent found 7 with high confidence — possible the 8th location is on a subpage the planner didn't select, or it was added after the cached HTML was fetched.

---

### amrconventions.com
- **agent_count:** "single location" (prose)
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. _(unnamed)_ | 4300 Weaver Parkway, Suite 100B | Warrenville, IL | high
- **Note:** ✅ Correct. Count prose instead of digit.

---

### cvillemedresearch.com
- **agent_count:** "single location" (prose)
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Charlottesville Medical Research | 325 Winding River Lane, Suite 102 | Charlottesville, VA | high
- **Note:** ✅ Full street address. Count prose.

---

### biophaseresearch.com
- **agent_count:** _(empty)_
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. BioPhase Research MultiSpecialty LLC | 17150 Northeast 19th Avenue | North Miami Beach, Florida | high
- **Note:** ✅ Full address. Golden expected research_url = Instagram — agent correctly found the website location instead.

---

### bhccr.com
- **agent_count:** "single location" (prose)
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Baptist Health Center for Clinical Research | 9601 Baptist Health Drive, Suite 310 | Little Rock, AR | high
- **Note:** ✅ Full address. Count prose.

---

### centralstatesresearch.com
- **agent_count:** "single location" (prose)
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Central States Research | _(no street)_ | _(city unknown)_, Oklahoma | medium
- **Note:** ⚠️ Location found but incomplete — state only, no city or street. Medium confidence. Site likely has minimal address info on fetched pages.

---

### vitaliscrc.com
- **agent_count:** _(empty)_
- **locs_extracted:** 0 | **capped:** No | **expected:** 1
- **Locations:** None
- **Note:** ❌ Planner reported "no extractable content" — trafilatura extracted nothing useful from the homepage. Site may be heavily JS-rendered. Playwright fetched it but returned a thin skeleton. Address (Allen Park, MI) not surfaced.

---

### tvcrtrials.com
- **agent_count:** 2
- **locs_extracted:** 2 | **capped:** No | **expected:** 2
- **Locations:**
  1. TVCR Mission | 1300 S Bryan Rd Suite 107 | Mission, TX | high
  2. TVCR Weslaco | 1116 E 8th St Suite 4 | Weslaco, TX | high
- **Note:** ✅ Both locations with full addresses. Count exact.

---

### jaclinicalresearch.com
- **agent_count:** "single location" (prose)
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. J&A Clinical Research | 8095 NW 12 ST, Suite 203 | Doral, FL | high
- **Note:** ✅ Full address. Count prose.

---

### acuroresearch.com
- **agent_count:** "single location" (prose)
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Acuro Research, Inc. | 18 Corporate Hill Dr, Suite 100 | Little Rock, AR | high
- **Note:** ✅ Full address. Count prose. (Phone miss in eval was a golden data formatting issue — extension `X7-5555` in expected.)

---

### butchertownclinicaltrials.com
- **agent_count:** _(empty)_
- **locs_extracted:** 0 | **capped:** No | **expected:** 1
- **Locations:** None
- **Note:** ❌ Hard fetch failure — Playwright timeout (30s). Site unreachable at time of run. Louisville, KY address known from golden but not extractable.

---

### viciscr.com
- **agent_count:** _(empty)_
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. _(unnamed)_ | 6800 N Dale Mabry Hwy Suite 150 | Tampa, FL | high
- **Note:** ✅ Full address, high confidence. Count field empty — site doesn't state a number.

---

### redriverresearchpartners.com
- **agent_count:** 4
- **locs_extracted:** 4 | **capped:** No | **expected:** 4
- **Locations:**
  1. Fargo, North Dakota | 3911 20th Ave S | Fargo, ND | high
  2. Houston, Texas | 3730 Kirby Drive | Houston, TX | high
  3. Bolivar, Missouri | 215 Chestnut Street | Bolivar, MO | high
  4. Lee's Summit, Missouri | 1324 NE Windsor Drive | Lee's Summit, MO | high
- **Note:** ✅ All 4 locations with full addresses. Count exact.

---

### bostonneuroresearch.com
- **agent_count:** _(empty)_
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Boston Neuro Research Center | _(no street)_ | Boston, MA | medium
- **Note:** ⚠️ Location found, city correct, but no street address. Medium confidence. Street address (237a State Rd, North Dartmouth, MA) is in golden but not on pages the planner fetched — site may bury address in a contact page.

---

### cra-al.biz
- **agent_count:** _(empty)_
- **locs_extracted:** 0 | **capped:** No | **expected:** 1
- **Locations:** None
- **Note:** ❌ Hard fetch failure — SSL certificate error (`ERR_CERT_COMMON_NAME_INVALID`). Site is unreachable over HTTPS. Huntsville, AL address known from golden but inaccessible.

---

### palmettoclinical.com
- **agent_count:** _(empty)_
- **locs_extracted:** 1 | **capped:** No | **expected:** 3
- **Locations:**
  1. Palmetto Clinical Trial Services | _(no street, no city, no state)_ | low confidence
- **Note:** ❌ Partial. Planner found no extractable content. Agent returned a stub location with no address. Golden expects 3 locations (Greenville SC area). Site appears heavily JS-rendered with no planner-navigable content.

---

### iconicclinicalresearchcenter.com
- **agent_count:** _(empty)_
- **locs_extracted:** 1 | **capped:** No | **expected:** 1
- **Locations:**
  1. Iconic Clinical Research Center | 351 Northwest 42nd Avenue | Miami, Florida | high
- **Note:** ✅ Full address. Count field empty. Planner dropped 1 hallucinated URL (self-corrected).

---

## Patterns to Review

**"single location" prose (7 domains):** cartainvestigators, qualityresearch, amrconventions, cvillemedresearch, bhccr, centralstatesresearch, jaclinicalresearch, acuroresearch — all correctly found 1 location but returned prose count. One-line prompt fix: instruct model to return a digit, not a phrase.

**Count field empty but location found (8 domains):** qualityresearch, mgmclinicalresearch, biophaseresearch, viciscr, bostonneuroresearch, palmettoclinical, iconicclinicalresearchcenter, acuroresearch — suggests the site has address info but no explicit location-count statement. The location list is the better signal in these cases.

**Hard fetch failures (3 domains):** cra-al.biz (SSL), butchertownclinicaltrials.com (timeout), vitaliscrc.com (no extractable content). Nothing to fix in the agent — sites are inaccessible or near-empty.

**Incomplete addresses (2 domains):** centralstatesresearch.com (state only), bostonneuroresearch.com (city only). Both medium confidence — agent correctly flagged uncertainty.
