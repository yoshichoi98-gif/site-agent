"""Normalize output_locations.csv:
  1. DROP truly international rows (state isn't a US state/territory).
  2. NORMALIZE state -> 2-letter US code (full names, punctuated forms like 'N.C.').
  3. NORMALIZE zip -> exactly 5 digits (zip+4 -> first 5; <5 digits -> blank).
Writes output_locations_normalized.csv and prints a report. Does not overwrite in place.
"""
import csv, re

PATH = "data/output_locations.csv"
OUT = "data/output_locations_normalized.csv"

NAME2AB = {
    "alabama": "AL", "alaska": "AK", "arizona": "AZ", "arkansas": "AR", "california": "CA",
    "colorado": "CO", "connecticut": "CT", "delaware": "DE", "florida": "FL", "georgia": "GA",
    "hawaii": "HI", "idaho": "ID", "illinois": "IL", "indiana": "IN", "iowa": "IA", "kansas": "KS",
    "kentucky": "KY", "louisiana": "LA", "maine": "ME", "maryland": "MD", "massachusetts": "MA",
    "michigan": "MI", "minnesota": "MN", "mississippi": "MS", "missouri": "MO", "montana": "MT",
    "nebraska": "NE", "nevada": "NV", "new hampshire": "NH", "new jersey": "NJ", "new mexico": "NM",
    "new york": "NY", "north carolina": "NC", "north dakota": "ND", "ohio": "OH", "oklahoma": "OK",
    "oregon": "OR", "pennsylvania": "PA", "rhode island": "RI", "south carolina": "SC",
    "south dakota": "SD", "tennessee": "TN", "texas": "TX", "utah": "UT", "vermont": "VT",
    "virginia": "VA", "washington": "WA", "west virginia": "WV", "wisconsin": "WI", "wyoming": "WY",
    "district of columbia": "DC", "puerto rico": "PR", "virgin islands": "VI", "guam": "GU",
}
US = set(NAME2AB.values()) | {"DC", "PR", "VI", "GU", "AS", "MP"}


def norm_state(raw: str):
    """Returns (normalized_state, kind) where kind in {us, us_unknown, intl, blank}."""
    s = (raw or "").strip()
    if not s:
        return "", "blank"
    if s.upper() in US:
        return s.upper(), "us"
    if s.lower() in NAME2AB:
        return NAME2AB[s.lower()], "us"
    letters = re.sub(r"[^a-z]", "", s.lower())
    if len(letters) == 2 and letters.upper() in US:          # 'N.C.' / 'D.C.'
        return letters.upper(), "us"
    if s.lower().replace(".", "").strip() in NAME2AB:        # 'Calif.' style full names
        return NAME2AB[s.lower().replace(".", "").strip()], "us"
    if letters in ("us", "usa"):                              # US but no specific state given
        return s, "us_unknown"
    return s, "intl"


def norm_zip(raw: str) -> str:
    d = re.sub(r"\D", "", (raw or ""))
    return d[:5] if len(d) >= 5 else ""


def main():
    rows = list(csv.DictReader(open(PATH)))
    fields = list(rows[0].keys())
    out, dropped, state_changes, zip_changes, us_unknown = [], [], 0, 0, []
    for r in rows:
        ns, kind = norm_state(r.get("address_state"))
        if kind == "intl":
            dropped.append(r)
            continue
        if kind == "us_unknown":
            us_unknown.append(r)
        if ns != (r.get("address_state") or "").strip():
            state_changes += 1
        r["address_state"] = ns
        nz = norm_zip(r.get("address_zip"))
        if nz != (r.get("address_zip") or "").strip():
            zip_changes += 1
        r["address_zip"] = nz
        out.append(r)

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    print(f"input rows: {len(rows)}")
    print(f"  dropped (international): {len(dropped)}")
    print(f"  state values normalized: {state_changes}")
    print(f"  zip values normalized:   {zip_changes}")
    print(f"  output rows: {len(out)} -> {OUT}")
    from collections import Counter
    print(f"  dropped by foreign state: {dict(Counter((r.get('address_state') or '').strip() for r in dropped))}")
    if us_unknown:
        print(f"  US-but-unspecified state (kept, review): {len(us_unknown)}")
        for r in us_unknown:
            print(f"     {r['domain']} | {r.get('address_street')} | {r.get('address_city')} {r.get('address_state')} {r.get('address_zip')}")
    # sanity: any remaining non-US / non-5-digit?
    bad_state = [r for r in out if (r.get('address_state') or '').strip() and (r.get('address_state').strip().upper() not in US and re.sub(r'[^a-z]','',r['address_state'].lower()) not in ('us','usa'))]
    bad_zip = [r for r in out if (r.get('address_zip') or '').strip() and not re.fullmatch(r"\d{5}", r['address_zip'].strip())]
    print(f"  sanity — remaining non-US state rows: {len(bad_state)} | non-5-digit zip rows: {len(bad_zip)}")


if __name__ == "__main__":
    main()
