"""
fetch_quizzes.py — Fetch all quizzes and their questions for a course.

Flags lockdown browser quizzes (must be skipped).
Flags one_question_at_a_time quizzes (require sequential submission).
Writes: .tmp/quizzes_<course_id>.json

Usage: python tools/fetch_quizzes.py --course-id 12345
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient


def fetch_quizzes(course_id):
    client = CanvasClient()
    os.makedirs(".tmp", exist_ok=True)

    print(f"[fetch_quizzes] Fetching quizzes for course {course_id}...")
    raw = client.get_all(f"/courses/{course_id}/quizzes")

    quizzes = []
    for q in raw:
        quiz_id = q["id"]

        if q.get("require_lockdown_browser"):
            print(f"  [SKIP] Quiz {quiz_id} '{q.get('title')}' requires Lockdown Browser — skipping")
            continue

        # Fetch questions
        try:
            questions_raw = client.get_all(f"/courses/{course_id}/quizzes/{quiz_id}/questions")
        except Exception as e:
            print(f"  [WARN] Could not fetch questions for quiz {quiz_id}: {e}")
            questions_raw = []

        questions = []
        for qn in questions_raw:
            answers = [
                {"id": a.get("id"), "text": a.get("text", ""), "weight": a.get("weight", 0)}
                for a in qn.get("answers", [])
            ]
            questions.append({
                "id": qn["id"],
                "question_name": qn.get("question_name", ""),
                "question_text": qn.get("question_text", ""),
                "question_type": qn.get("question_type", ""),
                "points_possible": qn.get("points_possible", 0),
                "answers": answers,
            })

        quizzes.append({
            "id": quiz_id,
            "title": q.get("title", ""),
            "description": q.get("description", ""),
            "quiz_type": q.get("quiz_type", ""),
            "time_limit": q.get("time_limit"),  # minutes, or None
            "allowed_attempts": q.get("allowed_attempts", 1),
            "one_question_at_a_time": q.get("one_question_at_a_time", False),
            "require_lockdown_browser": q.get("require_lockdown_browser", False),
            "points_possible": q.get("points_possible", 0),
            "questions": questions,
        })

    out_path = f".tmp/quizzes_{course_id}.json"
    with open(out_path, "w") as f:
        json.dump(quizzes, f, indent=2)

    print(f"[fetch_quizzes] {len(quizzes)} quiz(zes) fetched → {out_path}")
    for q in quizzes:
        flags = []
        if q["one_question_at_a_time"]:
            flags.append("sequential")
        if q["time_limit"]:
            flags.append(f"{q['time_limit']}min")
        print(f"  {q['id']:>8}  {len(q['questions'])} Qs  {', '.join(flags) or 'standard'}  {q['title']}")

    return quizzes


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Fetch Canvas quizzes")
    parser.add_argument("--course-id", type=int, required=True)
    args = parser.parse_args()
    fetch_quizzes(args.course_id)
