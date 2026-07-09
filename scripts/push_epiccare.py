"""Push the 17 scraped epic-care.com locations (data/epiccare_parsed.csv) to the sheet, REPLACING
all existing epic-care.com rows. Pull-fresh -> replace -> push -> re-sync."""
import csv, gspread

SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
DOMAIN = "epic-care.com"


def main():
    new_rows = list(csv.reader(open("data/epiccare_parsed.csv")))[1:]  # skip header
    print(f"{len(new_rows)} rows from staged CSV")

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    ws = gc.open_by_key(SHEET_ID).worksheet("locations")
    sheet = ws.get_all_values()
    hdr, body = sheet[0], sheet[1:]
    kept = [r for r in body if r and r[0].strip().lower() != DOMAIN]
    removed = len(body) - len(kept)
    final = [hdr] + kept + new_rows
    print(f"removed {removed} old {DOMAIN} rows, adding {len(new_rows)} new")

    ws.clear()
    ws.resize(rows=len(final), cols=len(hdr))
    ws.update(final, value_input_option="RAW")

    fresh = ws.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)
    print(f"pushed; sheet now {len(fresh)-1} data rows; local re-synced")


if __name__ == "__main__":
    main()
