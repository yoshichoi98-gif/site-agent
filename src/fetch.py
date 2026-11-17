"""
Fetch layer: 4-tier bot evasion with cache.
Every fetch is cached to data/cache/ — reruns hit cache first.

Tier 1: httpx            — fast, works for ~80% of sites
Tier 2: curl_cffi        — Chrome TLS fingerprint impersonation
Tier 3: Playwright       — headless Chromium, load-event wait
Tier 4: Playwright+stealth — stealth patches on top of Tier 3

Two public functions:
  fetch(domain)   — homepage only, cache key = domain
  fetch_url(url)  — arbitrary subpage, cache key = sanitized URL + hash
"""
import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass, field
from typing import Optional

import httpx

from src.config import CACHE_DIR, HTTPX_CONCURRENCY, HTTPX_TIMEOUT, PLAYWRIGHT_CONCURRENCY, PLAYWRIGHT_TIMEOUT

logger = logging.getLogger(__name__)

_USER_AGENTS = [
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.3 Safari/605.1.15",
]

# Phrases that definitively mean a bot-challenge page — safe to check at any body size
# because they don't appear in real site content.
_CHALLENGE_PATTERNS = [
    "just a moment",
    "checking your browser",
    "please enable cookies",
    "enable javascript and cookies",
    "ddos-guard",
    "perimeterx",
    "incapsula",
    "request unsuccessful",
]

# CDN/proxy names that appear on challenge pages BUT also appear in legitimate script src
# URLs (e.g. cdnjs.cloudflare.com, akamai CDN image hosts). Only checked on small bodies
# where a real site wouldn't produce them anyway.
_CDN_PATTERNS = [
    "cloudflare",
    "akamai",
    "ray id",
    "enable javascript",
    "access denied",
]

# Parking registrar keywords — only trusted when body < 5000 bytes.
_PARKING_BODY_SIGNALS = [
    "godaddy",
    "this domain is for sale",
    "buy this domain",
    "domain parking",
    "parked domain",
    "namecheap",
    "porkbun",
    "sedo",
    "afternic",
    "hugedomains",
    "domain.com is for sale",
    "register.com",
]

# If the final URL (after redirects) contains any of these, it's a parking page regardless of size.
_PARKING_URL_SIGNALS = [
    "godaddy.com/forsale",
    "sedoparking.com",
    "parkingcrew",
    "dan.com",
    "afternic.com",
]

# DNS failures — all tiers resolve DNS the same way, so short-circuit immediately.
_FATAL_ERROR_SIGNALS = [
    "nodename nor servname provided",
    "name or service not known",
    "could not resolve host",
    "errno 8",
    "errno 11001",
    "temporary failure in name resolution",
]

# SSL errors where the site doesn't support HTTPS at all — HTTP fallback will work.
_SSL_ERROR_SIGNALS = [
    "sslv3_alert_handshake_failure",
    "handshake failure",
    "ssl handshake",
    "tlsv1 alert",
    "certificate verify failed",
    "ssl:",
    "tls connect error",
]


def _is_parked(html: str, final_url: str = "", status: int = 0) -> bool:
    if status == 0:
        return False
    final_lower = final_url.lower()
    if any(sig in final_lower for sig in _PARKING_URL_SIGNALS):
        return True
    if status == 200 and len(html) < 500:
        return True
    if len(html) < 5000:
        lower = html.lower()
        if any(sig in lower for sig in _PARKING_BODY_SIGNALS):
            return True
    return False


def _is_blocked(status_code: int, html: str) -> bool:
    """
    True when the response looks like a bot-challenge or empty page.

    Split into two tiers of patterns to avoid false positives on large pages:
    - Status codes: 403/429/503 are always blocked regardless of body.
    - Empty body (< 500 bytes): always blocked.
    - _CHALLENGE_PATTERNS: definitive challenge phrases, checked at any size.
    - _CDN_PATTERNS: CDN names that appear on challenge pages but also in real
      site script URLs. Only checked when body < 5000 bytes, where a legitimate
      site wouldn't produce them.
    """
    if status_code in (403, 429, 503):
        return True
    if len(html) < 500:
        return True
    lower = html.lower()
    # Definitive challenge phrases — safe at any body size
    if any(p in lower for p in _CHALLENGE_PATTERNS):
        return True
    # CDN names — only on small bodies where they unambiguously indicate a challenge page
    if len(html) < 5000 and any(p in lower for p in _CDN_PATTERNS):
        return True
    return False


def _is_real_content(status: int, html: str) -> bool:
    """True when status=200 and body > 5000 bytes — trust without full block-pattern check."""
    return status == 200 and len(html) > 5000


