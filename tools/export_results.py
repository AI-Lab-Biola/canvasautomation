"""
export_results.py — Export benchmark results to CSV and/or Google Sheets.

Reads:   .tmp/benchmark_<run_id>.jsonl
Outputs: .tmp/benchmark_results_<run_id>.csv
         Appends rows to Google Sheet (if BENCHMARK_SHEET_ID is set)

Usage: python tools/export_results.py --run-id <run_id> [--format csv|sheets|both]
"""

import argparse
import csv
import json
import os
import sys
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.benchmark_logger import load_run, print_run_summary

from dotenv import load_dotenv
load_dotenv()

COLUMNS = [
    "run_id", "course_id", "course_name", "assignment_id", "assignment_name",
    "assignment_type", "model", "prompt_tokens", "completion_tokens", "latency_ms",
    "submitted_at", "submission_id", "grade", "score", "max_points",
    "score_pct", "error", "logged_at",
]


def compute_score_pct(record):
    score = record.get("score")
    max_pts = record.get("max_points") or 0
    if score is not None and max_pts > 0:
        return round(score / max_pts * 100, 2)
    return None


def export_csv(run_id):
    records = load_run(run_id)
    if not records:
        print(f"[export_results] No records found for run {run_id}")
        return None

    for r in records:
        r["score_pct"] = compute_score_pct(r)

    os.makedirs(".tmp", exist_ok=True)
    out_path = f".tmp/benchmark_results_{run_id}.csv"

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(records)

    print(f"[export_results] CSV written → {out_path} ({len(records)} rows)")
    return out_path


def export_sheets(run_id):
    sheet_id = os.getenv("BENCHMARK_SHEET_ID")
    if not sheet_id:
        print("[export_results] BENCHMARK_SHEET_ID not set — skipping Sheets export")
        return

    try:
        import gspread
        from google.oauth2.service_account import Credentials
    except ImportError:
        print("[export_results] gspread/google-auth not installed. Run: pip install gspread google-auth")
        return

    creds_path = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "credentials.json")
    if not os.path.exists(creds_path):
        print(f"[export_results] Google credentials not found at {creds_path}")
        return

    records = load_run(run_id)
    if not records:
        print(f"[export_results] No records to export for run {run_id}")
        return

    for r in records:
        r["score_pct"] = compute_score_pct(r)

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_file(creds_path, scopes=scopes)
    gc = gspread.authorize(creds)

    try:
        sh = gc.open_by_key(sheet_id)
        worksheet = sh.sheet1
    except Exception as e:
        print(f"[export_results] Could not open sheet {sheet_id}: {e}")
        return

    # Check if headers exist; add if sheet is empty
    existing = worksheet.get_all_values()
    if not existing:
        worksheet.append_row(COLUMNS)

    rows = [
        [str(r.get(col, "") or "") for col in COLUMNS]
        for r in records
    ]
    worksheet.append_rows(rows)
    print(f"[export_results] {len(rows)} rows appended to Google Sheet {sheet_id}")


def export_results(run_id, fmt="both"):
    print_run_summary(run_id)

    if fmt in ("csv", "both"):
        export_csv(run_id)

    if fmt in ("sheets", "both"):
        export_sheets(run_id)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Export benchmark results")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--format", choices=["csv", "sheets", "both"], default="csv")
    args = parser.parse_args()
    export_results(args.run_id, fmt=args.format)
