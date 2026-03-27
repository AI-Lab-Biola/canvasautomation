"""
fetch_assignments.py — Fetch all assignments and their rubrics for a course.

Skips assignments that are locked. Already-submitted assignments are included to allow resubmission.
Writes: .tmp/assignments_<course_id>.json

Usage: python tools/fetch_assignments.py --course-id 12345
"""

import argparse
import json
import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient


def strip_html(html_str):
    if not html_str:
        return ""
    return BeautifulSoup(html_str, "lxml").get_text(separator="\n", strip=True)


def fetch_assignments(course_id):
    client = CanvasClient()
    os.makedirs(".tmp", exist_ok=True)

    print(f"[fetch_assignments] Fetching assignments for course {course_id}...")
    raw = client.get_all(
        f"/courses/{course_id}/assignments",
        params={"include[]": ["submission", "rubric_criteria"]},
    )

    assignments = []
    skipped = 0

    for a in raw:
        # Skip locked assignments
        if a.get("locked_for_user") or a.get("lock_at") and a.get("is_locked"):
            skipped += 1
            continue

        # Fetch rubric separately if not included
        rubric = a.get("rubric") or []
        if not rubric:
            try:
                rubric_data = client.get(f"/courses/{course_id}/assignments/{a['id']}/rubric")
                rubric = rubric_data if isinstance(rubric_data, list) else []
            except Exception:
                rubric = []

        # Parse rubric criteria
        rubric_criteria = [
            {
                "description": r.get("description", ""),
                "long_description": r.get("long_description", ""),
                "points": r.get("points", 0),
            }
            for r in rubric
        ]

        assignments.append({
            "id": a["id"],
            "name": a.get("name", ""),
            "description": strip_html(a.get("description") or ""),
            "submission_types": a.get("submission_types", []),
            "due_at": a.get("due_at"),
            "points_possible": a.get("points_possible", 0),
            "rubric": rubric_criteria,
            "discussion_topic": a.get("discussion_topic"),
            "quiz_id": a.get("quiz_id"),
            "workflow_state": a.get("workflow_state"),
        })

    out_path = f".tmp/assignments_{course_id}.json"
    with open(out_path, "w") as f:
        json.dump(assignments, f, indent=2)

    print(f"[fetch_assignments] {len(assignments)} assignments fetched, {skipped} skipped → {out_path}")
    for a in assignments:
        types = ", ".join(a["submission_types"])
        print(f"  {a['id']:>8}  {types:<25}  {a['name']}")

    return assignments


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Canvas assignments")
    parser.add_argument("--course-id", type=int, required=True)
    args = parser.parse_args()
    fetch_assignments(args.course_id)