def _content_quality(html: str) -> str:
    """
    Returns a quality label for successfully-fetched HTML.
    'ok'          — has usable visible text
    'spa_shell'   — large HTML but < 300 chars of visible text (React/Vue/Next app shell)
    'login_wall'  — page is gated behind a login prompt
    'coming_soon' — placeholder / maintenance page
    'challenge'   — Cloudflare/bot challenge that slipped through the size check
    """
    if not html:
        return "ok"

    lower = html.lower()

    # Challenge page that passed the size threshold (e.g. Cloudflare JS challenge is ~8KB)
    if any(p in lower for p in _CHALLENGE_PATTERNS):
        return "challenge"
    if len(html) < 5000 and any(p in lower for p in _CDN_PATTERNS):
        return "challenge"

    # Login wall
    _login = ["sign in to continue", "please log in", "login required", "you must be logged in"]
    if any(s in lower for s in _login):
        return "login_wall"

    # Coming soon / maintenance — only flag when body is small (real sites mention these in blogs)
    _soon = ["coming soon", "under construction", "launching soon", "site is under maintenance"]
    if len(html) < 10_000 and any(s in lower for s in _soon):
        return "coming_soon"

    # SPA shell: strip script/style blocks first (their content isn't visible text),
    # then strip remaining tags. A 10KB+ page with < 300 chars of visible text has
    # no server-rendered content worth extracting.
    if len(html) >= 10_000:
        stripped = re.sub(r"<(script|style)[^>]*>.*?</(script|style)>", " ", html,
                          flags=re.DOTALL | re.IGNORECASE)
        visible = re.sub(r"<[^>]+>", " ", stripped)
        visible = " ".join(visible.split())
        if len(visible) < 300:
            return "spa_shell"

    return "ok"


def _is_fatal_network_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(sig in msg for sig in _FATAL_ERROR_SIGNALS)


def _is_ssl_error(e: Exception) -> bool:
    msg = str(e).lower()
    return any(sig in msg for sig in _SSL_ERROR_SIGNALS)


def _ua(index: int = 0) -> str:
    return _USER_AGENTS[index % len(_USER_AGENTS)]


@dataclass
class FetchResult:
    domain: str
    url: str
    html: str
    status_code: int
    fetched_with: str       # "cache"|"httpx"|"curl_cffi"|"playwright"|"playwright_stealth"
    blocked: bool = False
    parked: bool = False
    error: Optional[str] = None
    content_quality: str = "ok"   # "ok"|"spa_shell"|"login_wall"|"coming_soon"|"challenge"


_httpx_semaphore: Optional[asyncio.Semaphore] = None
_playwright_semaphore: Optional[asyncio.Semaphore] = None

# Persistent browser — launched once, reused across all Playwright requests.
# Each request gets its own context (~50ms) rather than a new Chromium process (5–15s).
_pw_instance = None
_pw_browser = None
_pw_init_lock: Optional[asyncio.Lock] = None


def _get_semaphores():
    global _httpx_semaphore, _playwright_semaphore
    if _httpx_semaphore is None:
        _httpx_semaphore = asyncio.Semaphore(HTTPX_CONCURRENCY)
    if _playwright_semaphore is None:
        _playwright_semaphore = asyncio.Semaphore(PLAYWRIGHT_CONCURRENCY)
    return _httpx_semaphore, _playwright_semaphore


async def _get_browser():
    """Return the shared Chromium browser, launching it on first call."""
    global _pw_instance, _pw_browser, _pw_init_lock
    if _pw_init_lock is None:
        _pw_init_lock = asyncio.Lock()
    async with _pw_init_lock:
        if _pw_browser is None or not _pw_browser.is_connected():
            from playwright.async_api import async_playwright
            _pw_instance = await async_playwright().start()
            _pw_browser = await _pw_instance.chromium.launch(headless=True)
            logger.info("Playwright browser launched (shared instance)")
    return _pw_browser


def _cache_key_for_domain(domain: str) -> str:
    safe = re.sub(r"[^\w.-]", "_", domain)
    return os.path.join(CACHE_DIR, f"{safe}.html")


def _cache_key_for_url(url: str) -> str:
    safe = re.sub(r"[^\w.-]", "_", url)[:80]
    suffix = hashlib.md5(url.encode()).hexdigest()[:8]
    return os.path.join(CACHE_DIR, f"{safe}__{suffix}.html")


def _write_cache(cache_file: str, html: str):
    with open(cache_file, "w", encoding="utf-8") as f:
        f.write(html)


def _parked_result(label: str, url: str, html: str, status: int, tier: str) -> FetchResult:
    logger.info(f"[{label}] parked (tier={tier}, bytes={len(html)})")
    return FetchResult(domain=label, url=url, html=html, status_code=status,
                       fetched_with="parked", parked=True)


