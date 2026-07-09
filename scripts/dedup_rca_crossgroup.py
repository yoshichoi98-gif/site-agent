"""Cross-group dedup for the RCA rollup. Some member sites cross-list other practices' pages, so the
same address appears under multiple practice groups with the SAME source_url. Rule: attribute each
location to the practice that OWNS its source_url (not the domain we happened to crawl), fix the name
to "{owner practice} — {branch}", then dedup by physical address. Rewrites rca_locations_final.csv,
the staged tab, and the live locations sheet (replace the RCA rows)."""
import csv, re, urllib.parse, collections, importlib.util, gspread
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

SHEET = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
PARENT = "retinaconsultantsofamerica.com"
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status",
          "source", "zip_check", "practice_domain"]
F13 = FIELDS[:13]
CONF = {"high": 3, "medium": 2, "low": 1, "": 0}


def norm(d):
    d = (d or "").strip().lower(); d = re.sub(r"^https?://", "", d); d = re.sub(r"^www\.", "", d)
    return d.split("/")[0].strip()


def owner_dom(r):
    return norm(urllib.parse.urlparse(r["source_url"]).netloc)


def branch(name):
    return name.split("—", 1)[1].strip() if "—" in name else ""


def addrkey(r):
    s = re.sub(r"[^a-z0-9]", "", (r["address_street"] or "").lower())
    z = re.sub(r"\D", "", r["address_zip"])[:5]
    return ("s", s, z) if s else ("c", (r["address_city"] or "").lower().strip(), (r["address_state"] or "").lower().strip())


def main():
    name_by = {norm(r["practice_domain"]): r["practice_name"]
               for r in csv.DictReader(open("data/rca_practices.csv")) if r["practice_domain"].strip()}
    rows = list(csv.DictReader(open("data/rca_locations_final.csv")))

    groups = collections.defaultdict(list)
    for r in rows:
        groups[addrkey(r)].append(r)

    out = []
    for k, g in groups.items():
        owners = [owner_dom(r) for r in g]
        known = [o for o in owners if o in name_by]
        owner = collections.Counter(known or owners).most_common(1)[0][0]
        oname = name_by.get(owner) or name_by.get(norm(g[0]["practice_domain"])) or owner
        branches = [branch(r["location_name"]) for r in g]
        bb = max(branches, key=len) if any(branches) else ""
        base = dict(sorted(g, key=lambda r: (bool(r["address_street"].strip()), len(r["address_street"]),
                                             CONF.get(r["confidence"], 0)), reverse=True)[0])
        base["domain"] = PARENT
        base["location_name"] = f"{oname} — {bb}" if bb else oname
        base["practice_domain"] = owner
        out.append(base)

    out.sort(key=lambda r: r["location_name"])
    with open("data/rca_locations_final.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS, extrasaction="ignore"); w.writeheader(); w.writerows(out)

    gc = gspread.service_account(filename="credentials/google_service_account.json")
    sh = gc.open_by_key(SHEET)
    # staged tab (14-col)
    body = [[r.get(c, "") for c in FIELDS] for r in out]
    ws = sh.worksheet("retinaconsultantsofamerica_locations")
    ws.clear(); ws.resize(rows=len(body) + 1, cols=len(FIELDS)); ws.update([FIELDS] + body, value_input_option="RAW")
    # live locations sheet: replace RCA rows with deduped (13-col)
    wl = sh.worksheet("locations")
    sheet = wl.get_all_values(); hdr, b = sheet[0], sheet[1:]
    kept = [r for r in b if r and norm(r[0]) != PARENT]
    rca13 = [[r.get(c, "") for c in F13] for r in out]
    final = [hdr] + kept + rca13
    wl.clear(); wl.resize(rows=len(final), cols=len(hdr)); wl.update(final, value_input_option="RAW")
    fresh = wl.get_all_values()
    with open("data/output_locations.csv", "w", newline="") as f:
        csv.writer(f).writerows(fresh)

    print(f"RCA: {len(rows)} -> {len(out)} after cross-group dedup ({len(rows)-len(out)} removed)")
    print(f"live locations sheet now {len(fresh)-1} rows (RCA={sum(1 for r in fresh if norm(r[0])==PARENT)})")
    print("\n=== new counts by owning practice ===")
    byp = collections.Counter(r["practice_domain"] for r in out)
    for d, n in byp.most_common():
        print(f"  {name_by.get(d, d)[:40]:40} {d:34} {n:>4}")
    print(f"  TOTAL {len(out)} across {len(byp)} practices")


if __name__ == "__main__":
    main()
