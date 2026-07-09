"""
Per-row orchestration: fetch → planner → fetch planned pages → extract → location_extract.
All HTTP fetches go through src/fetch.py (httpx + playwright fallback). No bare httpx here.
Returns a flat dict for orgs CSV and a list of Location dicts for locations CSV.
"""
import asyncio
import logging
import time

import httpx

from src.extract import extract
from src.fetch import fetch, fetch_url
from src.location_extract import extract_locations
from src.planner import plan_crawl
from src.schema import Evidence, Location, SiteProfile

logger = logging.getLogger(__name__)

# Sonnet 4.6 pricing
_INPUT_COST_PER_TOKEN = 3.0 / 1_000_000   # $3/MTok
_OUTPUT_COST_PER_TOKEN = 15.0 / 1_000_000  # $15/MTok

_run_cost_usd: float = 0.0


def add_cost(input_tokens: int, output_tokens: int) -> float:
    # asyncio is single-threaded (cooperative multitasking) — no lock needed.
    # +=  is never interrupted by another coroutine because there's no await here.
    global _run_cost_usd
    cost = input_tokens * _INPUT_COST_PER_TOKEN + output_tokens * _OUTPUT_COST_PER_TOKEN
    _run_cost_usd += cost
    return _run_cost_usd


def get_run_cost() -> float:
    return _run_cost_usd


def reset_run_cost():
    global _run_cost_usd
    _run_cost_usd = 0.0


_NON_EVIDENCE_FIELDS = {"locations", "locations_capped", "locations_capped_reason"}

# Subcategories that trigger location enumeration (Step 5).
# Defined here so main.py can import it for progress display without duplicating.
RESEARCH_TARGET_SUBCATEGORIES = {
    "dedicated_research_site",
    "dedicated_research_site_network",
    "site_management_organization",
    "specialty_practice_with_research",
    "oncology_practice_with_research",
}


def _profile_to_org_row(domain: str, profile: SiteProfile,
                         latency_s: float, fetch_status: str, error: str = "",
                         content_quality: str = "ok") -> dict:
    """Flatten SiteProfile Evidence fields to a CSV row (locations go to locations CSV)."""
    row = {
        "domain": domain,
        "finished_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "latency_s": round(latency_s, 1),
        "fetch_status": fetch_status,
        "content_quality": content_quality,
        "error": error,
        "locations_capped": profile.locations_capped,
        "locations_capped_reason": profile.locations_capped_reason or "",
    }
    for field_name in SiteProfile.model_fields:
        if field_name in _NON_EVIDENCE_FIELDS:
            continue
        ev = getattr(profile, field_name)
        row[f"{field_name}__value"] = ev.value or ""
        row[f"{field_name}__confidence"] = ev.confidence
        row[f"{field_name}__source_url"] = ev.source_url or ""
        row[f"{field_name}__snippet"] = ev.snippet or ""
    return row


def locations_to_rows(domain: str, locations: list[Location]) -> list[dict]:
    """Convert Location objects to flat dicts for the locations CSV."""
    rows = []
    for loc in locations:
        rows.append({
            "domain": domain,
            "location_name": loc.location_name or "",
            "address_street": loc.address_street or "",
            "address_city": loc.address_city or "",
            "address_state": loc.address_state or "",
            "address_zip": loc.address_zip or "",
            "phone": loc.phone or "",
            "source_url": loc.source_url,
            "snippet": loc.snippet,
            "confidence": loc.confidence,
            "validation_status": loc.validation_status,
        })
    return rows


