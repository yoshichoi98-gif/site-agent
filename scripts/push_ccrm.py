"""Parse ccrmivf.com locations from data/ccrm_raw.txt and REPLACE all existing ccrmivf.com rows.
Block = Name / street / 'City, State, zip' / phone / Directions. Drops non-US (Toronto, 6-char zip).
Full state names mapped to 2-letter. Streets VERBATIM. Geocode-verify + zip_check. Pull -> replace -> push."""
import csv, re, importlib.util, gspread
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "ccrmivf.com"
SRC_URL = "https://www.ccrmivf.com/locations"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]
STATE_ABBR = {"south carolina": "SC", "north carolina": "NC", "georgia": "GA", "florida": "FL",
              "texas": "TX", "california": "CA", "colorado": "CO", "illinois": "IL", "arizona": "AZ",
              "massachusetts": "MA", "delaware": "DE", "minnesota": "MN", "new jersey": "NJ",
              "new york": "NY", "virginia": "VA", "pennsylvania": "PA", "maryland": "MD",
              "washington": "WA"}
CITY_RE = re.compile(r"^(.+),\s*(.+),\s*(\d{5})$")   # US 5-digit only -> Canada dropped


def parse_blocks():
    raw = open("data/ccrm_raw.txt").read()
    out, dropped = [], []
    for block in raw.split("Directions"):
        lines = [l.strip() for l in block.splitlines() if l.strip()]
        if not lines:
            continue
        name = lines[0]
        ci = next((i for i, l in enumerate(lines) if CITY_RE.match(l)), None)
        if ci is None:                                # non-US (e.g. Toronto M4W 3R2)
            dropped.append(name); continue
        m = CITY_RE.match(lines[ci])
        city, st_raw, zipc = m.group(1).strip(), m.group(2).strip(), m.group(3)
        state = st_raw if len(st_raw) == 2 else STATE_ABBR.get(st_raw.lower(), st_raw)
        street = ", ".join(lines[1:ci])
        phone = lines[ci + 1] if ci + 1 < len(lines) else ""
        out.append((name, street, city, state, zipc, phone))
    return out, dropped


def main():
    parsed, dropped = parse_blocks()
    print(f"parsed {len(parsed)} US blocks | dropped non-US: {dropped}\n")
    new_rows = []
    for name, street, city, state, zipc, phone in parsed:
        g = vg.google_status(f"{street}, {city}, {state} {zipc}")
        vs = "passed" if g == "exists" else "needs_review"
        zf = zc.flag(zipc, city, state)
        new_rows.append([DOMAIN, name, street, city, state, zipc, phone, SRC_URL, "",
                         "high", vs, "manual", zf])
        tag = "" if vs == "passed" else " <REVIEW>"
        zt = f" zip:{zf}" if zf else ""
        print(f"  {name[:50]:50} | {city}, {state} {zipc}{tag}{zt}")

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
    print(f"\nccrm: {len(new_rows)} rows | needs_review: {nr} | zip_check flags: {flg}")
    for r in new_rows:
        if r[10] != "passed" or r[12]:
            print(f"   - {r[1]} | {r[2]}, {r[3]} {r[4]} {r[5]} | vs={r[10]} zip={r[12]}")


if __name__ == "__main__":
    main()
