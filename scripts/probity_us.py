"""Thorough probity pass: fetch ALL /clinics/<slug>/ subpages from the sitemap, extract each clinic's
address (batched), filter to US locations only, write data/probity_us_locations.csv (sam_new_targets
13-col schema, domain=probitymedical.com)."""
import os, sys, re, csv, importlib.util, warnings
sys.path.insert(0, ".")
warnings.filterwarnings("ignore")
from dotenv import load_dotenv; load_dotenv()
from concurrent.futures import ThreadPoolExecutor
from firecrawl import Firecrawl
from usp.tree import sitemap_tree_for_homepage
from src.location_extract import extract_locations
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=90)
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
US_FULL = {"alabama","alaska","arizona","arkansas","california","colorado","connecticut","delaware",
 "florida","georgia","hawaii","idaho","illinois","indiana","iowa","kansas","kentucky","louisiana",
 "maine","maryland","massachusetts","michigan","minnesota","mississippi","missouri","montana",
 "nebraska","nevada","new hampshire","new jersey","new mexico","new york","north carolina",
 "north dakota","ohio","oklahoma","oregon","pennsylvania","rhode island","south carolina",
 "south dakota","tennessee","texas","utah","vermont","virginia","washington","west virginia",
 "wisconsin","wyoming"}
US_ABBR = {"al","ak","az","ar","ca","co","ct","de","fl","ga","hi","id","il","in","ia","ks","ky","la",
 "me","md","ma","mi","mn","ms","mo","mt","ne","nv","nh","nj","nm","ny","nc","nd","oh","ok","or","pa",
 "ri","sc","sd","tn","tx","ut","vt","va","wa","wv","wi","wy"}


def is_us(state, zipc):
    s = (state or "").strip().lower()
    if s in US_FULL or s in US_ABBR:
        return True
    return bool(re.fullmatch(r"\d{5}(-\d{4})?", (zipc or "").strip()))  # US zip


def fetch(url):
    try:
        r = fc.scrape(url, formats=["rawHtml"], wait_for=2500)
        return url, (getattr(r, "raw_html", None) or getattr(r, "rawHtml", "") or "")
    except Exception:
        return url, ""


def main():
    t = sitemap_tree_for_homepage("https://probitymedical.com/")
    clinics = sorted({p.url for p in t.all_pages() if re.search(r"/clinics/[^/]+/?$", p.url)})
    print(f"clinic subpages: {len(clinics)}", file=sys.stderr)

    pages = {}
    with ThreadPoolExecutor(max_workers=10) as ex:
        for url, html in ex.map(fetch, clinics):
            if html:
                pages[url] = html
    print(f"fetched {len(pages)} pages", file=sys.stderr)

    items = list(pages.items())
    locs = []
    for i in range(0, len(items), 6):  # batch of 6 pages/extract call (combined-80 under-returned)
        batch = dict(items[i:i+6])
        try:
            res, _ = extract_locations("probitymedical.com", "", batch)
            locs.extend(res.locations)
        except Exception as e:
            print("batch err", e, file=sys.stderr)

    rows, seen = [], set()
    for l in locs:
        if not is_us(l.address_state, l.address_zip):
            continue
        k = (re.sub(r"\D", "", (l.address_street or ""))[:6], (l.address_zip or "")[:5], (l.address_city or "").lower())
        if k in seen:
            continue
        seen.add(k)
        rows.append({"domain": "probitymedical.com", "location_name": l.location_name or "",
            "address_street": l.address_street or "", "address_city": l.address_city or "",
            "address_state": l.address_state or "", "address_zip": l.address_zip or "",
            "phone": l.phone or "", "source_url": l.source_url or "", "snippet": l.snippet or "",
            "confidence": l.confidence or "", "validation_status": l.validation_status or "",
            "source": "sitemap", "zip_check": zc.flag(l.address_zip or "", l.address_city or "", l.address_state or "")})
    with open("data/probity_us_locations.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    print(f"US locations: {len(rows)} | full street: {sum(1 for r in rows if r['address_street'].strip())} -> data/probity_us_locations.csv", file=sys.stderr)
    for r in rows:
        print(f"  {r['location_name'][:34]:34} | {r['address_street'][:30]:30} | {r['address_city']}, {r['address_state']} {r['address_zip']}", file=sys.stderr)


if __name__ == "__main__":
    main()