async def process_row(domain: str, max_cost_usd: float = 20.0) -> tuple[dict, list[dict]]:
    """
    Full pipeline for one domain.
    Returns (org_row dict, list of location row dicts).
    Never raises — all errors captured in returned dicts.

    Hard outer timeout: 300s. A single wedged domain (DNS hang, infinite redirect,
    Playwright networkidle that never fires) previously held a concurrency slot
    indefinitely. 300s gives extra headroom for slow-but-real sites.
    """
    t0 = time.time()
    logger.info(f"[{domain}] pipeline: starting")

    def _empty(fetch_status: str, error: str = "") -> tuple[dict, list]:
        return (_profile_to_org_row(domain, SiteProfile(), time.time() - t0, fetch_status, error), [])

    if get_run_cost() >= max_cost_usd:
        logger.error(f"[{domain}] cost cap reached (${get_run_cost():.2f}), skipping")
        return _empty("skipped", "cost_cap_reached")

    async def _run() -> tuple[dict, list[dict]]:
        """Inner coroutine — wrapped by wait_for so the timeout can cancel it cleanly."""
        try:
            # Per-step timing — reported at WARNING level when total > 1000s so
            # we can identify which step is the bottleneck without bloating the log.
            step_fetch_homepage = 0.0
            step_planner = 0.0
            step_fetch_subpages = 0.0
            step_extract = 0.0
            step_locations = 0.0

            # Step 1: fetch homepage
            _s = time.time()
            homepage = await fetch(domain)
            step_fetch_homepage = time.time() - _s

            if homepage.parked:
                logger.info(f"[{domain}] parked domain — skipping pipeline")
                return _empty("parked", "parked_domain")
            if homepage.blocked or not homepage.html:
                logger.warning(f"[{domain}] homepage blocked/empty")
                return _empty("blocked", homepage.error or "blocked")

            # Step 2: plan crawl
            # run_in_executor: plan_crawl makes a synchronous Anthropic API call + trafilatura.
            # Running in a thread frees the event loop so other domains' I/O (timeouts,
            # httpx callbacks) can proceed concurrently — otherwise the GIL and blocking
            # socket calls would freeze the entire async runtime for 10-30s per LLM call.
            plan = None
            _s = time.time()
            try:
                loop = asyncio.get_event_loop()
                plan, plan_usage = await loop.run_in_executor(
                    None, lambda: plan_crawl(homepage.html, domain)
                )
                add_cost(plan_usage.input_tokens, plan_usage.output_tokens)
            except Exception as e:
                logger.warning(f"[{domain}] planner failed: {e}")
            step_planner = time.time() - _s

            # Step 3: fetch planned pages — all through fetch_url() with playwright fallback
            additional: dict[str, str] = {}
            _s = time.time()
            if plan and plan.pages:
                results = await asyncio.gather(
                    *[fetch_url(p.url) for p in plan.pages],
                    return_exceptions=True,
                )
                for p, result in zip(plan.pages, results):
                    if isinstance(result, Exception):
                        logger.warning(f"[{domain}] fetch_url error {p.url}: {result}")
                    elif result.blocked or not result.html:
                        logger.info(f"[{domain}] subpage blocked: {p.url}")
                    else:
                        additional[p.url] = result.html
            step_fetch_subpages = time.time() - _s

            logger.info(f"[{domain}] fetched {len(additional)}/{len(plan.pages) if plan else 0} planned pages")

            # Step 4: main extraction (SiteProfile Evidence fields)
            _s = time.time()
            try:
                loop = asyncio.get_event_loop()
                profile, extract_usage = await loop.run_in_executor(
                    None, lambda: extract(domain, homepage.html, additional)
                )
                add_cost(extract_usage.input_tokens, extract_usage.output_tokens)
            except Exception as e:
                logger.error(f"[{domain}] extractor failed: {e}")
                profile = SiteProfile()
            step_extract = time.time() - _s

            # Step 4b: validate research_url with a HEAD request — blank if 404/410/451/5xx
            if profile.research_url.value:
                try:
                    async with httpx.AsyncClient(timeout=5.0, follow_redirects=True) as client:
                        resp = await client.head(profile.research_url.value)
                    if resp.status_code in {404, 410, 451} or resp.status_code >= 500:
                        logger.info(f"[{domain}] research_url blanked ({resp.status_code}): {profile.research_url.value}")
                        profile.research_url = Evidence()
                    else:
                        logger.info(f"[{domain}] research_url validated ({resp.status_code}): {profile.research_url.value}")
                except Exception as e:
                    logger.info(f"[{domain}] research_url validation failed (leaving): {e}")

            # Clear any locations the main extractor speculatively filled in — Step 5 owns this field.
            profile.locations = []
            profile.locations_capped = False
            profile.locations_capped_reason = None

            # Step 5: location extraction (conditional)
            # Only enumerate locations for primary research-target SMOs.
            # Exact-match prevents "contract_research_organization" from matching "research".
            subcategory = (profile.org_subcategory.value or "").lower()
            _should_enumerate = subcategory in RESEARCH_TARGET_SUBCATEGORIES
            _s = time.time()
            if _should_enumerate and get_run_cost() < max_cost_usd:
                try:
                    loop = asyncio.get_event_loop()
                    loc_result, loc_usage = await loop.run_in_executor(
                        None, lambda: extract_locations(domain, homepage.html, additional)
                    )
                    profile.locations = loc_result.locations
                    profile.locations_capped = loc_result.capped
                    profile.locations_capped_reason = loc_result.capped_reason
                    add_cost(loc_usage.input_tokens, loc_usage.output_tokens)
                    if loc_result.capped:
                        logger.info(f"[{domain}] locations capped: {loc_result.capped_reason}")
                except Exception as e:
                    logger.error(f"[{domain}] location extractor failed: {e}")
            else:
                logger.info(f"[{domain}] skipping location pass (subcategory={subcategory!r})")
            step_locations = time.time() - _s

            latency = time.time() - t0
            logger.info(
                f"[{domain}] done in {latency:.1f}s | "
                f"{len(profile.locations)} location(s) | "
                f"est. cost ${get_run_cost():.4f}"
            )

            # Slow-domain breakdown — only logged when total latency is suspiciously high
            # so we can tell which step is the bottleneck without flooding the log.
            if latency > 1000:
                logger.warning(
                    f"[{domain}] SLOW ({latency:.0f}s total): "
                    f"fetch_homepage={step_fetch_homepage:.1f}s, "
                    f"planner={step_planner:.1f}s, "
                    f"fetch_subpages={step_fetch_subpages:.1f}s, "
                    f"extract={step_extract:.1f}s, "
                    f"locations={step_locations:.1f}s"
                )

            org_row = _profile_to_org_row(domain, profile, latency, homepage.fetched_with,
                                          content_quality=homepage.content_quality)
            loc_rows = locations_to_rows(domain, profile.locations)
            return org_row, loc_rows

        except Exception as e:
            latency = time.time() - t0
            logger.error(f"[{domain}] pipeline unexpected error: {e}")
            return _empty("error", str(e))

    # Hard outer timeout — prevents a single wedged domain from holding a concurrency
    # slot forever (e.g. Playwright networkidle that never fires, infinite DNS hang).
    try:
        return await asyncio.wait_for(_run(), timeout=300)
    except asyncio.TimeoutError:
        latency = time.time() - t0
        logger.warning(f"[{domain}] TIMEOUT at 300s, aborting")
        return _empty("timeout", "domain_timeout_300s")
