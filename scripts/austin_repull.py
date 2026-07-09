"""Re-pull austinretina.com per-center subpages (full streets), replace Austin's rows in the RCA
rollup, and re-push the staged tab + live locations sheet."""
import os, sys, re, csv, importlib.util, gspread
sys.path.insert(0, ".")
from dotenv import load_dotenv; load_dotenv()
from firecrawl import Firecrawl
from src.location_extract import extract_locations
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
PARENT = "retinaconsultantsofamerica.com"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status",
          "source", "zip_check", "practice_domain"]
F13 = FIELDS[:13]
SUBS = ["bastrop", "georgetown", "killeen", "lakeway", "main-office", "marble-falls",
        "round-rock-office", "san-marcos", "south-austin-office", "temple", "waco"]


def norm(d):
    d = (d or "").strip().lower(); d = re.sub(r"^https?://", "", d); d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].strip()


def main():
    fc = Firecrawl(api_key=os.environ["FIRECRAWL_API_KEY"], timeout=90)
    pages = {}
    for s in SUBS:
        u = f"https://www.austinretina.com/retina-centers/{s}"
        try:
            r = fc.scrape(u, formats=["rawHtml"], wait_for=3000)
            h = getattr(r, "raw_html", None) or getattr(r, "rawHtml", "") or ""
            if h:
                pages[u] = h
        except Exception as e:
            print("err", s, e)
    res, _ = extract_locations("austinretina.com", "", pages)
    new = []
    for l in res.locations:
        nm = (l.location_name or "").strip()
        new.append({
            "domain": PARENT, "location_name": f"Austin Retina Associates — {nm}" if nm else "Austin Retina Associates",
            "address_street": l.address_street or "", "address_city": l.address_city or "",
            "address_state": l.address_state or "", "address_zip": l.address_zip or "",
            "phone": l.phone or "", "source_url": l.source_url or "", "snippet": l.snippet or "",
            "confidence": l.confidence or "", "validation_status": l.validation_status or "",
            "source": "rca_rollup", "zip_check": zc.flag(l.address_zip or "", l.address_city or "", l.address_state or ""),
            "practice_domain": "austinretina.com",
        })
    print(f"new Austin rows: {len(new)} | full street: {sum(1 for r in new if r['address_street'].strip())}")

    rows = [r for r in csv.DictReader(open("data/rca_locations_final.csv")) if norm(r["practice_domain"]) != "austinretina.com"]
    rows += new
    rows.sort(key=lambda r: r["location_name"])
    with open("data/rca_locations_final.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(rows)

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    sh = gc.open_by_key(SHEET)
    body = [[r.get(c, "") for c in FIELDS] for r in rows]
    ws = sh.worksheet("retinaconsultantsofamerica_locations")
    ws.clear(); ws.resize(rows=len(body) + 1, cols=len(FIELDS)); ws.update([FIELDS] + body, value_input_option="RAW")
    wl = sh.worksheet("locations")
    sheet = wl.get_all_values(); hdr, b = sheet[0], sheet[1:]
    kept = [r for r in b if r and norm(r[0]) != PARENT]
    final = [hdr] + kept + [[r.get(c, "") for c in F13] for r in rows]
    wl.clear(); wl.resize(rows=len(final), cols=len(hdr)); wl.update(final, value_input_option="RAW")
    fresh = wl.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"RCA total now {len(rows)} | live locations sheet {len(fresh)-1} rows")


if __name__ == "__main__":
    main()
