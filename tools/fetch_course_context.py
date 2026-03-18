"""
fetch_course_context.py — Fetch syllabus, pages, and modules for a course.

Strips HTML to plain text. Truncates syllabus to SYLLABUS_CHAR_LIMIT characters.
Writes: .tmp/context_<course_id>.json

Usage: python tools/fetch_course_context.py --course-id 12345
"""

import argparse
import json
import os
import sys

from bs4 import BeautifulSoup

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient

SYLLABUS_CHAR_LIMIT = 4000
PAGE_BODY_CHAR_LIMIT = 1000  # per page, to avoid overflow


def strip_html(html_str):
    if not html_str:
        return ""
    return BeautifulSoup(html_str, "lxml").get_text(separator="\n", strip=True)


def fetch_course_context(course_id):
    client = CanvasClient()
    os.makedirs(".tmp", exist_ok=True)

    # Syllabus
    print(f"[fetch_course_context] Fetching syllabus for course {course_id}...")
    course_data = client.get(
        f"/courses/{course_id}",
        params={"include[]": "syllabus_body"},
    )
    syllabus_raw = course_data.get("syllabus_body") or ""
    syllabus_text = strip_html(syllabus_raw)[:SYLLABUS_CHAR_LIMIT]

    # Pages
    print(f"[fetch_course_context] Fetching pages...")
    pages_raw = client.get_all(f"/courses/{course_id}/pages")
    pages = []
    for p in pages_raw:
        page_detail = client.get(f"/courses/{course_id}/pages/{p['url']}")
        body_text = strip_html(page_detail.get("body") or "")[:PAGE_BODY_CHAR_LIMIT]
        pages.append({
            "title": p.get("title", ""),
            "url": p.get("url", ""),
            "body": body_text,
        })

    # Modules
    print(f"[fetch_course_context] Fetching modules...")
    modules_raw = client.get_all(
        f"/courses/{course_id}/modules",
        params={"include[]": "items"},
    )
    modules = [
        {
            "id": m["id"],
            "name": m.get("name", ""),
            "items": [
                {"title": i.get("title", ""), "type": i.get("type", "")}
                for i in m.get("items", [])
            ],
        }
        for m in modules_raw
    ]

    context = {
        "course_id": course_id,
        "course_name": course_data.get("name", ""),
        "syllabus_text": syllabus_text,
        "pages": pages,
        "modules": modules,
    }

    out_path = f".tmp/context_{course_id}.json"
    with open(out_path, "w") as f:
        json.dump(context, f, indent=2)

    print(f"[fetch_course_context] Written to {out_path}")
    print(f"  Syllabus: {len(syllabus_text)} chars | Pages: {len(pages)} | Modules: {len(modules)}")
    return context


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Canvas course context")
    parser.add_argument("--course-id", type=int, required=True)
    args = parser.parse_args()
    fetch_course_context(args.course_id)
