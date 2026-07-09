"""Scrape each epic-care.com /location/<slug>/ page for its address via Firecrawl JSON extraction.
Stages to data/epiccare_parsed.csv (no push). Streets kept verbatim from the page."""
import os, csv, json, importlib.util
from dotenv import load_dotenv; load_dotenv()
from firecrawl import Firecrawl

vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SLUGS = ["antioch", "brentwood-ent", "castro-valley", "clayton", "danville", "dublin",
         "emeryville", "hayward", "oakland-chinatown", "pinole", "pleasant-hill", "san-leandro",
         "san-ramon-internal-medicine-podiatry", "san-ramon", "walnut-creek-cyberknife-surgery",
         "walnut-creek-ob-gyn", "walnut-creek-plastic-surgery"]
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
SCHEMA = {"type": "object", "properties": {
    "location_name": {"type": "string", "description": "The name/title of this clinic location"},
    "address_street": {"type": "string", "description": "Street address incl. suite, verbatim, no city/state/zip"},
    "address_city": {"type": "string"},
    "address_state": {"type": "string", "description": "2-letter state code"},
    "address_zip": {"type": "string"},
    "phone": {"type": "string", "description": "Main phone number"}}}


def main():
    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=90)
    rows = []
    for slug in SLUGS:
        url = f"https://epic-care.com/location/{slug}/"
        try:
            r = fc.scrape(url, formats=[{"type": "json", "prompt": "Extract this clinic location's name, street address, city, state, zip, and phone.", "schema": SCHEMA}])
            d = r.json or {}
        except Exception as e:
            print(f"  {slug:42} ERROR {e}"); continue
        st = (d.get("address_street") or "").strip()
        city = (d.get("address_city") or "").strip()
        state = (d.get("address_state") or "").strip()
        zipc = (d.get("address_zip") or "").strip()[:5]
        name = (d.get("location_name") or slug).strip()
        phone = (d.get("phone") or "").strip()
        g = vg.google_status(f"{st}, {city}, {state} {zipc}") if st else "error"
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        rows.append([ "epic-care.com", name, st, city, state, zipc, phone, url, "",
                      "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[:34]:34} | {st[:30]:30} | {city}, {state} {zipc}{tag}{zt}")
    with open("data/epiccare_parsed.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(FIELDS); w.writerows(rows)
    print(f"\nstaged {len(rows)} -> data/epiccare_parsed.csv")


if __name__ == "__main__":
    main()
