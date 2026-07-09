#!/usr/bin/env python3
"""Extract clean, bounded text + key hooks from the local raw-HTML site cache
(data/cache/<domain>.html, ~83k pages) for email personalization.

Usage: python3 read_site_cache.py charterresearch.com artemis-research.com ...
Prints per domain: title, meta description, first ~1800 chars of visible text,
and keyword hook hits. Keeps output small (no full-HTML dump).
"""
import re, html, sys, os

CACHE = os.path.join(os.path.dirname(__file__), "..", "data", "cache")
KEYWORDS = ["dedicated","therapeut","trial","study","studies","enroll","recruit",
            "patient","since 19","since 20","years","FDA","phase","oncology","dermatolog",
            "psychiatr","neurolog","memory","alzheim","diabet","vaccine","weight","liver",
            "award","network","locations","founded","mission","claims","panelist"]

def clean(raw):
    t = re.sub(r"<(script|style)[^>]*>.*?</\1>", " ", raw, flags=re.I|re.S)
    t = re.sub(r"<[^>]+>", " ", t)
    return re.sub(r"\s+", " ", html.unescape(t)).strip()

def report(domain):
    f = os.path.join(CACHE, domain + ".html")
    print(f"\n===== {domain} =====")
    if not os.path.exists(f):
        print("  NOT CACHED"); return
    raw = open(f, encoding="utf-8", errors="ignore").read()
    title = re.search(r"<title[^>]*>(.*?)</title>", raw, re.I|re.S)
    desc = re.search(r'<meta[^>]+name=["\']description["\'][^>]+content=["\'](.*?)["\']', raw, re.I)
    print("TITLE:", title.group(1).strip()[:200] if title else "—")
    print("META :", html.unescape(desc.group(1).strip())[:300] if desc else "—")
    t = clean(raw)
    print(f"TEXT ({len(t)} chars), first 1800:\n{t[:1800]}")
    print("HOOKS:")
    seen=set()
    for kw in KEYWORDS:
        m = re.search(r".{60}"+re.escape(kw)+r".{110}", t, re.I)
        if m and kw not in seen:
            seen.add(kw); print(f"  [{kw}] …{m.group(0).strip()}…")

if __name__ == "__main__":
    for d in sys.argv[1:]:
        report(d.strip().lower().lstrip("www."))
