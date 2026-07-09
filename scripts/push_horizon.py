"""Push horizonfamilymedical.com's 35 locations (from the Manual Locations doc) to the sheet,
REPLACING existing rows. Address formats too irregular for a safe regex -> hand-specified.
Streets VERBATIM. All NY. First phone per block used (2nd is fax). Geocode-verify + zip_check.
Pull-fresh -> replace -> push -> re-sync."""
import csv, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "horizonfamilymedical.com"
SRC_URL = "https://www.horizonfamilymedical.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]

# (name, street, city, zip, phone) -- all NY
LOCS = [
    ("Chester (Primary Care)", "1460 Route 17M, STE A", "Chester", "10918", "845-469-4211"),
    ("Cornwall (Ophthalmology)", "55 Quaker Ave #104-105", "Cornwall", "12518", "845-534-5800"),
    ("Florida (Primary Care)", "21 Edward J. Lempka Dr.", "Florida", "10921", "845-651-1777"),
    ("Goshen (STE 101 - Primary/Weekend Care)", "30 Hatfield LN", "Goshen", "10924", "845-294-2733"),
    ("Goshen (STE 103 - Primary Care)", "30 Hatfield LN", "Goshen", "10924", "845-378-2222"),
    ("Goshen (STE 105 - Women's Health)", "30 Hatfield LN", "Goshen", "10924", "845-291-7400"),
    ("Goshen (STE 106 - Ophthalmology)", "30 Hatfield LN", "Goshen", "10924", "845-360-5947"),
    ("Goshen (STE 107 - Gastroenterology)", "30 Hatfield LN", "Goshen", "10924", "845-291-1260"),
    ("Goshen (STE 109B - Women's Health)", "30 Hatfield LN", "Goshen", "10924", "845-291-7400"),
    ("Goshen (STE 204 - Gastroenterology)", "70 Hatfield LN", "Goshen", "10924", "845-615-4000"),
    ("Goshen (STE 208 - Nephrology)", "30 Hatfield LN", "Goshen", "10924", "845-294-0994"),
    ("Highland Falls (Primary Care)", "144 Main Street", "Highland Falls", "10928", "845-446-4655"),
    ("Mahopac Ophthalmology", "250 Mahopac Avenue", "Yorktown Heights", "10598", "845-628-8788"),
    ("Maybrook (Primary Care)", "721 Homestead Ave", "Maybrook", "12543", "845-427-0884"),
    ("Middletown (STE 101 - Endoscopy)", "419 E Main ST, STE 101", "Middletown", "10940", "845-956-1362"),
    ("Monroe (STE 13 - Primary Care)", "1200 RT 208", "Monroe", "10950", "845-783-6266"),
    ("Monroe (STE 15 - Allergy and Immunology)", "1200 RT 208", "Monroe", "10950", "845-476-3016"),
    ("Monroe (STE 15 - Endocrinology)", "1200 RT 208", "Monroe", "10950", "845-549-1010"),
    ("Newburgh (STE 1 - Dermatology)", "400 Gidney Ave", "Newburgh", "12550", "845-561-1565"),
    ("Newburgh (STE 2 - Ophthalmology)", "53 NY-17K, Ste 2", "Newburgh", "", "845-561-4274"),
    ("New Windsor (17 Oakwood Terrace - Primary Care)", "17 Oakwood Terrace STE 100", "New Windsor", "12553", "845-561-1270"),
    ("New Windsor (270 Quassaick Ave - Primary Care)", "270 Quassaick Ave", "New Windsor", "12553", "845-569-8494"),
    ("New Windsor (905 Little Britain Rd - Primary Care)", "905 Little Britain RD", "New Windsor", "12553", "845-564-7066"),
    ("New Windsor (Critical Care/Pulmonology/Primary Care)", "3078 RT 9W", "New Windsor", "12553", "845-561-3310"),
    ("New Windsor (Endoscopy)", "88 Old RT 9W", "New Windsor", "12553", "845-549-1011"),
    ("New Windsor (Gastroenterology/Nutrition)", "277 Quassaick Ave", "New Windsor", "12553", "845-565-5630"),
    ("New Windsor (STE 100 - Endocrinology)", "17 Oakwood Terrace STE 100", "New Windsor", "12553", "845-862-2566"),
    ("New Windsor (STE 100 - Nephrology)", "17 Oakwood Terrace STE 100", "New Windsor", "12553", "845-294-0994"),
    ("New Windsor (STE 100 - Weekend Care)", "3068 US RT 9W", "New Windsor", "12553", "845-534-1024"),
    ("New Windsor (STE 100 - Women’s Health)", "17 Oakwood Terrace STE 100", "New Windsor", "12553", "845-769-8054"),
    ("New Windsor (STE 200 - Primary Care)", "3068 US RT 9W", "New Windsor", "12553", "845-534-1505"),
    ("Slate Hill (Primary Care)", "2904 RT 6,STE 1", "Slate Hill", "10973", "845-355-4611"),
    ("Warwick (21 Maple Ave - Primary Care)", "21 Maple AVE", "Warwick", "10990", "845-986-3311"),
    ("Warwick (5 Grand St - Primary Care)", "5 Grand ST", "Warwick", "10990", "845-986-7885"),
    ("Washingtonville (Primary Care)", "90 E Main ST", "Washingtonville", "10992", "845-496-2400"),
]


def main():
    print(f"{len(LOCS)} locations\n")
    new_rows = []
    for name, street, city, zipc, phone in LOCS:
        q = f"{street}, {city}, NY {zipc}".strip()
        g = vg.google_status(q)
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, "NY") if zipc else ""
        new_rows.append([DOMAIN, name, street, city, "NY", zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        if vs != "passed" or zf:
            print(f"  FLAG {name[:46]:46} | {street}, {city} {zipc} | vs={vs} zip={zf}")

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
    print(f"horizon: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
