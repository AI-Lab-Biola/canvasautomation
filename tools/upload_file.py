"""
upload_file.py — Canvas 3-step file upload process.

Step 1: Notify Canvas API → get pre-authorized S3 upload URL + params
Step 2: POST file binary directly to S3 (NO Authorization header)
Step 3: Confirm with Canvas API → get file_id

Returns file_id for use in assignment submission.

Usage (as module):
  from tools.upload_file import upload_file
  file_id = upload_file(client, course_id, assignment_id, file_path)
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from tools.canvas_client import CanvasClient

CONTENT_TYPE_MAP = {
    ".pdf": "application/pdf",
    ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ".txt": "text/plain",
    ".md": "text/markdown",
    ".html": "text/html",
    ".py": "text/x-python",
}


def upload_file(client, course_id, assignment_id, file_path):
    """
    Upload a file to Canvas for an assignment submission.
    Returns the Canvas file_id (int).
    """
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"File not found: {file_path}")

    file_name = os.path.basename(file_path)
    file_size = os.path.getsize(file_path)
    ext = os.path.splitext(file_name)[1].lower()
    content_type = CONTENT_TYPE_MAP.get(ext, "application/octet-stream")

    print(f"[upload_file] Step 1: Notifying Canvas API...")
    # Step 1 — Notify Canvas, get upload URL
    notify_response = client.post(
        f"/courses/{course_id}/assignments/{assignment_id}/submissions/self/files",
        json={
            "name": file_name,
            "size": file_size,
            "content_type": content_type,
        },
    )

    upload_url = notify_response.get("upload_url")
    upload_params = notify_response.get("upload_params", {})

    if not upload_url:
        raise RuntimeError(f"Canvas did not return an upload URL: {notify_response}")

    print(f"[upload_file] Step 2: Uploading to S3...")
    # Step 2 — Upload binary directly to S3 (NO auth header — must use raw post)
    with open(file_path, "rb") as fh:
        file_data = fh.read()

    # S3 requires form fields from upload_params BEFORE the file field
    form_data = {k: (None, v) for k, v in upload_params.items()}
    form_data["file"] = (file_name, file_data, content_type)

    import requests
    resp = requests.post(upload_url, files=form_data)

    if resp.status_code not in (200, 201, 301, 302, 303):
        raise RuntimeError(f"S3 upload failed {resp.status_code}: {resp.text[:300]}")

    # S3 may redirect to a confirmation URL
    confirm_url = resp.headers.get("Location") or resp.url

    print(f"[upload_file] Step 3: Confirming with Canvas...")
    # Step 3 — Confirm with Canvas to get file_id
    confirm_resp = client._request("GET", confirm_url)
    file_data_resp = confirm_resp.json()
    file_id = file_data_resp.get("id")

    if not file_id:
        raise RuntimeError(f"Canvas confirmation did not return file ID: {file_data_resp}")

    print(f"[upload_file] Upload complete. File ID: {file_id}")
    return file_id


def save_response_as_file(response_text, assignment_id, run_id):
    """Save LLM response text to a .txt file for upload."""
    out_dir = f".tmp/responses_{run_id}"
    os.makedirs(out_dir, exist_ok=True)
    file_path = f"{out_dir}/{assignment_id}_submission.txt"
    with open(file_path, "w") as f:
        f.write(response_text)
    return file_path
