"""
fetch_courses.py — Fetch all active Canvas courses for the authenticated user.

Writes: .tmp/courses.json
Usage:  python tools/fetch_courses.py [--course-id 12345]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient


def fetch_courses(course_id=None):
    client = CanvasClient()

    # Check for BENCHMARK_COURSE_IDS env var (set by web UI)
    course_ids_env = os.getenv("BENCHMARK_COURSE_IDS", "all").strip()
    if course_ids_env and course_ids_env != "all" and not course_id:
        # Parse comma-separated IDs from env
        try:
            target_ids = [int(cid.strip()) for cid in course_ids_env.split(",") if cid.strip()]
        except ValueError:
            target_ids = []
    else:
        target_ids = []

    if course_id:
        course = client.get(f"/courses/{course_id}", params={"include[]": "term"})
        courses = [course]
    elif target_ids:
        # Fetch only specified courses
        courses = []
        for cid in target_ids:
            try:
                course = client.get(f"/courses/{cid}", params={"include[]": "term"})
                courses.append(course)
            except Exception as e:
                print(f"[fetch_courses] Warning: Could not fetch course {cid}: {e}")
    else:
        courses = client.get_all(
            "/courses",
            params={"enrollment_state": "active", "include[]": "term"},
        )

    active = [
        {
            "id": c["id"],
            "name": c.get("name", ""),
            "course_code": c.get("course_code", ""),
            "term": c.get("term", {}).get("name", "") if c.get("term") else "",
            "workflow_state": c.get("workflow_state", ""),
        }
        for c in courses
        if c.get("workflow_state") in ("available", "unpublished", None)
        or course_id
        or target_ids
    ]

    os.makedirs(".tmp", exist_ok=True)
    with open(".tmp/courses.json", "w") as f:
        json.dump(active, f, indent=2)

    print(f"[fetch_courses] Found {len(active)} course(s):")
    for c in active:
        print(f"  {c['id']:>8}  {c['course_code']:<20}  {c['name']}")

    return active


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Canvas courses")
    parser.add_argument("--course-id", type=int, help="Fetch a single course by ID")
    args = parser.parse_args()
    fetch_courses(course_id=args.course_id)
