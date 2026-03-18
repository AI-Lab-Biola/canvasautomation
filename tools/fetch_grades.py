"""
fetch_grades.py — Poll Canvas for grades on submitted assignments.

Runs as a separate deferred step — grades may not be available immediately.
Auto-graded quizzes: available within minutes.
Essay/text assignments: may take hours or days (instructor must grade).

Polls until all records are graded or GRADE_POLL_MAX_HOURS is reached.

Usage: python tools/fetch_grades.py --run-id <run_id> [--once]
  --once: Check grades a single time without polling loop
"""

import argparse
import os
import sys
import time
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient
from tools.benchmark_logger import load_run, update_grade

from dotenv import load_dotenv
load_dotenv()


def fetch_grades(run_id, once=False):
    client = CanvasClient()
    poll_interval = int(os.getenv("GRADE_POLL_INTERVAL_SECONDS", "3600"))
    max_hours = int(os.getenv("GRADE_POLL_MAX_HOURS", "48"))
    max_seconds = max_hours * 3600
    start_time = time.monotonic()

    print(f"[fetch_grades] Starting grade polling for run {run_id}")
    print(f"  Interval: {poll_interval}s | Max wait: {max_hours}h")

    while True:
        records = load_run(run_id)
        ungraded = [
            r for r in records
            if r.get("score") is None
            and r.get("submission_id") is not None
            and not r.get("error")
        ]

        if not ungraded:
            print(f"[fetch_grades] All submissions graded!")
            break

        print(f"[fetch_grades] Checking {len(ungraded)} ungraded submission(s)...")

        for r in ungraded:
            course_id = r["course_id"]
            assignment_id = r["assignment_id"]

            # Handle quiz submissions (assignment_id is "quiz_<id>")
            if str(assignment_id).startswith("quiz_"):
                quiz_id = str(assignment_id).replace("quiz_", "")
                _check_quiz_grade(client, run_id, course_id, quiz_id, assignment_id)
            else:
                _check_assignment_grade(client, run_id, course_id, assignment_id)

        if once:
            break

        elapsed = time.monotonic() - start_time
        if elapsed >= max_seconds:
            remaining = [r for r in load_run(run_id) if r.get("score") is None and not r.get("error")]
            if remaining:
                print(f"[fetch_grades] Max wait ({max_hours}h) reached. {len(remaining)} assignment(s) still ungraded.")
            break

        print(f"[fetch_grades] Waiting {poll_interval}s before next check...")
        time.sleep(poll_interval)

    from tools.benchmark_logger import print_run_summary
    print_run_summary(run_id)


def _check_assignment_grade(client, run_id, course_id, assignment_id):
    try:
        sub = client.get(
            f"/courses/{course_id}/assignments/{assignment_id}/submissions/self",
            params={"include[]": "submission_comments"},
        )
        if sub.get("workflow_state") == "graded" and sub.get("score") is not None:
            grade = sub.get("grade")
            score = sub.get("score")
            update_grade(run_id, assignment_id, grade, score)
        else:
            state = sub.get("workflow_state", "unknown")
            print(f"  assignment {assignment_id}: not yet graded (state={state})")
    except Exception as e:
        print(f"  assignment {assignment_id}: error fetching grade — {e}")


def _check_quiz_grade(client, run_id, course_id, quiz_id, assignment_id):
    try:
        result = client.get(
            f"/courses/{course_id}/quizzes/{quiz_id}/submissions",
            params={"include[]": "quiz_submissions"},
        )
        subs = result.get("quiz_submissions", [])
        graded = [s for s in subs if s.get("workflow_state") == "complete" and s.get("score") is not None]
        if graded:
            latest = max(graded, key=lambda s: s.get("attempt", 0))
            score = latest.get("score")
            kept_score = latest.get("kept_score", score)
            grade = str(kept_score)
            update_grade(run_id, assignment_id, grade, kept_score)
        else:
            print(f"  quiz {quiz_id}: not yet graded")
    except Exception as e:
        print(f"  quiz {quiz_id}: error fetching grade — {e}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Poll Canvas for grades")
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--once", action="store_true", help="Check once without polling loop")
    args = parser.parse_args()
    fetch_grades(args.run_id, once=args.once)
