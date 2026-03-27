"""
fetch_attachments.py — Download (or synthesize) dataset files for Excel assignments.

Strategy:
  1. Try Canvas API to find and download attached files.
  2. If unavailable (403, no attachments), generate realistic synthetic data
     from known schemas described in the assignment instructions.

Writes files to: .tmp/attachments_{course_id}_{assignment_id}/

Usage:
  python tools/fetch_attachments.py --course-id 67723 --assignment-id 904598
"""

import argparse
import json
import os
import random
import sys

import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient

# ── Synthetic data schemas ─────────────────────────────────────────────────────
# Keyed by a tuple of keywords found in the assignment description.
# Each entry: {"filename": str, "generator": callable() -> list[dict]}

random.seed(42)


def _home_sales_data(n=75):
    """Realistic Orange County home sales dataset."""
    cities = [
        "Anaheim", "Irvine", "Santa Ana", "Huntington Beach", "Garden Grove",
        "Orange", "Fullerton", "Costa Mesa", "Mission Viejo", "Lake Forest"
    ]
    home_types = ["Detached", "Condo"]
    rows = []
    for _ in range(n):
        home_type  = random.choice(home_types)
        sqft       = random.randint(850, 3800) if home_type == "Detached" else random.randint(600, 1800)
        age        = random.randint(1, 55)
        base_price = sqft * random.uniform(380, 650)
        # Older homes slightly cheaper, condos slightly cheaper per sqft
        if home_type == "Condo":
            base_price *= 0.82
        if age > 30:
            base_price *= 0.93
        price      = round(base_price / 1000) * 1000
        sd_rating  = round(random.uniform(4.0, 9.5), 1)
        city       = random.choice(cities)
        # Irvine premium
        if city == "Irvine":
            price = int(price * 1.18)
        rows.append({
            "City":                  city,
            "Selling Price":         price,
            "Size (SqFt)":           sqft,
            "Age (Years)":           age,
            "Home Type":             home_type,
            "School District Rating": sd_rating,
        })
    return rows


def _churn_data(n=200):
    """GlobalConnect customer churn dataset."""
    contract_types = ["Month-to-month", "One year", "Two year"]
    rows = []
    for _ in range(n):
        contract      = random.choice(contract_types)
        tenure        = {
            "Month-to-month": random.randint(1, 24),
            "One year":       random.randint(6, 48),
            "Two year":       random.randint(12, 72),
        }[contract]
        monthly       = round(random.uniform(20, 110), 2)
        tech_support  = random.choice(["Yes", "No"])
        # Churn probability: higher for month-to-month, no tech support, short tenure
        churn_prob = 0.05
        if contract == "Month-to-month":
            churn_prob += 0.25
        if tech_support == "No":
            churn_prob += 0.15
        if tenure < 6:
            churn_prob += 0.20
        if monthly > 80:
            churn_prob += 0.10
        churn = "Yes" if random.random() < churn_prob else "No"
        rows.append({
            "Tenure":          tenure,
            "Monthly Charges": monthly,
            "TechSupport":     tech_support,
            "Contract Type":   contract,
            "Churn":           churn,
        })
    return rows


# Map: (assignment_id, fallback keywords in description) → dataset spec
_SYNTHETIC_DATASETS = {
    "home_sales": {
        "filename":    "Home_Sales_Data.csv",
        "description": "Orange County home sales data (City, Selling Price, Size SqFt, Age Years, Home Type, School District Rating)",
        "generator":   _home_sales_data,
    },
    "churn": {
        "filename":    "GlobalConnect_Churn_Data.csv",
        "description": "GlobalConnect customer churn data (Tenure, Monthly Charges, TechSupport, Contract Type, Churn)",
        "generator":   _churn_data,
    },
}

# Assignment ID → which synthetic dataset to use
_ASSIGNMENT_DATASET_MAP = {
    904598: "home_sales",   # Data analysis basics in Excel
    904597: "home_sales",   # Charts and tables
    904599: "churn",        # Predictive analysis
}


