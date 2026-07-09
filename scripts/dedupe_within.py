"""Within-domain dedupe + street normalization.
  1. Rewrite address_street to canonical_display (St->Street, Ave->Avenue, Title-cased, suite kept).
  2. Collapse rows that are the SAME normalized street (incl suite) + city + state WITHIN a domain,
     keeping the most-complete row of each group. Suites kept distinct. Cross-domain left alone.
Writes output_locations_dedup_within.csv + report. Does not overwrite in place.
"""
import csv, re, importlib.util
from collections import defaultdict

PATH = "data/output_locations.csv"
OUT = "data/output_locations_dedup_within.csv"

_spec = importlib.util.spec_from_file_location("sn", "scripts/street_norm.py")
sn = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sn)


def cityk(r): return re.sub(r"[^a-z0-9]", "", (r.get("address_city") or "").lower())
def completeness(r): return sum(1 for k in ("address_zip", "address_street", "phone",
                                            "address_city", "location_name") if (r.get(k) or "").strip())


def key(r):
    return (r["domain"].strip().lower(), sn.norm_street(r.get("address_street") or ""),
            cityk(r), (r.get("address_state") or "").strip().upper())


def main():
    rows = list(csv.DictReader(open(PATH)))
    fields = list(rows[0].keys())

    groups = defaultdict(list)
    for r in rows:
        groups[key(r)].append(r)

    out, removed, seen = [], 0, set()
    for r in rows:
        k = key(r)
        if k in seen:
            continue
        seen.add(k)
        grp = groups[k]
        best = max(grp, key=completeness)        # representative = most complete row
        out.append(best)
        removed += len(grp) - 1

    rewritten = 0
    for r in out:
        s = r.get("address_street") or ""
        if s.strip():
            c = sn.canonical_display(s)
            if c != s:
                rewritten += 1
            r["address_street"] = c

    with open(OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        w.writeheader()
        w.writerows(out)

    print(f"input rows: {len(rows)}")
    print(f"  within-domain duplicate rows removed: {removed}")
    print(f"  street values rewritten to canonical:  {rewritten}")
    print(f"  output rows: {len(out)} -> {OUT}")
    # show a few collapsed groups for sanity
    shown = 0
    for k, grp in groups.items():
        if len(grp) > 1 and shown < 6:
            shown += 1
            print(f"  collapsed [{grp[0]['domain']}] {grp[0].get('address_city')} {grp[0].get('address_state')}:")
            for g in grp:
                print(f"       {g.get('address_street')!r}  (zip {g.get('address_zip') or '-'})")


if __name__ == "__main__":
    main()
