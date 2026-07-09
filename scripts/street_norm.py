"""Street-address normalizer for dedupe. Produces a canonical comparison key:
lowercase, expand directional + street-type abbreviations, standardize unit markers, strip
punctuation. Two keys: with suite (norm_street) and without (norm_street_nosuite)."""
import re

_DIR = {"n": "north", "s": "south", "e": "east", "w": "west", "ne": "northeast",
        "nw": "northwest", "se": "southeast", "sw": "southwest"}
_TYPE = {"st": "street", "str": "street", "ave": "avenue", "av": "avenue", "rd": "road",
         "blvd": "boulevard", "dr": "drive", "ln": "lane", "ct": "court", "pl": "place",
         "pkwy": "parkway", "pky": "parkway", "hwy": "highway", "hway": "highway",
         "cir": "circle", "ter": "terrace", "terr": "terrace", "sq": "square", "trl": "trail",
         "pt": "point", "plz": "plaza", "expy": "expressway", "fwy": "freeway"}
_UNIT_WORDS = ("suite", "ste", "unit", "apt", "apartment", "floor", "fl", "rm", "room",
               "bldg", "building", "department", "dept")


def _canon_tokens(s: str, drop_unit: bool) -> str:
    s = s.lower()
    s = s.replace("#", " suite ")
    s = re.sub(r"[.,]", " ", s)
    s = re.sub(r"[^a-z0-9\s]", " ", s)        # drop remaining punctuation
    toks = s.split()
    out = []
    i = 0
    while i < len(toks):
        t = toks[i]
        if drop_unit and t in _UNIT_WORDS:
            break  # everything from the unit marker on is suite/floor info — drop it
        t = _DIR.get(t, t)
        t = _TYPE.get(t, t)
        out.append(t)
        i += 1
    return " ".join(out).strip()


def norm_street(s: str) -> str:
    """Canonical street incl. suite (St->street, Ave->avenue, '#'->suite, etc.)."""
    return _canon_tokens(s or "", drop_unit=False)


def norm_street_nosuite(s: str) -> str:
    """Canonical street with suite/unit/floor info stripped — same building collapses."""
    return _canon_tokens(s or "", drop_unit=True)


# ── Display canonicalization (expanded, Title-Cased, suite preserved) ──────────
_DIR_FULL = {"n": "North", "s": "South", "e": "East", "w": "West", "ne": "Northeast",
             "nw": "Northwest", "se": "Southeast", "sw": "Southwest"}
_TYPE_FULL = {"st": "Street", "str": "Street", "ave": "Avenue", "av": "Avenue", "rd": "Road",
              "blvd": "Boulevard", "dr": "Drive", "ln": "Lane", "ct": "Court", "pl": "Place",
              "pkwy": "Parkway", "pky": "Parkway", "hwy": "Highway", "hway": "Highway",
              "cir": "Circle", "ter": "Terrace", "terr": "Terrace", "sq": "Square", "trl": "Trail",
              "pt": "Point", "plz": "Plaza", "expy": "Expressway", "fwy": "Freeway",
              "rte": "Route", "rt": "Route"}
_UNIT_CANON = {"ste": "Suite", "suite": "Suite", "unit": "Unit", "apt": "Apt", "apartment": "Apt",
               "floor": "Floor", "fl": "Floor", "rm": "Room", "room": "Room", "bldg": "Building",
               "building": "Building", "dept": "Dept", "department": "Dept", "lobby": "Lobby",
               "level": "Level"}
_ROADISH = {"rd", "road", "rte", "rt", "route", "hwy", "highway"}


def _titlecase(tok: str) -> str:
    if re.fullmatch(r"\d+(st|nd|rd|th)", tok.lower()):       # ordinals: 4th, 88th -> lowercase suffix
        return tok.lower()
    if any(c.isdigit() for c in tok) and any(c.isalpha() for c in tok):
        return tok.upper()                                   # alnum unit values: 8A, E102
    return tok.capitalize()


def canonical_display(s: str) -> str:
    """Readable canonical: '2155 E Paris Ave SE, Suite 100' -> '2155 East Paris Avenue Southeast,
    Suite 100'. Expands directionals + street types, Title-cases, standardizes the unit marker,
    and PRESERVES the suite/unit value (suites are kept distinct)."""
    raw = (s or "").strip()
    if not raw:
        return ""
    work = re.sub(r"\b(?:suite|ste)\.?\s*#\s*", "Suite ", raw, flags=re.I)  # "Suite# 300" -> "Suite 300" (no double)
    work = re.sub(r"#\s*", "Suite ", work)                                  # standalone "#221" -> "Suite 221"
    work = re.sub(r"[.,]", " ", work)
    work = re.sub(r"\s+", " ", work).strip()
    toks = work.split()
    low = [t.lower() for t in toks]
    # split at first unit marker
    cut = next((i for i, t in enumerate(low) if t in _UNIT_CANON), len(toks))
    # floor value usually PRECEDES the marker ("4th Floor") — pull the ordinal into the unit
    if cut < len(toks) and low[cut] in ("floor", "fl") and cut > 0 and re.fullmatch(r"\d+(st|nd|rd|th)", low[cut - 1]):
        cut -= 1
    main, unit = toks[:cut], toks[cut:]

    out_main = []
    for i, t in enumerate(main):
        tl = t.lower()
        if tl == "st":
            nxt = main[i + 1].lower() if i + 1 < len(main) else ""
            if nxt in _ROADISH:
                out_main.append("State")                       # "St Rd 60" -> "State Road 60"
            elif nxt == "" or nxt in _DIR_FULL or nxt in _TYPE_FULL:
                out_main.append("Street")                      # "Main St", "Main St N" -> Street (suffix)
            else:
                out_main.append("Saint")                       # "St Francis Dr" -> "Saint Francis Drive"
        elif tl in _DIR_FULL:
            out_main.append(_DIR_FULL[tl])
        elif tl in _TYPE_FULL:
            out_main.append(_TYPE_FULL[tl])
        else:
            out_main.append(_titlecase(t))
    main_str = " ".join(out_main)

    if not unit:
        return main_str
    unit_out = [_UNIT_CANON.get(t.lower(), _titlecase(t)) for t in unit]
    collapsed = []                                            # collapse "Suite Suite" (from '#') etc.
    for w in unit_out:
        if not collapsed or collapsed[-1].lower() != w.lower():
            collapsed.append(w)
    return f"{main_str}, {' '.join(collapsed)}"
