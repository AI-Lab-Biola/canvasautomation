"""
benchmark_logger.py — Append-only JSONL benchmark log per run.

Each line in .tmp/benchmark_<run_id>.jsonl is one JSON record.
Schema:
  run_id, course_id, course_name, assignment_id, assignment_name,
  assignment_type, model, prompt_tokens, completion_tokens, latency_ms,
  submitted_at, submission_id, grade, score, max_points, error

Usage (as module):
  from tools.benchmark_logger import log_attempt, update_grade, load_run
"""

import json
import os
from datetime import datetime, timezone


def _log_path(run_id):
    os.makedirs(".tmp", exist_ok=True)
    return f".tmp/benchmark_{run_id}.jsonl"


def log_attempt(run_id, record: dict):
    """Append a new benchmark record to the JSONL log."""
    full_record = {
        "run_id": run_id,
        "logged_at": datetime.now(timezone.utc).isoformat(),
        "course_id": None,
        "course_name": "",
        "assignment_id": None,
        "assignment_name": "",
        "assignment_type": "",
        "model": "",
        "prompt_tokens": 0,
        "completion_tokens": 0,
        "latency_ms": 0,
        "submitted_at": None,
        "submission_id": None,
        "grade": None,
        "score": None,
        "max_points": 0,
        "error": None,
    }
    full_record.update(record)

    path = _log_path(run_id)
    with open(path, "a") as f:
        f.write(json.dumps(full_record) + "\n")

    print(f"[benchmark_logger] Logged: {full_record['assignment_name']} | error={full_record['error']}")


def update_grade(run_id, assignment_id, grade, score):
    """Update grade and score for a specific assignment in the log."""
    path = _log_path(run_id)
    if not os.path.exists(path):
        print(f"[benchmark_logger] Log not found: {path}")
        return

    records = load_run(run_id)
    updated = False
    for r in records:
        if str(r.get("assignment_id")) == str(assignment_id) and r.get("grade") is None:
            r["grade"] = grade
            r["score"] = score
            r["grade_fetched_at"] = datetime.now(timezone.utc).isoformat()
            updated = True

    if updated:
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")
        print(f"[benchmark_logger] Updated grade for assignment {assignment_id}: {score}/{r.get('max_points')}")
    else:
        print(f"[benchmark_logger] No ungraded record found for assignment {assignment_id}")


def load_run(run_id):
    """Load all records for a run. Returns list of dicts."""
    path = _log_path(run_id)
    if not os.path.exists(path):
        return []
    records = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if line:
                records.append(json.loads(line))
    return records


def print_run_summary(run_id):
    records = load_run(run_id)
    if not records:
        print(f"No records found for run {run_id}")
        return

    total = len(records)
    errors = sum(1 for r in records if r.get("error"))
    graded = [r for r in records if r.get("score") is not None]
    scores = [r["score"] / r["max_points"] * 100 for r in graded if r.get("max_points")]

    print(f"\n=== Benchmark Run: {run_id} ===")
    print(f"  Total attempts:  {total}")
    print(f"  Errors:          {errors}")
    print(f"  Graded:          {len(graded)}/{total}")
    if scores:
        print(f"  Mean score:      {sum(scores)/len(scores):.1f}%")
        print(f"  Min score:       {min(scores):.1f}%")
        print(f"  Max score:       {max(scores):.1f}%")
    avg_tokens = sum(r.get("prompt_tokens", 0) + r.get("completion_tokens", 0) for r in records) / total
    print(f"  Avg tokens/task: {avg_tokens:.0f}")
    avg_latency = sum(r.get("latency_ms", 0) for r in records) / total
    print(f"  Avg latency:     {avg_latency:.0f}ms")
