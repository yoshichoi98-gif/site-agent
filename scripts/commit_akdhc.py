import csv, gspread
SHEET_ID = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
gc = gspread.service_account(filename="credentials/google_service_account.json")
ws = gc.open_by_key(SHEET_ID).worksheet("locations")

sheet = ws.get_all_values()          # pull fresh (source of truth)
hdr = sheet[0]
new = list(csv.DictReader(open("data/akdhc_parsed.csv")))
new_rows = [[r.get(c, "") for c in hdr] for r in new]

kept = [row for row in sheet[1:] if row[0].strip().lower() != "akdhc.com"]
old = len(sheet[1:]) - len(kept)
out = [hdr] + kept + new_rows

ws.clear()
ws.resize(rows=len(out) + 5, cols=len(hdr))
ws.update(out, value_input_option="RAW")
print("replaced " + str(old) + " old akdhc rows with " + str(len(new_rows)) + "; sheet now " + str(len(out) - 1) + " data rows")

# re-sync local + verify identical
fresh = ws.get_all_values()
with open("data/output_locations.csv", "w", newline="") as f:
    csv.writer(f).writerows(fresh)
local = list(csv.reader(open("data/output_locations.csv")))
w = len(local[0])
def norm(r): return [c.strip() for c in (list(r) + [""] * (w - len(r)))[:w]]
diff = sum(1 for i in range(min(len(fresh), len(local))) if norm(fresh[i]) != norm(local[i]))
print("CSV vs sheet diffs: " + str(diff) + " | akdhc rows now: " + str(sum(1 for r in fresh[1:] if r[0] == "akdhc.com")))
