"""Push urologyclinics.com's locations from the Manual Locations doc. 22 unique (the Mesquite
office is listed in both the main and Cancer Clinics sections identically -> collapsed). Name =
facility name when given, else the area header. Streets VERBATIM (multi-line joined). All TX.
Geocode-verify + zip_check. Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "urologyclinics.com"
SRC_URL = "https://urologyclinics.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

# (name, street, city, zip, phone) -- all TX
LOCS = [
    ("Presbyterian Hospital of Allen", "1105 N Central Expressway, Suite 230", "Allen", "75013", "469-678-8370"),
    ("Baylor Hospital At Carrollton", "4325 N. Josey Lane, Plaza III, Suite 301", "Carrollton", "75010", "214-915-8515"),
    ("Methodist Dallas Medical Center", "221 W. Colorado Blvd, Methodist Pavilion II, Suite 443", "Dallas", "75208", "214-271-9971"),
    ("Medical City Hospital of Dallas", "7777 Forest Lane, Building C, Suite 565", "Dallas", "75230", "972-566-7765"),
    ("Baylor, Scott & White Medical Center", "3417 Gaston Avenue, Suite 830", "Dallas", "75246", "214-826-6021"),
    ("UROPharmacy", "9900 North Central Expressway, Suite 120", "Dallas", "75231", "214-580-2265"),
    ("Texas Health Presbyterian Hospital of Dallas", "8230 Walnut Hill Lane, Professional Building 3, Suite 700", "Dallas", "75231", "214-691-1902"),
    ("Medical City of Denton", "3537 S Interstate 35 E, Suite 315", "Denton", "76210", "940-536-0706"),
    ("Presbyterian Hospital Of Flower Mound", "4370 Medical Arts Drive, Suite 270", "Flower Mound", "75028", "972-394-4500"),
    ("Fort Worth (N Riverside Drive)", "10932 N Riverside Drive, Suite 100", "Fort Worth", "76244", "214-915-8506"),
    ("Frisco (Coit Road)", "4401 Coit Road, MOB I Suite 309", "Frisco", "75035", "469-678-8370"),
    ("Frisco (PGA Parkway)", "16050 Everwell Lane, Suite 401A", "Frisco", "75033", "469-678-8370"),
    ("Garland (Naaman Forest Blvd)", "6460 Naaman Forest Blvd", "Garland", "75044", "972-494-6764"),
    ("Grapevine (Lancaster Drive)", "1631 Lancaster Drive, Suite 350", "Grapevine", "76051", "214-915-8502"),
    ("Baylor Scott & White Health", "5220 W University, Suite 210", "McKinney", "75071", "469-678-8370"),
    ("Mesquite/Sunnyvale (State Highway 352)", "920 State Highway 352, Suite 100", "Mesquite", "75149", "972-270-8859"),
    ("Baylor Scott & White Medical Center Plano", "4708 Alliance Boulevard, Pavilion I, Suite 835", "Plano", "75093", "972-566-7765"),
    ("Presbyterian Hospital of Plano – MOB 3", "6124 West Parker Road, Suite 434", "Plano", "75093", "214-691-1902"),
    ("Presbyterian Hospital Of Rockwall", "890 Rockwall Parkway, Suite 110", "Rockwall", "75032", "972-494-6764"),
    ("Cancer Clinics of North Texas (Dallas – NorthPointe Medical Arts)", "12606 Greenville Avenue", "Dallas", "75243", "214-691-9377"),
    ("Cancer Clinics of North Texas (Plano – W Plano Pkwy)", "6957 W Plano Pkwy, Suite 1300", "Plano", "75093", "972-820-1400"),
    ("UCNT Radiation Center", "2800 State Hwy 114, Suite 100", "Trophy Club", "76262", "817-778-4481"),
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
        if vs != "passed" or zf:
            print(f"  FLAG {name[:44]:44} | {street}, {city} {zipc} | vs={vs} zip={zf}")

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
    print(f"urologyclinics: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