async def _httpx_fetch(url: str, ua_index: int = 0) -> tuple[int, str, str]:
    headers = {
        "User-Agent": _ua(ua_index),
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Accept-Language": "en-US,en;q=0.5",
    }
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(connect=5, read=HTTPX_TIMEOUT, write=5, pool=5),
        follow_redirects=True,
    ) as client:
        r = await client.get(url, headers=headers)
        return r.status_code, r.text, str(r.url)


async def _curl_cffi_fetch(url: str) -> tuple[int, str, str]:
    from curl_cffi.requests import AsyncSession
    async with AsyncSession(impersonate="chrome120") as session:
        # (connect_timeout, read_timeout) — matches httpx split to keep dead-domain time ~20s.
        # Scalar timeout=15 only sets the read timeout; connect can still hang for 60s+.
        r = await session.get(url, timeout=(5, HTTPX_TIMEOUT), allow_redirects=True)
        return r.status_code, r.text, str(r.url)


async def _playwright_fetch(url: str, stealth: bool = False) -> tuple[int, str, str]:
    """Shared browser instance — context per request, browser reused."""
    browser = await _get_browser()
    ctx = await browser.new_context(
        user_agent=_ua(2),
        viewport={"width": 1280, "height": 800},
        extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
        ignore_https_errors=True,
    )
    page = await ctx.new_page()
    if stealth:
        from playwright_stealth import stealth_async
        await stealth_async(page)
    final_url = url
    try:
        resp = await page.goto(url, timeout=PLAYWRIGHT_TIMEOUT * 1000, wait_until="load")
        status = resp.status if resp else 0
        html = await page.content()
        final_url = page.url
    except Exception as e:
        logger.warning(f"playwright{'_stealth' if stealth else ''} error on {url}: {e}")
        html = ""
        status = 0
    finally:
        await ctx.close()
    return status, html, final_url


