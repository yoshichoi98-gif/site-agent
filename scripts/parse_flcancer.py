"""Parse flcancer.com locations from data/flcancer_raw.txt. Anchor on the 'CITY, ST ZIP' line:
the line before = street, the line before that = name, the next 'Call:' line = phone. Everything
from 'Location Services:'/'Hours:' is dropped. Street kept VERBATIM (incl. source ALL-CAPS);
city title-cased for sheet consistency; zip trimmed to 5. Dry-run: prints all rows + count."""
import re

CITY_RE = re.compile(r"^(.+?),\s*([A-Z]{2})\s+(\d{5})(?:-\d{4})?\s*$")
CALL_RE = re.compile(r"Call:\s*(.+)$", re.I)


def parse():
    lines = [l.strip() for l in open("data/flcancer_raw.txt")]
    # keep non-empty lines but remember nothing else
    L = [l for l in lines if l]
    out = []
    for i, l in enumerate(L):
        m = CITY_RE.match(l)
        if not m:
            continue
        city = m.group(1).strip().title()
        state = m.group(2)
        zipc = m.group(3)
        # walk back collecting street lines: ALL-CAPS (no lowercase), not a bare block-number.
        # the first line with a lowercase letter above them is the location name.
        j = i - 1
        street_parts = []
        while j >= 0 and not re.fullmatch(r"\d+", L[j]) and not any(c.islower() for c in L[j]):
            street_parts.insert(0, L[j]); j -= 1
        street = ", ".join(street_parts)
        name = L[j] if (j >= 0 and not re.fullmatch(r"\d+", L[j])) else ""
        phone = ""
        for j in range(i + 1, min(i + 4, len(L))):
            cm = CALL_RE.search(L[j])
            if cm:
                phone = cm.group(1).strip(); break
        out.append((name, street, city, state, zipc, phone))
    return out


def main():
    rows = parse()
    states = {}
    for name, street, city, state, zipc, phone in rows:
        states[state] = states.get(state, 0) + 1
        print(f"  {name[:30]:30} | {street[:34]:34} | {city}, {state} {zipc} | {phone}")
    print(f"\nTOTAL: {len(rows)} locations | states: {states}")
    # flag suspicious streets (no digit) and missing names/phones
    for name, street, city, state, zipc, phone in rows:
        if not any(c.isdigit() for c in street) or not name or not phone:
            print(f"  SUSPECT -> name={name!r} street={street!r} phone={phone!r}")


if __name__ == "__main__":
    main()
