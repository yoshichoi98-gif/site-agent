"""Push urologyaustin.com's 15 locations (from the Manual Locations doc) to the sheet, REPLACING
existing rows. Streets VERBATIM (suite/building lines joined). All TX. Geocode-verify + zip_check.
Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "urologyaustin.com"
SRC_URL = "https://urologyaustin.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

# (name, street, city, zip, phone) -- all TX
LOCS = [
    ("Apex Cancer Care – Austin (Radiation Oncology)", "1020 West 34th Street", "Austin", "78705", "512-337-9020"),
    ("Apex Cancer Care – Kyle (Radiation Oncology)", "1180 Seton Parkway, Suite 150", "Kyle", "78640", "512-337-9020"),
    ("Atrium Office", "8701 North Mopac Expressway, Suite 200", "Austin", "78759", "512-788-9688"),
    ("Bastrop Office", "3101 Highway 71 East, Suite 210-A", "Bastrop", "78602", "512-788-9688"),
    ("Cedar Park Office", "1401 Medical Parkway, Building B, Suite 101", "Cedar Park", "78613", "512-788-9688"),
    ("Dripping Springs Office", "13830 Sawyer Ranch Road, Suite 201", "Dripping Springs", "78620", "512-788-9688"),
    ("Georgetown Office", "1900 Scenic Drive, Suite 1114", "Georgetown", "78626", "512-788-9688"),
    ("Kyle Office", "1180 Seton Parkway, Suites 125 and 320", "Kyle", "78640", "512-788-9688"),
    ("Lakeway Office", "101 Medical Parkway, Suite 200", "Lakeway", "78738", "512-788-9688"),
    ("Marble Falls Office", "2503 US 281 North, Suite 400", "Marble Falls", "78654", "512-788-9688"),
    ("Radam Lane Office", "608 Radam Lane", "Austin", "78745", "512-788-9688"),
    ("Round Rock Office", "16040 Park Valley Drive, Building 1, Suite 111", "Round Rock", "78681", "512-788-9688"),
    ("Urology Austin Interventional Radiology (IR)", "8701 North Mopac Expressway, Suite 100", "Austin", "78759", "737-241-2184"),
    ("Urology Austin Pharmacy", "8701 North Mopac Expressway, Suite 375", "Austin", "78759", "512-410-3770"),
    ("Westlake Office", "5300 Bee Caves Road, Building 1, Suite 100", "West Lake Hills", "78746", "512-788-9688"),
]


def main():
    print(f"{len(LOCS)} locations\n")
    new_rows = []
    for name, street, city, zipc, phone in LOCS:
        g = vg.google_status(f"{street}, {city}, TX {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, "TX")
        new_rows.append([DOMAIN, name, street, city, "TX", zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[:44]:44} | {street[:42]:42} | {city} {zipc}{tag}{zt}")

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
    print(f"urologyaustin: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
