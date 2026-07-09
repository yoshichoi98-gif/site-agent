import csv, re, importlib.util
sn = importlib.util.module_from_spec(importlib.util.spec_from_file_location("sn", "scripts/street_norm.py"))
importlib.util.spec_from_file_location("sn", "scripts/street_norm.py").loader.exec_module(sn)
vg = importlib.util.module_from_spec(importlib.util.spec_from_file_location("vg", "scripts/verify_google.py"))
importlib.util.spec_from_file_location("vg", "scripts/verify_google.py").loader.exec_module(vg)
zc = importlib.util.module_from_spec(importlib.util.spec_from_file_location("zc", "scripts/zip_check.py"))
importlib.util.spec_from_file_location("zc", "scripts/zip_check.py").loader.exec_module(zc)

FIELDS = ["domain", "location_name", "address_street", "address_city", "address_state",
          "address_zip", "phone", "source_url", "snippet", "confidence", "validation_status", "source", "zip_check"]


def parse_blocks():
    lines = [l.rstrip("\n") for l in open("data/unitedgi_raw.txt")]
    out, i = [], 0
    while i < len(lines):
        if lines[i].startswith("### "):
            name = lines[i][4:].strip()
            addr = phone = ""
            j = i + 1
            while j < len(lines) and not lines[j].startswith("### "):
                s = lines[j].strip()
                if s.startswith("**") and not addr:
                    addr = s.strip("*").strip()
                if s.lower().startswith("ph:") and not phone:
                    phone = s.split(":", 1)[1].strip()
                j += 1
            out.append((name, addr, phone)); i = j
        else:
            i += 1
    return out


def parse_addr(addr):
    parts = [p.strip() for p in addr.split(",")]
    z = re.search(r"\d{5}", parts[-1]); zc_ = z.group(0) if z else ""
    city_cand = parts[-2] if len(parts) >= 2 else ""
    street_parts = parts[:-2]
    if re.search(r"\d", city_cand):                       # malformed: "Ste. 100 Riverside"
        m = re.search(r"(\d[\w-]*)\s+([A-Za-z].*)$", city_cand)
        if m:
            city = m.group(2).strip()
            street_parts = street_parts + [city_cand[:m.end(1)].strip()]
        else:
            city = city_cand
    else:
        city = city_cand
    street = ", ".join([p for p in street_parts if p])
    return sn.canonical_display(street), city, zc_


def main():
    rows = []
    skipped = []
    for name, addr, phone in parse_blocks():
        if not addr or "CA" not in addr:
            skipped.append(name); continue
        street, city, z = parse_addr(addr)
        g = vg.google_status(street + ", " + city + ", CA " + z)
        r = {"domain": "unitedgi.com", "location_name": name, "address_street": street, "address_city": city,
             "address_state": "CA", "address_zip": z, "phone": phone, "source_url": "https://unitedgi.com",
             "snippet": "", "confidence": "high", "validation_status": "passed" if g == "exists" else "needs_review",
             "source": "manual"}
        r["zip_check"] = zc.flag(z, city, "CA")
        rows.append(r)
    with open("data/unitedgi_parsed.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=FIELDS); w.writeheader(); w.writerows(rows)
    nr = sum(1 for r in rows if r["validation_status"] != "passed")
    print("parsed " + str(len(rows)) + " (skipped " + str(len(skipped)) + " no-address: " + ", ".join(skipped) + ")")
    print("needs_review: " + str(nr) + " | zip_check flags: " + str(sum(1 for r in rows if r["zip_check"])))
    for r in rows:
        flag = "" if r["validation_status"] == "passed" else " <REVIEW>"
        zf = (" zip:" + r["zip_check"]) if r["zip_check"] else ""
        print("  " + r["location_name"][:40].ljust(40) + " | " + r["address_street"] + ", " + r["address_city"] + " " + r["address_zip"] + flag + zf)


if __name__ == "__main__":
    main()