async def _fetch_with_fallback(url: str, cache_file: str, label: str) -> FetchResult:
    """
    4-tier fetch with several short-circuits to avoid wasting time:
    - DNS failure after tier 1 → return immediately (all tiers share DNS)
    - SSL error on https → retry http before escalating
    - Both httpx AND curl_cffi return status=0 → skip Playwright (dead TCP, browser can't help)
    - After Playwright, run _is_blocked() so challenge pages aren't cached as real content
    """
    os.makedirs(CACHE_DIR, exist_ok=True)

    if os.path.exists(cache_file):
        with open(cache_file, "r", encoding="utf-8", errors="replace") as f:
            html = f.read()
        logger.info(f"[{label}] cache hit ({len(html)} bytes)")
        return FetchResult(domain=label, url=url, html=html, status_code=200,
                           fetched_with="cache", content_quality=_content_quality(html))

    httpx_sem, pw_sem = _get_semaphores()

    # --- Tier 1: httpx ---
    async with httpx_sem:
        try:
            status, html, final_url = await _httpx_fetch(url)
            logger.info(f"[{label}] httpx: {status} / {len(html)} bytes")
        except Exception as e:
            if _is_fatal_network_error(e):
                logger.warning(f"[{label}] DNS failure — skipping all tiers: {e}")
                return FetchResult(domain=label, url=url, html="", status_code=0,
                                   fetched_with="blocked", blocked=True,
                                   error=f"dns_failure: {e}")
            if _is_ssl_error(e) and url.startswith("https://"):
                # Older clinic sites often have no HTTPS at all. Try HTTP before escalating.
                http_url = "http://" + url[8:]
                logger.info(f"[{label}] SSL error — trying http fallback")
                try:
                    status, html, final_url = await _httpx_fetch(http_url)
                    url = http_url  # all remaining tiers use http too
                    logger.info(f"[{label}] http fallback: {status} / {len(html)} bytes")
                except Exception as e2:
                    logger.warning(f"[{label}] http fallback failed: {e2}")
                    status, html, final_url = 0, "", url
            else:
                logger.warning(f"[{label}] httpx failed: {e}")
                status, html, final_url = 0, "", url

    httpx_status = status  # save for dual-failure check after curl_cffi

    if _is_parked(html, final_url, status):
        return _parked_result(label, url, html, status, "httpx")

    if _is_real_content(status, html):
        _write_cache(cache_file, html)
        return FetchResult(domain=label, url=url, html=html, status_code=status,
                           fetched_with="httpx", content_quality=_content_quality(html))

    if not _is_blocked(status, html):
        _write_cache(cache_file, html)
        return FetchResult(domain=label, url=url, html=html, status_code=status,
                           fetched_with="httpx", content_quality=_content_quality(html))

    logger.info(f"[{label}] httpx blocked (status={status}) — trying curl_cffi")

    # --- Tier 2: curl_cffi ---
    async with httpx_sem:
        try:
            status, html, final_url = await _curl_cffi_fetch(url)
            logger.info(f"[{label}] curl_cffi: {status} / {len(html)} bytes")
        except Exception as e:
            logger.warning(f"[{label}] curl_cffi failed: {e}")
            status, html, final_url = 0, "", url

    # If BOTH http tiers got zero bytes, it's a dead TCP connection — Playwright makes
    # the same TCP handshake and will also fail. Skip tiers 3+4 entirely (~20s saved vs 300s).
    if status == 0 and httpx_status == 0:
        logger.warning(f"[{label}] both httpx and curl_cffi got status=0 — dead domain, skipping Playwright")
        return FetchResult(domain=label, url=url, html="", status_code=0,
                           fetched_with="blocked", blocked=True,
                           error="connection_failure_all_http_tiers")

    if _is_parked(html, final_url, status):
        return _parked_result(label, url, html, status, "curl_cffi")

    if _is_real_content(status, html):
        _write_cache(cache_file, html)
        return FetchResult(domain=label, url=url, html=html, status_code=status,
                           fetched_with="curl_cffi", content_quality=_content_quality(html))

    if not _is_blocked(status, html):
        _write_cache(cache_file, html)
        return FetchResult(domain=label, url=url, html=html, status_code=status,
                           fetched_with="curl_cffi", content_quality=_content_quality(html))

    logger.info(f"[{label}] curl_cffi blocked (status={status}) — trying playwright")

    # --- Tier 3: Playwright ---
    async with pw_sem:
        try:
            status, html, final_url = await _playwright_fetch(url, stealth=False)
            logger.info(f"[{label}] playwright: {status} / {len(html)} bytes")
        except Exception as e:
            logger.error(f"[{label}] playwright failed: {e}")
            status, html, final_url = 0, "", url

    if _is_parked(html, final_url, status):
        return _parked_result(label, url, html, status, "playwright")

    # Check for challenge pages — Cloudflare JS challenges are ~8KB and pass the size
    # threshold. Don't cache them; fall through to stealth tier.
    if len(html) > 5000 and not _is_blocked(status, html):
        _write_cache(cache_file, html)
        return FetchResult(domain=label, url=url, html=html, status_code=status,
                           fetched_with="playwright", content_quality=_content_quality(html))

    logger.info(f"[{label}] playwright blocked — trying playwright+stealth")

    # --- Tier 4: Playwright + stealth ---
    async with pw_sem:
        try:
            status, html, final_url = await _playwright_fetch(url, stealth=True)
            logger.info(f"[{label}] playwright_stealth: {status} / {len(html)} bytes")
        except Exception as e:
            logger.error(f"[{label}] playwright_stealth failed: {e}")
            status, html, final_url = 0, "", url

    if _is_parked(html, final_url, status):
        return _parked_result(label, url, html, status, "playwright_stealth")

    ok = len(html) > 5000 and not _is_blocked(status, html)
    if ok:
        _write_cache(cache_file, html)
    return FetchResult(
        domain=label, url=url, html=html, status_code=status,
        fetched_with="playwright_stealth", blocked=not ok,
        error=None if ok else "all tiers blocked",
        content_quality=_content_quality(html) if ok else "ok",
    )


async def fetch(domain: str) -> FetchResult:
    """Fetch a domain homepage. Cache key = domain name."""
    url = f"https://{domain}"
    cache_file = _cache_key_for_domain(domain)
    return await _fetch_with_fallback(url, cache_file, label=domain)


async def fetch_url(url: str) -> FetchResult:
    """Fetch an arbitrary URL (subpage). Cache key = sanitized URL + hash."""
    cache_file = _cache_key_for_url(url)
    try:
        from urllib.parse import urlparse
        label = urlparse(url).netloc + urlparse(url).path
    except Exception:
        label = url[:60]
    return await _fetch_with_fallback(url, cache_file, label=label)


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO, stream=sys.stderr)
    domain = sys.argv[1] if len(sys.argv) > 1 else "example.com"

    async def main():
        result = await fetch(domain)
        print(f"domain:          {result.domain}")
        print(f"url:             {result.url}")
        print(f"status:          {result.status_code}")
        print(f"via:             {result.fetched_with}")
        print(f"blocked:         {result.blocked}")
        print(f"content_quality: {result.content_quality}")
        print(f"bytes:           {len(result.html)}")
        print("---")
        print(result.html[:500])

    asyncio.run(main())
