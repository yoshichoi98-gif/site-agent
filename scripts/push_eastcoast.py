"""Parse eastcoastresearch.net's 12 locations (hand-specified from the Manual Locations doc -
address formats too irregular for a safe regex) and REPLACE all existing eastcoastresearch.net rows.
Streets VERBATIM. Geocode-verify + zip_check. Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "eastcoastresearch.net"
SRC_URL = "https://www.eastcoastresearch.net/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

# (name, street, city, state, zip, phone)
LOCS = [
    ("Rovia Jacksonville – University (ECIR Site)", "3550 University Blvd. South, Suite 101", "Jacksonville", "FL", "32216", "(904) 854-1354"),
    ("Rovia St. Augustine (ECIR Site)", "150 Southpark Blvd., Suite 202", "St. Augustine", "FL", "32086", "(904) 310-1845"),
    ("Rovia Jacksonville – LaVilla (ECIR Site)", "915 West Monroe Street, Suite 200", "Jacksonville", "FL", "32204", "(904) 740-4118"),
    ("Rovia Lake City (ECIR Site)", "404 NW Hall of Fame Drive", "Lake City", "FL", "32055", "(386) 463-5356"),
    ("Rovia Jacksonville – Southside (ECIR Site)", "8773 Perimeter Park Court", "Jacksonville", "FL", "32216", "904-740-4120"),
    ("Rovia Palmetto Bay", "9380 SW 150th Street, Suite 140", "Miami", "FL", "33176", "(786) 310-7477"),
    ("Rovia Jacksonville – Eye Center (ECIR Site)", "11512 Lake Mead Ave #534", "Jacksonville", "FL", "32256", "(904) 564-2020 ext. 1110"),
    ("Rovia Doral (Universal Axon Site)", "3650 NW 82nd Ave, PH503", "Doral", "FL", "33166", ""),
    ("Rovia Canton (ECIR Site)", "125 Oakside Ct., Suite 301", "Canton", "GA", "30114", "(678) 785-9600"),
    ("Rovia Jefferson City (ECIR Site)", "120 Hospital Dr., Suite 260", "Jefferson City", "TN", "37760", "423-212-5593"),
    ("StudyMetrix", "3862 Mexico Road", "St. Peters", "MO", "63303", "6363875100"),
    ("Coastal Research Institute", "2139 Valleygate Dr Suite 101B", "Fayetteville", "NC", "28304", "910-500-3146"),
]


def main():
    print(f"{len(LOCS)} locations\n")
    new_rows = []
    for name, street, city, state, zipc, phone in LOCS:
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        new_rows.append([DOMAIN, name, street, city, state, zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[:44]:44} | {street[:34]:34} | {city}, {state} {zipc}{tag}{zt}")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()
    hdr, body = sheet[0], sheet[1:]
    kept = [r for r in body if r and r[0].strip().lower() != DOMAIN]
    removed = len(body) - len(kept)
    final = [hdr] + kept + new_rows
    print(f"\nremoved {removed} old {DOMAIN} rows, adding {len(new_rows)} new")

    ws.clear()
    ws.resize(rows=len(final), cols=len(hdr))
    ws.update(final, value_input_option="RAW")
    print(f"pushed {len(final)-1} data rows to sheet")

    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"re-synced local CSV ({len(fresh)-1} rows)")
    nr = sum(1 for r in new_rows if r[10] != "passed")
    flg = sum(1 for r in new_rows if r[12])
    print(f"\neastcoast: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")
    for r in new_rows:
        if r[10] != "passed" or r[12]:
            print(f"   - {r[1]} | {r[2]}, {r[3]} {r[4]} {r[5]} | vs={r[10]} zip={r[12]}")


if __name__ == "__main__":
    main()
