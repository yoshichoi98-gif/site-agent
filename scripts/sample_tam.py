"""
sample_tam.py — generate pipeline input from TAM_v4.csv

POLICY: NO filtering on any status column.
  - Do NOT filter on "Final Domain Good?"
  - Do NOT filter on "Final Domain Status"
  - Do NOT filter on "Organization Type"
  - Do NOT filter on "Organization Subcategory"
  - Do NOT filter on "Good to Go"
  - Do NOT filter on any other status or classification column

The pipeline itself handles blocked/parked/DNS-failure domains gracefully.
Filtering here would silently drop domains that may be valid targets.
The only eligibility criterion is: the row has a non-empty "Final Domain".

Usage:
  # Full TAM (all unique domains)
  python scripts/sample_tam.py --tam data/TAM_v4.csv --all --output data/full_tam_run.csv

  # Random sample of N domains (for smoke tests / validation batches)
  python scripts/sample_tam.py --tam data/TAM_v4.csv --n 100 --seed 42 --output data/sample.csv
"""
import argparse
import csv
import random
import sys


def load_unique_domains(tam_path: str) -> list[tuple[str, str]]:
    """Return list of (domain, source_row_id) for every unique non-empty Final Domain."""
    seen: set[str] = set()
    rows: list[tuple[str, str]] = []
    with open(tam_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            domain = (row.get("Final Domain") or "").strip().lower()
            if not domain or domain in seen:
                continue
            seen.add(domain)
            rows.append((domain, row.get("Imported Row ID", "")))
    return rows


def main():
    parser = argparse.ArgumentParser(description="Generate pipeline input from TAM CSV")
    parser.add_argument("--tam", required=True, help="Path to TAM_v4.csv")
    parser.add_argument("--output", required=True, help="Output CSV path")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Include all unique domains")
    group.add_argument("--n", type=int, help="Random sample of N domains")
    parser.add_argument("--seed", type=int, default=42, help="Random seed (default 42)")
    args = parser.parse_args()

    rows = load_unique_domains(args.tam)

    if args.all:
        selected = rows
    else:
        rng = random.Random(args.seed)
        selected = rng.sample(rows, min(args.n, len(rows)))

    with open(args.output, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "source_row_id"])
        writer.writeheader()
        for domain, row_id in selected:
            writer.writerow({"domain": domain, "source_row_id": row_id})

    print(f"Wrote {len(selected)} domains to {args.output}", file=sys.stderr)


if __name__ == "__main__":
    main()
