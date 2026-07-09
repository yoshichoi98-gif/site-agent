"""Recover the firecrawl_failed-but-LIVE domains (data/rt_recoverable.csv) using the LOCAL tiered
fetcher (httpx -> curl_cffi -> playwright -> stealth) on the working URL variant, then the org extractor.
These failed Firecrawl due to www-only / http-only / 403-409 anti-bot. Writes org rows -> merges into
research_targets_orgs.csv (replacing the failed rows)."""
import asyncio, csv, sys, time
sys.path.insert(0, ".")
csv.field_size_limit(10_000_000)
from src.fetch import fetch_url
from src.planner import plan_crawl
from src.extract import extract
from src.pipeline import _profile_to_org_row
from src.fetch import _content_quality
from src.schema import SiteProfile

rows=list(csv.DictReader(open("data/rt_recoverable.csv")))
print(f"recovering {len(rows)} live-but-failed domains", flush=True)
SEM=asyncio.Semaphore(5)

async def recover(d, url):
    t0=time.time()
    async with SEM:
        try:
            res=await fetch_url(url)
            html=getattr(res,"html","") or ""
        except Exception as e:
            return _profile_to_org_row(d, SiteProfile(), time.time()-t0, "local_failed", f"fetch:{type(e).__name__}")
        if not html or len(html)<500:
            return _profile_to_org_row(d, SiteProfile(), time.time()-t0, "local_failed", "no_html")
        additional={}
        try:
            loop=asyncio.get_event_loop()
            plan,_=await loop.run_in_executor(None, lambda: plan_crawl(html, d))
            for p in (plan.pages[:4] if plan and plan.pages else []):
                try:
                    h=await fetch_url(p.url); hh=getattr(h,"html","") or ""
                    if hh: additional[p.url]=hh
                except Exception: pass
        except Exception: pass
        try:
            loop=asyncio.get_event_loop()
            profile,_=await loop.run_in_executor(None, lambda: extract(d, html, additional))
        except Exception as e:
            return _profile_to_org_row(d, SiteProfile(), time.time()-t0, "local", f"extract:{type(e).__name__}")
        return _profile_to_org_row(d, profile, time.time()-t0, "local_recovered", content_quality=_content_quality(html))

async def main():
    results=await asyncio.gather(*[recover(r["domain"], r.get("final_url") or r["url"]) for r in rows])
    return results

recovered=asyncio.run(main())
got=sum(1 for r in recovered if (r.get("canonical_org_name__value") or "").strip())
print(f"recovered org data: {got}/{len(recovered)}", flush=True)

# merge into research_targets_orgs.csv (replace rows for these domains)
import os
master=list(csv.DictReader(open("data/research_targets_orgs.csv")))
cols=master[0].keys() if master else recovered[0].keys()
rec_d={r["domain"] for r in recovered}
merged=[r for r in master if r["domain"] not in rec_d] + [{k:r.get(k,"") for k in cols} for r in recovered]
with open("data/research_targets_orgs.csv","w",newline="") as f:
    w=csv.DictWriter(f, fieldnames=list(cols), extrasaction="ignore"); w.writeheader(); w.writerows(merged)
print(f"merged -> research_targets_orgs.csv now {len(merged)} rows", flush=True)
for r in recovered:
    if (r.get("canonical_org_name__value") or "").strip():
        print(f"  {r['domain']:32} {r.get('fetch_status'):16} {r.get('canonical_org_name__value','')[:28]:28} | {r.get('hq_address__value','')[:30]}", flush=True)
