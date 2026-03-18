"""
submit_quiz.py — Stateful Canvas quiz submission.

CRITICAL: LLM response must be generated BEFORE starting the quiz session.
          Starting a session starts the timer. Never start speculatively.

Flow:
  1. Check remaining attempts
  2. POST to start quiz session → get quiz_submission_id + validation_token
  3a. Standard quiz: PUT all answers at once
  3b. one_question_at_a_time: synchronous loop — GET question → PUT answer → advance
  4. POST to complete session with validation_token

Reads:  .tmp/responses_<run_id>/quiz_<quiz_id>.json
        .tmp/quizzes_<course_id>.json
Updates: .tmp/benchmark_<run_id>.jsonl via benchmark_logger

Usage: python tools/submit_quiz.py --course-id 12345 --quiz-id 11111 --run-id <run_id>
"""

import argparse
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient
from tools.benchmark_logger import log_attempt


def submit_quiz(course_id, quiz_id, run_id):
    client = CanvasClient()

    # Load quiz metadata
    quizzes_path = f".tmp/quizzes_{course_id}.json"
    with open(quizzes_path) as f:
        quizzes = json.load(f)
    quiz = next((q for q in quizzes if q["id"] == quiz_id), None)
    if not quiz:
        raise ValueError(f"Quiz {quiz_id} not found in {quizzes_path}")

    # Safety check — lockdown browser (should have been filtered earlier)
    if quiz.get("require_lockdown_browser"):
        error = "lockdown_browser_required — cannot automate this quiz"
        print(f"[submit_quiz] SKIP: {error}")
        log_attempt(run_id, _base_record(course_id, quiz, run_id, error=error))
        return {"error": error}

    # Load LLM response (must exist before starting session)
    response_path = f".tmp/responses_{run_id}/quiz_{quiz_id}.json"
    if not os.path.exists(response_path):
        raise FileNotFoundError(
            f"LLM response not found: {response_path}. Run run_llm.py BEFORE starting quiz session."
        )
    with open(response_path) as f:
        llm_response = json.load(f)

    parsed_answers = llm_response.get("parsed_answers", {})
    if not parsed_answers:
        error = "LLM response contained no parseable answers"
        print(f"[submit_quiz] ERROR: {error}")
        log_attempt(run_id, _base_record(course_id, quiz, run_id, llm_response=llm_response, error=error))
        return {"error": error}

    # Check existing in-progress submission (avoid duplicate sessions)
    try:
        existing = client.get(f"/courses/{course_id}/quizzes/{quiz_id}/submissions",
                              params={"include[]": "quiz_submissions"})
        subs = existing.get("quiz_submissions", [])
        in_progress = [s for s in subs if s.get("workflow_state") == "untaken"]
        if in_progress:
            print(f"[submit_quiz] Found existing in-progress session, resuming...")
            session = in_progress[0]
        else:
            session = _start_session(client, course_id, quiz_id)
    except Exception:
        session = _start_session(client, course_id, quiz_id)

    qs_id = session["id"]
    validation_token = session.get("validation_token", "")
    attempt = session.get("attempt", 1)

    print(f"[submit_quiz] Session started: qs_id={qs_id}, attempt={attempt}")

    error = None
    submission_id = None
    submitted_at = None

    try:
        if quiz.get("one_question_at_a_time"):
            _submit_sequential(client, course_id, quiz_id, qs_id, parsed_answers, quiz["questions"])
        else:
            _submit_bulk(client, course_id, quiz_id, qs_id, parsed_answers, quiz["questions"])

        # Complete the session
        print(f"[submit_quiz] Completing quiz session...")
        complete_result = client.post(
            f"/courses/{course_id}/quizzes/{quiz_id}/submissions/{qs_id}/complete",
            json={
                "attempt": attempt,
                "validation_token": validation_token,
            },
        )
        quiz_sub = (complete_result.get("quiz_submissions") or [{}])[0]
        submission_id = quiz_sub.get("id", qs_id)
        submitted_at = quiz_sub.get("finished_at") or quiz_sub.get("end_at")
        print(f"[submit_quiz] Quiz submitted! submission_id={submission_id}")

    except Exception as e:
        error = str(e)
        print(f"[submit_quiz] ERROR: {error}")

    record = _base_record(course_id, quiz, run_id, llm_response=llm_response, error=error)
    record.update({
        "submission_id": submission_id,
        "submitted_at": submitted_at,
    })
    log_attempt(run_id, record)

    return {"submission_id": submission_id, "submitted_at": submitted_at, "error": error}


def _start_session(client, course_id, quiz_id):
    print(f"[submit_quiz] Starting quiz session...")
    result = client.post(f"/courses/{course_id}/quizzes/{quiz_id}/submissions")
    sessions = result.get("quiz_submissions", [result])
    return sessions[0] if sessions else result


def _submit_bulk(client, course_id, quiz_id, qs_id, parsed_answers, questions):
    """Submit all answers at once for standard quizzes."""
    quiz_questions = []
    for q in questions:
        q_id = q["id"]
        answer = parsed_answers.get(str(q_id)) or parsed_answers.get(q_id)
        if not answer:
            continue
        entry = {"id": q_id}
        if "answer_id" in answer:
            entry["answer"] = answer["answer_id"]
        else:
            entry["answer"] = answer.get("answer_text", "")
        quiz_questions.append(entry)

    print(f"[submit_quiz] Submitting {len(quiz_questions)} answers in bulk...")
    client.put(
        f"/courses/{course_id}/quizzes/{quiz_id}/submissions/{qs_id}/questions",
        json={"quiz_questions": quiz_questions},
    )


def _submit_sequential(client, course_id, quiz_id, qs_id, parsed_answers, questions):
    """Submit answers one at a time for one_question_at_a_time quizzes."""
    print(f"[submit_quiz] Sequential mode: {len(questions)} questions")
    for i, q in enumerate(questions):
        q_id = q["id"]
        answer = parsed_answers.get(str(q_id)) or parsed_answers.get(q_id)
        entry = {"id": q_id}
        if answer:
            if "answer_id" in answer:
                entry["answer"] = answer["answer_id"]
            else:
                entry["answer"] = answer.get("answer_text", "")
        else:
            entry["answer"] = ""  # blank answer if not parsed

        print(f"  [{i+1}/{len(questions)}] Answering question {q_id}...")
        client.put(
            f"/courses/{course_id}/quizzes/{quiz_id}/submissions/{qs_id}/questions",
            json={"quiz_questions": [entry]},
        )
        time.sleep(0.5)  # small pause between sequential questions


def _base_record(course_id, quiz, run_id, llm_response=None, error=None):
    # Load course name from context if available
    course_name = ""
    context_path = f".tmp/context_{course_id}.json"
    if os.path.exists(context_path):
        with open(context_path) as f:
            course_name = json.load(f).get("course_name", "")

    return {
        "course_id": course_id,
        "course_name": course_name,
        "assignment_id": f"quiz_{quiz['id']}",
        "assignment_name": quiz.get("title", ""),
        "assignment_type": "online_quiz",
        "model": llm_response.get("model", "") if llm_response else "",
        "prompt_tokens": llm_response.get("token_in", 0) if llm_response else 0,
        "completion_tokens": llm_response.get("token_out", 0) if llm_response else 0,
        "latency_ms": llm_response.get("latency_ms", 0) if llm_response else 0,
        "submitted_at": None,
        "submission_id": None,
        "grade": None,
        "score": None,
        "max_points": quiz.get("points_possible", 0),
        "error": error,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Submit a quiz to Canvas")
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--quiz-id", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    submit_quiz(args.course_id, args.quiz_id, args.run_id)
