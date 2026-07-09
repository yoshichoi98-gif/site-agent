"""
Find a LinkedIn URL for each domain by scraping its pages via Firecrawl (links + markdown formats)
and regexing for linkedin.com. Prefers the company page (/company/) over personal (/in/).
Checks homepage first, then /contact, /about-us, /about if none found.

Writes results to the 'linkedin_lookup' tab: domain | linkedin_url | type | pages_checked | all_found
"""
import argparse, csv, os, re, sys, time, random, threading, logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from dotenv import load_dotenv; load_dotenv("/Users/yoshichoi/site-agent/.env")
import gspread
from gspread.utils import rowcol_to_a1
from firecrawl import Firecrawl

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
CRED = "credentials/google_service_account.json"
app = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"])
logger = logging.getLogger("linkedin")

LINKEDIN_RE = re.compile(r'https?://[a-z0-9.-]*linkedin\.com/(company|in|school|showcase)/[^\s"\'<>)\]}\\]+', re.I)
RANK = {"company": 0, "showcase": 1, "school": 2, "in": 3}
FALLBACK_PATHS = ["contact", "about-us"]   # footer (where LinkedIn lives) is on every page; homepage usually suffices

def _retry(fn, *a, **kw):
    for i in range(5):
        try: return fn(*a, **kw)
        except Exception as e:
            if i == 4 or not any(s in str(e).lower() for s in ("rate","429","timeout","502","503","504")):
                raise
            time.sleep(min(2**i + random.random(), 30))

def scrape_links(url):
    """Return combined text (links + markdown) to search, or '' on failure."""
    try:
        doc = _retry(app.scrape, url, formats=["links", "markdown"])
    except Exception as e:
        logger.warning(f"scrape fail {url}: {str(e)[:80]}"); return ""
    links = getattr(doc, "links", None) or []
    md = getattr(doc, "markdown", None) or ""
    return "\n".join(links) + "\n" + md

def find_for(domain):
    found = {}   # url -> type
    checked = 0
    urls_to_try = [f"https://{domain}"] + [f"https://{domain}/{p}" for p in FALLBACK_PATHS]
    for u in urls_to_try:
        checked += 1
        text = scrape_links(u)
        for m in LINKEDIN_RE.finditer(text):
            full = m.group(0).rstrip(").,'\"")
            found[full] = m.group(1).lower()
        if any(t == "company" for t in found.values()):
            break   # got a company page — good enough, stop spending credits
        if found and checked >= 2:
            break   # have something and already checked 2 pages
    if not found:
        return {"domain": domain, "linkedin_url": "", "type": "none", "pages_checked": checked, "all_found": ""}
    best = min(found.items(), key=lambda kv: RANK.get(kv[1], 9))
    return {"domain": domain, "linkedin_url": best[0], "type": best[1],
            "pages_checked": checked, "all_found": " | ".join(sorted(found))}

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--tab", default="Linkedin URL Needed")
    ap.add_argument("--out-tab", default="linkedin_lookup")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--limit", type=int, default=None)
    args = ap.parse_args()
    logging.basicConfig(level=logging.WARNING, format="%(message)s", stream=sys.stderr)

    gc = gspread.service_account(filename=CRED); sh = gc.open_by_key(SHEET_ID)
    col = [c.strip() for c in sh.worksheet(args.tab).col_values(1) if c.strip()]
    domains = [c.replace("https://","").replace("http://","").strip("/").lower()
               for c in col if c.lower() != "domain"]
    if args.limit: domains = domains[:args.limit]
    print(f"Looking up LinkedIn for {domains and len(domains)} domains, {args.workers} workers\n", file=sys.stderr)

    COLS = ["domain","linkedin_url","type","pages_checked","all_found"]
    results = {}; done = 0; t0 = time.time(); lock = threading.Lock()
    def work(d):
        try: return find_for(d)
        except Exception as e: return {"domain":d,"linkedin_url":"","type":f"error","pages_checked":0,"all_found":str(e)[:80]}
    with ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(work, d): d for d in domains}
        for fut in as_completed(futs):
            r = fut.result()
            with lock:
                results[r["domain"]] = r; done += 1
                if done % 20 == 0 or done == len(domains):
                    hit = sum(1 for x in results.values() if x["linkedin_url"])
                    print(f"  {done}/{len(domains)} | {hit} found | {(time.time()-t0)/60:.1f}min", file=sys.stderr)

    ordered = [results[d] for d in domains]
    with open("data/linkedin_lookup.csv","w",newline="") as f:
        w = csv.DictWriter(f, fieldnames=COLS); w.writeheader(); w.writerows(ordered)
    if args.out_tab in [w.title for w in sh.worksheets()]: sh.del_worksheet(sh.worksheet(args.out_tab))
    ws = sh.add_worksheet(title=args.out_tab, rows=len(ordered)+10, cols=len(COLS))
    ws.update(values=[COLS]+[[str(r.get(c,"")) for c in COLS] for r in ordered], range_name="A1", value_input_option="USER_ENTERED")
    ws.format(f"A1:{rowcol_to_a1(1,len(COLS))}", {"textFormat":{"bold":True}})
    from collections import Counter
    hit = sum(1 for r in ordered if r["linkedin_url"])
    print(f"\nDONE in {(time.time()-t0)/60:.1f}min -> tab {args.out_tab!r}", file=sys.stderr)
    print(f"  found LinkedIn for {hit}/{len(ordered)} ({100*hit/max(len(ordered),1):.0f}%)", file=sys.stderr)
    print(f"  by type: {dict(Counter(r['type'] for r in ordered))}", file=sys.stderr)

if __name__ == "__main__":
    main()
