"""Partition `locations` into two NEW tabs (master `locations` untouched):
  locations_good_to_go  — rows passing all good-to-go criteria
  locations_fix_needed  — failing rows + a leading fix_reason column listing every failed check
Good-to-go = all 4 address fields present + usps_street populated + usps_dpv in {Y,S,D} +
zip_check blank + validation_status not failed/needs_review. (location_name & suite_changed ignored.)
Mirrors both to CSV; reports counts + fix_reason breakdown."""
import gspread, csv, collections
csv.field_size_limit(10_000_000)
sh = gspread.service_account(filename="credentials/google_service_account.json").open_by_key("13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4")
v = sh.worksheet("locations").get_all_values(); h = v[0]; C = {c: i for i, c in enumerate(h)}
def g(r, c): return (r[C[c]] if c in C and len(r) > C[c] else "").strip()

good, fix = [], []
reasons = collections.Counter()
for r in v[1:]:
    why = []
    miss = [f.split("_")[1] for f in ["address_street","address_city","address_state","address_zip"] if not g(r, f)]
    if miss: why.append("missing: " + ", ".join(miss))
    if not g(r, "usps_street"):
        why.append("usps not found")
    elif g(r, "usps_dpv") not in ("Y", "S", "D") and g(r, "gmaps_verified") != "Y":
        why.append(f"usps not confirmed ({g(r,'usps_dpv') or 'blank'})")
    if g(r, "zip_check"):
        why.append(f"zip_check: {g(r,'zip_check')}")
    if g(r, "validation_status") in ("failed", "needs_review"):
        why.append(f"validation: {g(r,'validation_status')}")
    if why:
        for w in why: reasons[w.split(":")[0].split(" (")[0]] += 1
        fix.append(["; ".join(why)] + r)
    else:
        good.append(r)

print(f"total {len(v)-1} | good_to_go {len(good)} | fix_needed {len(fix)} | sum {len(good)+len(fix)}")
print("fix_reason categories:", dict(reasons))

def write(title, header, rows, zipcols):
    try: w = sh.worksheet(title); w.clear()
    except gspread.WorksheetNotFound: w = sh.add_worksheet(title=title, rows=len(rows)+10, cols=len(header))
    w.resize(rows=len(rows)+1, cols=len(header))
    w.update(values=[header]+rows, range_name="A1", value_input_option="RAW")
    for col in zipcols: w.format(f"{col}1:{col}", {"numberFormat": {"type": "TEXT"}})
    w.format("A1:%s1" % chr(64+len(header)) if len(header)<=26 else "A1", {"textFormat": {"bold": True}})
    return w

# good_to_go: same schema (address_zip=F, usps_zip=R)
write("locations_good_to_go", h, good, ["F", "R"])
# fix_needed: fix_reason prepended -> address_zip shifts to G, usps_zip to S
write("locations_fix_needed", ["fix_reason"]+h, fix, ["G", "S"])

with open("data/locations_good_to_go.csv", "w", newline="") as f:
    csv.writer(f).writerow(h); csv.writer(f).writerows(good)
with open("data/locations_fix_needed.csv", "w", newline="") as f:
    csv.writer(f).writerow(["fix_reason"]+h); csv.writer(f).writerows(fix)
print("-> tabs locations_good_to_go + locations_fix_needed | CSVs mirrored")
