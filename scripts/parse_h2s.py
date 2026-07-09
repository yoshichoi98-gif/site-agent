"""Parse data/h2s_manual.txt -> hand2shouldercenter.com rows. Handles building-name + suite on
separate lines (before or after the street). Canonicalizes, geocode-verifies. Stages to data/h2s_parsed.csv."""
import csv, re, importlib.util
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)

CITY_RE = re.compile(r"^(.+?),?\s+([A-Za-z]{2})\s+(\d{5})$")
SUITE_RE = re.compile(r"((?:suite|ste\.?|#)\s*[A-Za-z0-9][A-Za-z0-9 \-]*?)\s*$", re.I)
FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source"]


def main():
    lines = [ln.strip() for ln in open("data/h2s_manual.txt") if ln.strip()]
    lines = [ln for ln in lines if not ln.lower().startswith("fax:")]

    records, pending, phone = [], [], ""
    i = 0
    while i < len(lines):
        ln = lines[i]
        m = CITY_RE.match(ln)
        if m and pending:
            name = pending[0]
            addr_lines = pending[1:]
            base = next((a for a in addr_lines if re.match(r"^\d", a)), addr_lines[-1] if addr_lines else "")
            base = base.rstrip(", ")
            if not re.search(r"\b(suite|ste|#)\b", base, re.I):       # base lacks a suite -> pull one from another line
                for a in addr_lines:
                    if a is base:
                        continue
                    sm = SUITE_RE.search(a)
                    if sm:
                        base = base + ", " + sm.group(1).strip()
                        break
            ph = ""
            if i + 1 < len(lines) and lines[i + 1].lower().startswith("phone:"):
                ph = lines[i + 1].split(":", 1)[1].strip()
                i += 1
            records.append({"name": name, "street": sn.canonical_display(base), "city": m.group(1).strip(),
                            "state": m.group(2).upper(), "zip": m.group(3), "phone": ph})
            pending = []
        else:
            pending.append(ln)
        i += 1

    print("parsed " + str(len(records)) + " blocks")
    out = []
    for r in records:
        g = vg.google_status(r["street"] + ", " + r["city"] + ", " + r["state"] + " " + r["zip"])
        vs = "passed" if g == "exists" else "needs_review"
        out.append({"domain": "hand2shouldercenter.com", "location_name": r["name"], "address_street": r["street"],
                    "address_city": r["city"], "address_state": r["state"], "address_zip": r["zip"], "phone": r["phone"],
                    "source_url": "https://hand2shouldercenter.com", "snippet": "", "confidence": "high",
                    "validation_status": vs, "source": "manual"})
        flag = "" if g == "exists" else "  <-- REVIEW"
        print("  " + vs.ljust(12) + " " + r["street"] + ", " + r["city"] + " " + r["state"] + " " + r["zip"] + " | " + r["phone"] + flag)

    with open("data/h2s_parsed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(out)
    print("staged " + str(len(out)) + " -> data/h2s_parsed.csv")


if __name__ == "__main__":
    main()
