import os, requests
from dotenv import load_dotenv
load_dotenv()
key = os.environ.get("GOOGLE_PLACES_API_KEY")
tests = [
    "8200 South Saginaw Street, Grand Blanc, MI 48439",
    "310 Arthur Godfrey Road, Miami Beach, FL 33140",
    "19701 Kingwood Drive, Kingwood, TX 77339",
    "595 Chapel Hills Drive, Colorado Springs, CO 80920",
    "170 Dr. Arla Way, Suite 101, New York, NY",   # known hallucinated fake
]
for a in tests:
    r = requests.get("https://maps.googleapis.com/maps/api/geocode/json",
                     params={"address": a, "key": key}, timeout=20).json()
    st = r.get("status")
    if st == "OK":
        res = r["results"][0]
        print(f"  OK   {a[:46]:46} -> {res['geometry']['location_type']:20} partial={res.get('partial_match', False)}")
    else:
        print(f"  {st:14} {a[:46]} | {r.get('error_message', '')[:70]}")
