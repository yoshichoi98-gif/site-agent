"""Scrape each synovationmedicalgroup.com /location/<slug>/ page for its address via Firecrawl JSON
extraction (markdown-regex fallback). Stages to data/synovation_parsed.csv (no push)."""
import os, csv, re, importlib.util
from dotenv import load_dotenv; load_dotenv()
from firecrawl import Firecrawl
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SLUGS = ["anderson-sc", "azusa-ca", "chino-ca", "chula-vista-ca", "colton-ca", "corona-ca",
         "culver-city-ca", "escondido-ca", "fountain-valley-ca", "fullerton-ca", "hallandale-fl",
         "homestead-fl", "los-angeles-dtla", "pasadena-ca", "pomona-ca", "rancho-cucamonga-ca",
         "rancho-mirage-ca", "reseda-ca", "san-diego-ca", "santa-ana-ca", "santa-clarita-ca",
         "simi-valley-ca", "south-miami-fl", "torrance-ca", "visalia-ca", "wichita-falls-tx"]
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
SCHEMA = {"type": "object", "properties": {
    "location_name": {"type": "string", "description": "The name/title of this clinic location"},
    "address_street": {"type": "string", "description": "Street address incl. suite, verbatim, no city/state/zip"},
    "address_city": {"type": "string"}, "address_state": {"type": "string", "description": "2-letter state code"},
    "address_zip": {"type": "string"}, "phone": {"type": "string", "description": "Main phone number"}}}
CITY_RE = re.compile(r"([A-Za-z .'-]+),\s*([A-Z]{2})\s+(\d{5})")


def fallback(md):
    m = CITY_RE.search(md or "")
    if not m:
        return None
    lines = [l.strip() for l in (md or "").splitlines() if l.strip()]
    st = ""
    for k, l in enumerate(lines):
        if m.group(1).strip() in l and m.group(3) in l:
            for back in range(k - 1, max(k - 4, -1), -1):
                if re.match(r"^\d+\s+\S", lines[back]):
                    st = lines[back]; break
            break
    return st, m.group(1).strip(), m.group(2), m.group(3)


def main():
    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=120)
    rows = []
    for slug in SLUGS:
        url = f"https://www.synovationmedicalgroup.com/location/{slug}/"
        st = city = state = zipc = phone = ""
        name = slug.replace("-", " ").title()
        try:
            r = fc.scrape(url, formats=[{"type": "json", "prompt": "Extract this clinic location's name, street address, city, state, zip, and phone.", "schema": SCHEMA}, "markdown"])
            d = r.json or {}
            st = (d.get("address_street") or "").strip()
            city = (d.get("address_city") or "").strip()
            state = (d.get("address_state") or "").strip()
            zipc = (d.get("address_zip") or "").strip()[:5]
            name = (d.get("location_name") or name).strip()
            phone = (d.get("phone") or "").strip()
            if not st or not zipc:
                fb = fallback(r.markdown)
                if fb:
                    st = st or fb[0]; city = city or fb[1]; state = state or fb[2]; zipc = zipc or fb[3]
        except Exception as e:
            print(f"  {slug:22} ERROR {e}")
        g = vg.google_status(f"{st}, {city}, {state} {zipc}") if st else "error"
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        rows.append(["synovationmedicalgroup.com", name, st, city, state, zipc, phone, url, "", "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {slug:22} | {st[:30]:30} | {city}, {state} {zipc}{tag}{zt}")
    with open("data/synovation_parsed.csv", "w", newline="") as f:
        w = csv.writer(f); w.writerow(FIELDS); w.writerows(rows)
    print(f"\nstaged {len(rows)} -> data/synovation_parsed.csv")


if __name__ == "__main__":
    main()
