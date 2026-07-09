"""
scripts/firecrawl_test.py

Test Firecrawl's /extract endpoint on the flagged problem domains:
  - austinheart.com (doctor-as-location dupes)
  - ascendvision.com (partner page contamination)
  - docsdermgroup.com (Google Maps only, Show More)
  - allieddigestivehealth.com (HQ address stamped on all rows)
  - frontierdermatology.com (city/state only, no street)
  - calderminstitute.com (Show More button)
  - coloradouro.com (Show More button)
  - aaraclinicalresearch.com (37 zips on page, only got 10)

For each domain, Firecrawl will crawl + extract via wildcard pattern. We use
its agent (FIRE-1) on hard sites that need interaction.

Output: data/firecrawl_test_results.csv
"""
import csv
import logging
import os
import sys
import time
from typing import Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from firecrawl import FirecrawlApp

load_dotenv('/Users/yoshichoi/site-agent/.env')

logger = logging.getLogger(__name__)

API_KEY  = os.environ['FIRECRAWL_API_KEY']
OUT_PATH = 'data/firecrawl_test_results.csv'

TEST_DOMAINS = [
    "austinheart.com",
    "ascendvision.com",
    "docsdermgroup.com",
    "allieddigestivehealth.com",
    "frontierdermatology.com",
    "calderminstitute.com",
    "coloradouro.com",
    "aaraclinicalresearch.com",
]

# ── Pydantic schema for Firecrawl ─────────────────────────────────────────────

class Location(BaseModel):
    location_name:  Optional[str] = Field(None, description="e.g. 'HQ' or 'Palm Beach Gardens Branch' or null if not labeled")
    address_street: Optional[str] = Field(None, description="Street address with suite/unit if present")
    address_city:   Optional[str] = Field(None, description="City name")
    address_state:  Optional[str] = Field(None, description="2-letter US state abbreviation")
    address_zip:    Optional[str] = Field(None, description="5-digit ZIP code")
    phone:          Optional[str] = Field(None, description="Phone for this specific location")
    source_url:     Optional[str] = Field(None, description="URL where this location was found")


class Locations(BaseModel):
    locations: list[Location] = Field(default_factory=list)


PROMPT = """\
Extract every individual physical office or clinic location from this organization's website.

CRITICAL RULES:
1. ONE row per UNIQUE physical street address. Do NOT create separate rows for different
   doctors or services at the same address.
2. EXCLUDE partner practices, affiliated organizations, or referral networks. Only include
   locations directly owned/operated by this organization. Skip /our-partners/, /affiliates/, etc.
3. Doctor names are NOT locations. A location is a distinct physical street address.
4. If a page lists 5 doctors at one office, return ONE row for that office, not 5.
5. For sites that hide locations behind "Show More" or pagination, expand them all.
6. For sites where addresses appear in a Google Map (markers/info windows), extract them.
"""


def extract_domain(app: FirecrawlApp, domain: str) -> tuple[list[dict], dict]:
    """Run Firecrawl /extract on a single domain, return (locations, meta)."""
    t0 = time.time()
    url_pattern = f"https://{domain}/*"
    logger.info(f"[{domain}] extracting via {url_pattern}")

    try:
        # Firecrawl v2 SDK — extract endpoint
        result = app.extract(
            urls=[url_pattern],
            schema=Locations.model_json_schema(),
            prompt=PROMPT,
        )
    except Exception as e:
        logger.error(f"[{domain}] extract failed: {e}")
        return [], {"error": str(e), "duration_s": time.time() - t0}

    duration = time.time() - t0

    # Result shape varies — handle dict vs object
    if hasattr(result, 'data'):
        data = result.data
    elif isinstance(result, dict):
        data = result.get('data', result)
    else:
        data = result

    if isinstance(data, dict) and 'locations' in data:
        locations = data['locations']
    elif isinstance(data, list):
        locations = data
    else:
        locations = []

    logger.info(f"[{domain}] got {len(locations)} locations in {duration:.1f}s")
    return locations, {"duration_s": duration, "url_pattern": url_pattern}


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    app = FirecrawlApp(api_key=API_KEY)

    fieldnames = [
        "domain", "location_name", "address_street", "address_city",
        "address_state", "address_zip", "phone", "source_url",
    ]

    all_rows = []
    summary = {}

    for domain in TEST_DOMAINS:
        locations, meta = extract_domain(app, domain)
        summary[domain] = {
            "count": len(locations),
            "duration_s": meta.get("duration_s", 0),
            "error": meta.get("error"),
        }
        for loc in locations:
            if not isinstance(loc, dict):
                loc = loc.model_dump() if hasattr(loc, "model_dump") else dict(loc)
            row = {"domain": domain}
            for k in fieldnames[1:]:
                row[k] = loc.get(k, "") or ""
            all_rows.append(row)

    with open(OUT_PATH, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore", quoting=csv.QUOTE_MINIMAL)
        writer.writeheader()
        writer.writerows(all_rows)
    logger.info(f"Wrote {len(all_rows)} rows to {OUT_PATH}")

    # Print summary
    print()
    print(f"{'domain':<35} {'count':>8} {'duration':>10} {'error'}")
    print("-" * 80)
    for d, s in summary.items():
        err = (s.get("error") or "")[:40]
        print(f"{d:<35} {s['count']:>8} {s['duration_s']:>9.1f}s {err}")


if __name__ == "__main__":
    main()
