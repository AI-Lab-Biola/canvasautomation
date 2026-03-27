"""
submit_assignment.py — Submit an LLM response to Canvas by assignment type.

Routes based on submission_types[0]:
  - online_text_entry  → POST body as HTML
  - online_url         → extract URL from response, POST it
  - discussion_topic   → POST to discussion entries endpoint
  - online_upload      → save as .txt file, upload via upload_file.py, POST file_ids

Reads:  .tmp/responses_<run_id>/<assignment_id>.json
        .tmp/assignments_<course_id>.json
Updates: .tmp/benchmark_<run_id>.jsonl via benchmark_logger

Usage: python tools/submit_assignment.py --course-id 12345 --assignment-id 67890 --run-id <run_id>
"""

import argparse
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient
from tools.upload_file import upload_file, save_response_as_file
from tools.benchmark_logger import log_attempt


def submit_assignment(course_id, assignment_id, run_id):
    client = CanvasClient()

    # Load assignment metadata
    assignments_path = f".tmp/assignments_{course_id}.json"
    with open(assignments_path) as f:
        assignments = json.load(f)
    assignment = next((a for a in assignments if a["id"] == assignment_id), None)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} not found in {assignments_path}")

    # Load LLM response
    response_path = f".tmp/responses_{run_id}/{assignment_id}.json"
    with open(response_path) as f:
        llm_response = json.load(f)

    response_text = llm_response["text"]
    submission_type = (assignment.get("submission_types") or ["online_text_entry"])[0]

    print(f"[submit_assignment] Submitting assignment {assignment_id} as '{submission_type}'...")

    submission_id = None
    submitted_at = None
    error = None

    try:
        if submission_type == "online_text_entry":
            result = _submit_text(client, course_id, assignment_id, response_text)

        elif submission_type == "online_url":
            result = _submit_url(client, course_id, assignment_id, response_text)

        elif submission_type == "discussion_topic":
            result = _submit_discussion(client, course_id, assignment, response_text)

        elif submission_type == "online_upload":
            # Check if an Excel file was generated for this assignment
            excel_path = f".tmp/responses_{run_id}/{assignment_id}.xlsx"
            reflection_text = llm_response.get("reflection_text", "")
            if os.path.exists(excel_path):
                result = _submit_excel(client, course_id, assignment_id, excel_path, reflection_text, run_id)
            else:
                result = _submit_upload(client, course_id, assignment_id, response_text, run_id)

        else:
            raise NotImplementedError(f"Submission type '{submission_type}' not supported")

        submission_id = result.get("id") or result.get("submission_id")
        submitted_at = result.get("submitted_at")
        print(f"[submit_assignment] Submitted! submission_id={submission_id}, submitted_at={submitted_at}")

    except Exception as e:
        error = str(e)
        print(f"[submit_assignment] ERROR: {error}")

    # Load course name from context if available
    course_name = ""
    context_path = f".tmp/context_{course_id}.json"
    if os.path.exists(context_path):
        with open(context_path) as f:
            course_name = json.load(f).get("course_name", "")

    # Log to benchmark
    log_attempt(run_id, {
        "course_id": course_id,
        "course_name": course_name,
        "assignment_id": assignment_id,
        "assignment_name": assignment.get("name", ""),
        "assignment_type": submission_type,
        "model": llm_response.get("model", ""),
        "prompt_tokens": llm_response.get("token_in", 0),
        "completion_tokens": llm_response.get("token_out", 0),
        "latency_ms": llm_response.get("latency_ms", 0),
        "submitted_at": submitted_at,
        "submission_id": submission_id,
        "grade": None,
        "score": None,
        "max_points": assignment.get("points_possible", 0),
        "error": error,
    })

    return {"submission_id": submission_id, "submitted_at": submitted_at, "error": error}


def _submit_text(client, course_id, assignment_id, text):
    # Wrap in minimal HTML for Canvas rich text
    html_body = f"<p>{text.replace(chr(10), '</p><p>')}</p>"
    return client.post(
        f"/courses/{course_id}/assignments/{assignment_id}/submissions",
        json={
            "submission": {
                "submission_type": "online_text_entry",
                "body": html_body,
            }
        },
    )


def _submit_url(client, course_id, assignment_id, text):
    # Extract URL from response — look for "URL: http..." pattern or bare URL
    url_match = re.search(r"URL:\s*(https?://\S+)", text) or re.search(r"(https?://\S+)", text)
    if not url_match:
        raise ValueError("LLM response did not contain a valid URL for online_url submission")
    url = url_match.group(1).rstrip(".,;)")
    print(f"[submit_assignment] Extracted URL: {url}")
    return client.post(
        f"/courses/{course_id}/assignments/{assignment_id}/submissions",
        json={
            "submission": {
                "submission_type": "online_url",
                "url": url,
            }
        },
    )


def _submit_discussion(client, course_id, assignment, text):
    discussion_topic = assignment.get("discussion_topic") or {}
    topic_id = discussion_topic.get("id")
    if not topic_id:
        raise ValueError(f"Assignment {assignment['id']} has no discussion_topic.id")
    result = client.post(
        f"/courses/{course_id}/discussion_topics/{topic_id}/entries",
        json={"message": text},
    )
    # Wrap in submission-like dict for consistent return
    return {"id": result.get("id"), "submitted_at": result.get("created_at")}


def _submit_upload(client, course_id, assignment_id, text, run_id):
    file_path = save_response_as_file(text, assignment_id, run_id)
    file_id = upload_file(client, course_id, assignment_id, file_path)
    return client.post(
        f"/courses/{course_id}/assignments/{assignment_id}/submissions",
        json={
            "submission": {
                "submission_type": "online_upload",
                "file_ids": [file_id],
            }
        },
    )


def _submit_excel(client, course_id, assignment_id, excel_path, reflection_text, run_id):
    """Upload the .xlsx workbook (and optionally a reflection .txt) then submit both file IDs."""
    file_ids = []

    # Upload the Excel workbook
    excel_id = upload_file(client, course_id, assignment_id, excel_path)
    file_ids.append(excel_id)

    # If there's a reflection, save and upload it too
    if reflection_text.strip():
        reflection_path = save_response_as_file(reflection_text, f"{assignment_id}_reflection", run_id)
        reflection_id = upload_file(client, course_id, assignment_id, reflection_path)
        file_ids.append(reflection_id)

    return client.post(
        f"/courses/{course_id}/assignments/{assignment_id}/submissions",
        json={
            "submission": {
                "submission_type": "online_upload",
                "file_ids": file_ids,
            }
        },
    )


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Submit an assignment to Canvas")
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--assignment-id", type=int, required=True)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()
    submit_assignment(args.course_id, args.assignment_id, args.run_id)
