"""Diagnose why flagged domains returned ZERO locations. For each domain, replicate discovery
(map + homepage-link harvest + candidate_pages) and scrape each candidate with RAW extraction
(no has_street filter, no off-page guard) to separate the failure modes:

  - discovery miss : few/no candidates, raw_total == 0      -> locations live somewhere we don't reach
  - street casualty: raw_total > 0 but street_total == 0    -> found locations but none had a street
  - guard casualty : raw > kept (street rows exist but on-page guard dropped them)
  - blocked/dead   : map failed or 0 links                  -> site blocks us / no site

Reads domains from argv[1] (a CSV with a 'domain' column). Prints one diagnosis line per domain.
"""
import csv
import sys
import importlib.util
from concurrent.futures import ThreadPoolExecutor, as_completed

_spec = importlib.util.spec_from_file_location("fl", "scripts/firecrawl_locations.py")
fl = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(fl)

app = fl.Firecrawl(api_key=fl.API_KEY, timeout=fl.REQUEST_TIMEOUT_S)


def diagnose(domain: str) -> dict:
    base = f"https://{domain}"
    d = {"domain": domain, "n_map": 0, "n_home": 0, "n_cand": 0,
         "raw": 0, "street": 0, "onpage": 0, "err": "", "where": ""}
    try:
        links = fl.map_site(app, base, domain)
        d["n_map"] = len(links)
    except Exception as e:
        d["err"] = f"map:{str(e)[:60]}"
        links = []
    try:
        home = fl.harvest_home_links(app, base, domain)
        d["n_home"] = len(home)
    except Exception as e:
        home = []
    pages = fl.candidate_pages(domain, list(links) + home)
    d["n_cand"] = len(pages)
    best_page = ""
    for kind, url in pages:
        try:
            doc = fl._call_with_backoff(app.scrape, url, formats=[fl.json_format(), "markdown"],
                                        only_main_content=True, wait_for=fl.ESCALATE_WAIT_MS,
                                        _what=f"diag {url}")
            data = getattr(doc, "json", None) or {}
            md = getattr(doc, "markdown", "") or ""
            locs = data.get("locations", []) if isinstance(data, dict) else []
            locs = [(l if isinstance(l, dict) else l.model_dump()) for l in locs]
            raw = len(locs)
            street = sum(1 for l in locs if fl.has_street(l))
            onpage = sum(1 for l in locs if fl.has_street(l) and fl.street_on_page(str(l.get("address_street", "")), md))
            d["raw"] += raw
            d["street"] += street
            d["onpage"] += onpage
            if raw and not best_page:
                best_page = url
        except Exception as e:
            if not d["err"]:
                d["err"] = f"scrape:{str(e)[:50]}"
    d["where"] = best_page
    # classify
    if d["n_map"] == 0 and d["n_home"] == 0:
        d["bucket"] = "BLOCKED/DEAD"
    elif d["raw"] == 0:
        d["bucket"] = "DISCOVERY-MISS"
    elif d["street"] == 0:
        d["bucket"] = "NO-STREET-on-page"
    elif d["onpage"] == 0:
        d["bucket"] = "GUARD-dropped"
    else:
        d["bucket"] = "SHOULD-HAVE-WORKED"  # raw+street+onpage>0 yet final was 0 -> dedupe/logic bug
    return d


def main():
    domains = [r["domain"].strip() for r in csv.DictReader(open(sys.argv[1])) if r.get("domain")]
    results = []
    with ThreadPoolExecutor(max_workers=10) as ex:
        futs = {ex.submit(diagnose, d): d for d in domains}
        for fut in as_completed(futs):
            r = fut.result()
            results.append(r)
            print(f"{r['bucket']:20} {r['domain']:32} map={r['n_map']:<4} home={r['n_home']:<3} "
                  f"cand={r['n_cand']:<3} raw={r['raw']:<3} street={r['street']:<3} onpage={r['onpage']:<3} "
                  f"{('err='+r['err']) if r['err'] else ''} {r['where']}")
    print("\n=== bucket summary ===")
    from collections import Counter
    for b, c in Counter(x["bucket"] for x in results).most_common():
        print(f"  {b}: {c}")


if __name__ == "__main__":
    main()
