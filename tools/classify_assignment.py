"""
classify_assignment.py — Categorize each assignment before the pipeline runs.

Categories:
  skip              — DataCamp / submission_type=none; tracked externally, nothing to submit
  needs_human       — requires login to external site, screenshot, physical meeting, or real URL
  automatable_excel — needs a generated .xlsx workbook (+ written reflection)
  automatable_text  — discussion posts, text entries, reflections (current default behaviour)

Usage (as module):
  from tools.classify_assignment import classify, CATEGORIES

Usage (CLI):
  python tools/classify_assignment.py --assignments-file .tmp/assignments_67723.json
"""

import json
import argparse
import sys
import os

# Public category constants
SKIP             = "skip"
NEEDS_HUMAN      = "needs_human"
AUTOMATABLE_EXCEL = "automatable_excel"
AUTOMATABLE_TEXT  = "automatable_text"

CATEGORIES = (SKIP, NEEDS_HUMAN, AUTOMATABLE_EXCEL, AUTOMATABLE_TEXT)


# Keywords that reliably signal "nothing to submit to Canvas"
_SKIP_NAME_KW = ("datacamp",)

# Keywords that reliably signal human-only action
_HUMAN_NAME_KW = (
    "mentor",              # "Discussion with Mentor"
    "directed learning",   # all directed-learning quizzes need NotebookLM login + screenshot
    "notebooklm for your", # "Project: NotebookLM for your project" — needs a real NLM URL
)

# Description signals for Excel workbook assignments
# Must signal that the *deliverable* is an Excel file, not just a reference to one
_EXCEL_DESC_KW = (
    "excel workbook (.xlsx)",          # explicit deliverable phrase
    "single excel workbook",           # "A single Excel workbook..."
    "excel workbook containing",       # "...workbook containing separate tabs"
)
_EXCEL_NAME_KW = ("charts and tables",)  # this assignment explicitly builds chart deliverables


def classify(assignment: dict) -> tuple[str, str]:
    """
    Classify a single assignment dict.
    Returns (category, reason) where category is one of the CATEGORIES constants.
    """
    sub_types = assignment.get("submission_types") or []
    name      = (assignment.get("name") or "").lower()
    desc      = (assignment.get("description") or "").lower()

    # ── 1. Skip: nothing to submit on Canvas ──────────────────────────────────
    if sub_types == ["none"]:
        return SKIP, "submission_type=none (tracked externally, e.g. DataCamp)"

    if any(kw in name for kw in _SKIP_NAME_KW):
        return SKIP, f"assignment name contains '{next(kw for kw in _SKIP_NAME_KW if kw in name)}'"

    # ── 2. Needs human: external platform / screenshot / physical meeting ──────
    if any(kw in name for kw in _HUMAN_NAME_KW):
        matched = next(kw for kw in _HUMAN_NAME_KW if kw in name)
        return NEEDS_HUMAN, f"assignment name contains '{matched}' — requires human action"

    # Check description for screenshot signal
    if "screenshot" in desc:
        return NEEDS_HUMAN, "description mentions screenshot — requires human to capture"

    # ── 3. Excel: generate a real .xlsx workbook ───────────────────────────────
    if any(kw in desc for kw in _EXCEL_DESC_KW):
        return AUTOMATABLE_EXCEL, "description requires .xlsx workbook"

    if any(kw in name for kw in _EXCEL_NAME_KW):
        return AUTOMATABLE_EXCEL, f"assignment name signals Excel/chart work"

    # ── 4. Default: text-based (discussion, text entry, doc upload) ───────────
    return AUTOMATABLE_TEXT, "standard text / discussion submission"


def classify_all(assignments: list[dict]) -> list[dict]:
    """Classify a list of assignments and return enriched dicts."""
    results = []
    for a in assignments:
        cat, reason = classify(a)
        results.append({
            "id":       a["id"],
            "name":     a.get("name", ""),
            "category": cat,
            "reason":   reason,
            "submission_types": a.get("submission_types") or [],
        })
    return results


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Classify Canvas assignments")
    parser.add_argument("--assignments-file", required=True)
    args = parser.parse_args()

    with open(args.assignments_file) as f:
        assignments = json.load(f)

    results = classify_all(assignments)

    # Group by category for a clean summary
    from collections import defaultdict
    groups = defaultdict(list)
    for r in results:
        groups[r["category"]].append(r)

    for cat in CATEGORIES:
        items = groups.get(cat, [])
        print(f"\n{'─'*60}")
        print(f"  {cat.upper()}  ({len(items)} assignment(s))")
        print(f"{'─'*60}")
        for r in items:
            print(f"  [{r['id']}] {r['name']}")
            print(f"        → {r['reason']}")
