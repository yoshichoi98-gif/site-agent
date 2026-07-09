"""
scripts/sync_to_sheets.py

Syncs output_orgs.csv, output_orgs_research.csv, and output_locations.csv
to a single Google Sheet with one tab per CSV.

Usage:
    python -m scripts.sync_to_sheets
"""
import csv
import logging
import os
import sys
import time

import gspread
from google.oauth2.service_account import Credentials

logger = logging.getLogger(__name__)

SPREADSHEET_ID  = "13KzQocrzrmH6ifieZ2McanyURfNIqBb4UMEASAl8d-4"
CREDENTIALS_PATH = os.path.join(os.path.dirname(__file__), "..", "credentials", "google_service_account.json")
DATA = os.path.join(os.path.dirname(__file__), "..", "data")

SHEETS = [
    ("orgs",          os.path.join(DATA, "output_orgs.csv")),
    ("orgs_research", os.path.join(DATA, "output_orgs_research.csv")),
    ("locations",     os.path.join(DATA, "output_locations.csv")),
    ("deleted_rows",  os.path.join(DATA, "deleted_rows_audit.csv")),
]

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Sheets API has a 10MB request limit — batch writes in chunks
BATCH_SIZE = 1000


def load_csv(path: str) -> tuple[list[str], list[list]]:
    with open(path, newline='', encoding='utf-8') as f:
        reader = csv.reader(f)
        rows = list(reader)
    if not rows:
        return [], []
    return rows[0], rows[1:]


def sync_sheet(ws: gspread.Worksheet, headers: list, rows: list):
    """Clear the sheet and write all data in batches."""
    ws.clear()
    time.sleep(1)  # avoid rate limit after clear

    all_data = [headers] + rows
    total = len(all_data)

    for i in range(0, total, BATCH_SIZE):
        batch = all_data[i:i + BATCH_SIZE]
        # gspread row index is 1-based
        start_row = i + 1
        end_row   = start_row + len(batch) - 1
        end_col   = len(headers)
        range_notation = f"A{start_row}:{_col_letter(end_col)}{end_row}"

        ws.update(range_notation, batch, value_input_option="RAW")
        logger.info(f"  wrote rows {start_row}–{end_row} ({len(batch)} rows)")
        time.sleep(0.5)  # stay under 60 req/min quota


def _col_letter(n: int) -> str:
    """Convert column number (1-based) to letter (A, B, ... Z, AA, ...)."""
    result = ""
    while n:
        n, remainder = divmod(n - 1, 26)
        result = chr(65 + remainder) + result
    return result


def main():
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s: %(message)s",
        stream=sys.stderr,
    )

    creds = Credentials.from_service_account_file(CREDENTIALS_PATH, scopes=SCOPES)
    gc    = gspread.authorize(creds)
    spreadsheet = gc.open_by_key(SPREADSHEET_ID)

    existing_titles = {ws.title for ws in spreadsheet.worksheets()}

    for tab_name, csv_path in SHEETS:
        logger.info(f"Syncing {tab_name} ← {os.path.basename(csv_path)}")
        headers, rows = load_csv(csv_path)

        if not headers:
            logger.warning(f"  {csv_path} is empty — skipping")
            continue

        # Get or create worksheet
        if tab_name in existing_titles:
            ws = spreadsheet.worksheet(tab_name)
        else:
            ws = spreadsheet.add_worksheet(title=tab_name, rows=len(rows)+10, cols=len(headers))
            existing_titles.add(tab_name)

        sync_sheet(ws, headers, rows)
        logger.info(f"  {tab_name}: {len(rows)} data rows, {len(headers)} columns — done")

    logger.info("All sheets synced.")
    print(f"\nhttps://docs.google.com/spreadsheets/d/{SPREADSHEET_ID}")


if __name__ == "__main__":
    main()
