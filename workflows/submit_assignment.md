# Submit Assignment

## Objective
Submit an LLM-generated response to a Canvas assignment using the correct submission method.

## Required Inputs
- `course_id`
- `assignment_id`
- `run_id`
- LLM response must already exist at `.tmp/responses_<run_id>/<assignment_id>.json`

## Submission Type Routing

`submit_assignment.py` reads `submission_types[0]` from the assignment and routes:

| Type | Method | Notes |
|---|---|---|
| `online_text_entry` | POST body as HTML | Default — works for essays, short answers |
| `online_url` | Extract URL from LLM response | LLM must include `URL: https://...` in response |
| `discussion_topic` | POST to discussion entries | Uses `assignment.discussion_topic.id` |
| `online_upload` | Save as .txt → 3-step upload | Generates `<assignment_id>_submission.txt` |

## Steps

```bash
python tools/submit_assignment.py --course-id <id> --assignment-id <id> --run-id <run_id>
```

The tool:
1. Reads assignment metadata from `.tmp/assignments_<course_id>.json`
2. Reads LLM response from `.tmp/responses_<run_id>/<assignment_id>.json`
3. Routes to the correct submission method
4. Logs the result to `.tmp/benchmark_<run_id>.jsonl`

## Edge Cases
- **422 Validation Error**: Assignment settings may reject the submission (e.g., past due with no late policy). Error is logged and execution continues.
- **Multiple submission types**: Only `submission_types[0]` is used. If an assignment allows both text and upload, text is chosen.
- **online_url with no URL in response**: Error is logged. Ensure the LLM prompt explicitly requests a URL.
- **discussion_topic without topic ID**: If `discussion_topic.id` is missing from the assignment object, fetch assignments again — this field should be included.
- **online_upload**: File is saved as plain `.txt`. If an assignment explicitly requires PDF, adjust `save_response_as_file()` in `upload_file.py`.
