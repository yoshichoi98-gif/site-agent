"""Push the 88 parsed flcancer.com locations to the sheet, REPLACING existing flcancer.com rows.
Reuses parse_flcancer.parse(). Streets VERBATIM (source ALL-CAPS), city title-cased, zip 5-digit,
state from cityline (FL/AL). Geocode-verify + zip_check. Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
pf = importlib.util.module_from_spec(importlib.util.spec_from_file_location("pf", "scripts/parse_flcancer.py"))
importlib.util.spec_from_file_location("pf", "scripts/parse_flcancer.py").loader.exec_module(pf)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "flcancer.com"
SRC_URL = "https://flcancer.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]


def main():
    parsed = pf.parse()
    print(f"parsed {len(parsed)} locations; geocoding...")
    new_rows = []
    for n, (name, street, city, state, zipc, phone) in enumerate(parsed, 1):
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        new_rows.append([DOMAIN, name, street, city, state, zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        if vs != "passed" or zf:
            print(f"  FLAG {name} | {street}, {city} {state} {zipc} | vs={vs} zip={zf}")

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
    nr = sum(1 for r in new_rows if r[10] != "passed")
    flg = sum(1 for r in new_rows if r[12])
    print(f"pushed; sheet now {len(fresh)-1} data rows; local re-synced")
    print(f"flcancer: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
