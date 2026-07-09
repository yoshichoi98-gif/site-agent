"""
RECOVERY PHASE 1 — for domains Firecrawl couldn't scrape, use the PROJECT's own 4-tier fetcher
(httpx -> curl_cffi -> Playwright -> stealth) + extract_page_sections, then build the classify
prompt. Fresh (no cache). Output state JSONL is the SAME schema as classify_phase1, so
classify_phase2_batch consumes it directly.

Usage:
  .venv/bin/python -m scripts.recover_phase1 --input data/recover_targets.txt --state data/recover_state.jsonl --concurrency 12
"""
import argparse, asyncio, json, re, sys, tempfile, time, logging

# Force fresh fetches (no project cache) BEFORE importing anything that binds CACHE_DIR
import src.fetch as _fetch
_fetch.CACHE_DIR = tempfile.mkdtemp(prefix="recover_")

import httpx
from src.fetch import fetch as fetch_home, fetch_url
from src.html_extract import extract_page_sections
from src.planner import _extract_internal_links
from scripts.fresh_classify import (PagePicks, _ask, build_classify_prompt, mine_specialties,
                                     norm, MAX_CHARS_PER_PAGE, is_block_page, SUSPENDED_RE)

logger = logging.getLogger("recover")
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 Chrome/120 Safari/537.36"}

async def sitemap_urls(domain):
    """Best-effort: robots.txt -> sitemap(s) -> recurse child sitemaps. Returns a set of URLs."""
    urls = set()
    async with httpx.AsyncClient(timeout=10, follow_redirects=True, headers=UA, verify=False) as c:
        sm_locs = []
        try:
            r = await c.get(f"https://{domain}/robots.txt")
            sm_locs = re.findall(r"(?i)sitemap:\s*(\S+)", r.text)
        except Exception: pass
        if not sm_locs:
            sm_locs = [f"https://www.{domain}/sitemap.xml", f"https://{domain}/sitemap.xml"]
        for sm in sm_locs[:3]:
            try:
                r = await c.get(sm)
                if r.status_code != 200 or "<loc>" not in r.text: continue
                locs = re.findall(r"<loc>([^<]+)</loc>", r.text)
                for u in locs:
                    if u.endswith(".xml") and len(urls) < 400:
                        try:
                            rc = await c.get(u); urls.update(re.findall(r"<loc>([^<]+)</loc>", rc.text))
                        except Exception: pass
                    else:
                        urls.add(u)
            except Exception: pass
    return {u for u in urls if domain in u}

def _skip(domain, status, detail=""):
    return {"domain":domain,"status":status,"detail":detail,"credits":0,"sel_in":0,"sel_out":0,
            "url_specialties":[],"prompt":None,"pages_used":0}

async def prepare_one(domain, sem):
    async with sem:
        try:
            r = await fetch_home(domain)
        except Exception as e:
            return _skip(domain, "error", str(e)[:150])
        if getattr(r, "parked", False):
            return _skip(domain, "skip_parked")
        if r.blocked or not r.html:
            return _skip(domain, "skip_blocked", r.error or "no html")
        base = r.url or f"https://{domain}"
        home_text = extract_page_sections(r.html, base)
        low = home_text[:6000].lower()
        if is_block_page(home_text):  return _skip(domain, "skip_blocked", "block page")
        if SUSPENDED_RE.search(low):  return _skip(domain, "skip_suspended")
        if len(home_text) < 350:     return _skip(domain, "skip_thin")

        # discover: homepage links + sitemap
        links = _extract_internal_links(r.html, domain)
        try: sm = await sitemap_urls(domain)
        except Exception: sm = set()
        urls = sorted(set(links) | sm)
        url_specs = mine_specialties(urls)
        inv = "\n".join(urls[:120])

        loop = asyncio.get_event_loop()
        try:
            picks, pi, po = await loop.run_in_executor(None, lambda: _ask(PagePicks,
                f"Full URL inventory for {domain}. Pick <=5 pages whose CONTENT best reveals (a) what kind of org "
                f"this is, (b) whether it conducts clinical research/trials, (c) its medical specialties. Prefer "
                f"homepage, about, research/trials, providers/team or services. Avoid blogs and near-duplicates."
                f"\n\nURLS:\n{inv}"))
        except Exception as e:
            return _skip(domain, "error", str(e)[:150])

        seen = {norm(base)}; pages = {base: home_text[:MAX_CHARS_PER_PAGE]}
        inv_norm = {norm(x) for x in urls}
        picked = [u for u in picks.urls if norm(u) in inv_norm and norm(u) not in seen and not seen.add(norm(u))][:4]
        if picked:
            results = await asyncio.gather(*[fetch_url(u) for u in picked], return_exceptions=True)
            for u, rr in zip(picked, results):
                if not isinstance(rr, Exception) and rr.html and not rr.blocked:
                    pages[u] = extract_page_sections(rr.html, u)[:MAX_CHARS_PER_PAGE]
        prompt = build_classify_prompt(domain, url_specs, inv, pages)
        return {"domain":domain,"status":"pending","detail":"","credits":0,"sel_in":pi,"sel_out":po,
                "url_specialties":url_specs,"prompt":prompt,"pages_used":len(pages)}

async def run(domains, state_path, concurrency):
    sem = asyncio.Semaphore(concurrency)
    f = open(state_path, "w", encoding="utf-8")
    from collections import Counter
    ct = Counter(); done = 0; t0 = time.time()
    tasks = [asyncio.create_task(prepare_one(d, sem)) for d in domains]
    for fut in asyncio.as_completed(tasks):
        s = await fut
        f.write(json.dumps(s) + "\n"); f.flush()
        done += 1; ct[s["status"]] += 1
        if done % 20 == 0 or done == len(domains):
            print(f"  {done}/{len(domains)} | {(time.time()-t0)/60:.1f}min | {dict(ct)}", file=sys.stderr)
    f.close()
    print(f"\nRECOVERY PHASE 1 DONE in {(time.time()-t0)/60:.1f}min | {dict(ct)}", file=sys.stderr)

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--state", default="data/recover_state.jsonl")
    ap.add_argument("--concurrency", type=int, default=12)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)
    doms = [l.strip().replace("https://","").replace("http://","").strip("/").lower()
            for l in open(args.input) if l.strip() and l.strip().lower() != "domain"]
    print(f"RECOVERY PHASE 1: {len(doms)} domains via project fetcher, concurrency {args.concurrency}\n", file=sys.stderr)
    asyncio.run(run(doms, args.state, args.concurrency))

if __name__ == "__main__":
    main()
