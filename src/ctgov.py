"""
ClinicalTrials.gov v2 API cross-reference.
Uses the canonical_org_name from the extractor, not the input row name.
"""
import logging
import urllib.parse

import httpx

from src.schema import Evidence

logger = logging.getLogger(__name__)

# Human-readable search URL (for the evidence source_url field)
_CTGOV_SEARCH_BASE = "https://clinicaltrials.gov/search?term={name}&status=RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING"
# API v2 endpoint
_CTGOV_API = "https://clinicaltrials.gov/api/v2/studies"


async def get_trials_status(canonical_org_name: str) -> Evidence:
    """
    Query CT.gov for active/historical trials by org name.

    Returns Evidence with:
      value = "active" | "inactive" | "unknown"
      confidence = "high" | "medium" | "low"
      source_url = human-readable CT.gov search URL
      snippet = brief description of what was found
    """
    if not canonical_org_name:
        return Evidence(confidence="not_found")

    encoded_name = urllib.parse.quote(canonical_org_name)
    search_url = _CTGOV_SEARCH_BASE.format(name=encoded_name)

    active_statuses = "RECRUITING,NOT_YET_RECRUITING,ACTIVE_NOT_RECRUITING"
    params = {
        "query.term": canonical_org_name,
        "filter.overallStatus": active_statuses,
        "pageSize": 10,
        "fields": "NCTId,OfficialTitle,OverallStatus",
    }

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r = await client.get(_CTGOV_API, params=params)
            r.raise_for_status()
            data = r.json()
    except Exception as e:
        logger.warning(f"CT.gov API error for '{canonical_org_name}': {e}")
        return Evidence(confidence="not_found", error=str(e) if hasattr(Evidence, 'error') else None)

    # API v2 returns a list of studies + optional nextPageToken (no totalCount field)
    active_studies = data.get("studies", [])
    has_more = bool(data.get("nextPageToken"))
    active_count = len(active_studies)

    if active_count >= 1:
        display_count = f"{active_count}+" if has_more else str(active_count)
        snippet = f"{display_count} active/recruiting trial(s) found for {canonical_org_name}"
        return Evidence(
            value="active",
            source_url=search_url,
            snippet=snippet[:300],
            confidence="high",
        )

    # No active trials — check for any historical trials (all statuses)
    try:
        all_params = {
            "query.term": canonical_org_name,
            "pageSize": 1,
            "fields": "NCTId",
        }
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            r2 = await client.get(_CTGOV_API, params=all_params)
            r2.raise_for_status()
            all_data = r2.json()
        all_count = len(all_data.get("studies", []))
    except Exception as e:
        logger.warning(f"CT.gov history lookup error for '{canonical_org_name}': {e}")
        all_count = 0

    if all_count >= 1:
        snippet = f"No active trials; {all_count} historical trial(s) found for {canonical_org_name}"
        return Evidence(
            value="inactive",
            source_url=search_url,
            snippet=snippet[:300],
            confidence="medium",
        )

    snippet = f"No trials found on ClinicalTrials.gov for {canonical_org_name}"
    return Evidence(
        value="unknown",
        source_url=search_url,
        snippet=snippet[:300],
        confidence="low",
    )