def fetch_attachments(course_id: int, assignment_id: int) -> list[str]:
    """
    Download or synthesize dataset files for an assignment.
    Returns list of local file paths.
    """
    out_dir = f".tmp/attachments_{course_id}_{assignment_id}"
    os.makedirs(out_dir, exist_ok=True)

    downloaded = _try_canvas_download(course_id, assignment_id, out_dir)
    if downloaded:
        print(f"[fetch_attachments] Downloaded {len(downloaded)} file(s) from Canvas.")
        return downloaded

    # Fall back to synthetic data
    return _synthesize(assignment_id, out_dir)


def _try_canvas_download(course_id: int, assignment_id: int, out_dir: str) -> list[str]:
    """Attempt to download files from Canvas. Returns paths or empty list."""
    try:
        client = CanvasClient()
        # Load cached assignment to check for attachment metadata
        assignments_path = f".tmp/assignments_{course_id}.json"
        if not os.path.exists(assignments_path):
            return []
        with open(assignments_path) as f:
            assignments = json.load(f)
        assignment = next((a for a in assignments if a["id"] == assignment_id), None)
        if not assignment:
            return []

        attachments = assignment.get("attachments") or []

        # Some Canvas instances embed file URLs in the API response
        if not attachments:
            # Try fetching full assignment with attachments include
            try:
                full = client.get(
                    f"/courses/{course_id}/assignments/{assignment_id}",
                    params={"include[]": "attachments"},
                )
                attachments = full.get("attachments") or []
            except Exception:
                pass

        if not attachments:
            return []

        token = os.getenv("CANVAS_TOKEN", "")
        downloaded = []
        for att in attachments:
            url      = att.get("url") or att.get("download_url")
            filename = att.get("filename") or att.get("display_name", f"attachment_{att.get('id', '')}")
            if not url:
                continue
            resp = requests.get(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
            if resp.ok:
                path = os.path.join(out_dir, filename)
                with open(path, "wb") as fh:
                    fh.write(resp.content)
                downloaded.append(path)
                print(f"[fetch_attachments] Downloaded: {filename}")
        return downloaded

    except Exception as exc:
        print(f"[fetch_attachments] Canvas download skipped: {exc}")
        return []


def _synthesize(assignment_id: int, out_dir: str) -> list[str]:
    """Generate a synthetic dataset CSV for the given assignment."""
    import csv

    dataset_key = _ASSIGNMENT_DATASET_MAP.get(assignment_id)
    if not dataset_key:
        print(f"[fetch_attachments] No synthetic dataset configured for assignment {assignment_id}.")
        return []

    spec = _SYNTHETIC_DATASETS[dataset_key]
    filename = spec["filename"]
    out_path = os.path.join(out_dir, filename)

    if os.path.exists(out_path):
        print(f"[fetch_attachments] Synthetic dataset already exists: {out_path}")
        return [out_path]

    rows = spec["generator"]()
    if not rows:
        return []

    with open(out_path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        writer.writeheader()
        writer.writerows(rows)

    print(f"[fetch_attachments] Synthesized {len(rows)} rows → {out_path}")
    print(f"[fetch_attachments] Dataset: {spec['description']}")
    return [out_path]


def get_dataset_path(course_id: int, assignment_id: int) -> str | None:
    """Return the path to the dataset file for this assignment (or None)."""
    out_dir = f".tmp/attachments_{course_id}_{assignment_id}"
    if not os.path.exists(out_dir):
        return None
    files = [f for f in os.listdir(out_dir) if not f.startswith(".")]
    if not files:
        return None
    return os.path.join(out_dir, files[0])


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch or synthesize assignment datasets")
    parser.add_argument("--course-id",     type=int, required=True)
    parser.add_argument("--assignment-id", type=int, required=True)
    args = parser.parse_args()
    paths = fetch_attachments(args.course_id, args.assignment_id)
    print(f"Ready: {paths}")
