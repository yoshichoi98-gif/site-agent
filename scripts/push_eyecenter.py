"""Replace all eyecenternoco.com rows with the doc's 5 locations (source of truth). Streets VERBATIM,
no phones in doc -> blank. Geocode-verify + zip_check. Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "eyecenternoco.com"
SRC_URL = "https://www.eyecenternoco.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

LOCS = [
    ("Fort Collins at Precision Center", "3151 Precision Dr", "Fort Collins", "CO", "80528"),
    ("Fort Collins at Prospect", "1725 E Prospect Rd", "Fort Collins", "CO", "80525"),
    ("Loveland at Centerra", "6125 Sky Pond Dr", "Loveland", "CO", "80538"),
    ("Loveland at Skyline", "2555 E 13th St # 225", "Loveland", "CO", "80537"),
    ("Greeley at Fox Run", "1701 61st Ave", "Greeley", "CO", "80634"),
]


def main():
    new_rows = []
    for name, street, city, state, zipc in LOCS:
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        new_rows.append([DOMAIN, name, street, city, state, zipc, "", SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name:34} | {street:22} | {city}, {state} {zipc}{tag}{zt}")

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

    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"pushed; sheet now {len(fresh)-1} data rows; local re-synced")


if __name__ == "__main__":
    main()
