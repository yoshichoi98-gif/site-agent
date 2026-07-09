"""Parse ankleandfootcenters.com's 41 locations from data/ankle_raw.txt and REPLACE all existing
ankleandfootcenters.com rows in the sheet with them. Streets kept VERBATIM (no canonicalization,
per Yoshi's preference). Geocode-verify + zip_check each. Pull-fresh sheet -> replace domain rows
-> full push -> re-sync local CSV."""
import csv, re, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "ankleandfootcenters.com"
SRC_URL = "https://www.ankleandfootcenters.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
CITY_RE = re.compile(r"^(.*?),?\s+(?:GA|Georgia)\s+(\d{5})(?:-\d{4})?$")


def parse_blocks():
    raw = open("data/ankle_raw.txt").read()
    out = []
    for block in raw.split("Directions"):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0]
        city = zipc = ""
        ci = None
        for idx, l in enumerate(lines):
            m = CITY_RE.match(l)
            if m:
                city, zipc = m.group(1).strip(), m.group(2)
                ci = idx
                break
        if ci is None:
            print("  !! no city line for", name); continue
        street = ", ".join(lines[1:ci])               # street + suite/unit/building, verbatim
        phone = ""
        for l in lines:
            if l.lower().startswith("phone:"):
                phone = l.split(":", 1)[1].strip(); break
        out.append((name, street, city, zipc, phone))
    return out


def main():
    parsed = parse_blocks()
    print(f"parsed {len(parsed)} blocks\n")
    new_rows = []
    for name, street, city, zipc, phone in parsed:
        g = vg.google_status(f"{street}, {city}, GA {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, "GA")
        new_rows.append([DOMAIN, name, street, city, "GA", zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[:22]:22} | {street[:42]:42} | {city} {zipc}{tag}{zt}")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()
    hdr = sheet[0]
    body = sheet[1:]
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
    print(f"\nankle: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")


if __name__ == "__main__":
    main()
