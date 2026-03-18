# Export Results

## Objective
Export benchmark data to CSV and/or Google Sheets for analysis.

## Required Inputs
- `run_id`
- `.tmp/benchmark_<run_id>.jsonl` must exist

## Steps

```bash
# CSV only (default)
python tools/export_results.py --run-id <run_id> --format csv

# Google Sheets only
python tools/export_results.py --run-id <run_id> --format sheets

# Both
python tools/export_results.py --run-id <run_id> --format both
```

CSV output: `.tmp/benchmark_results_<run_id>.csv`

## Column Reference

| Column | Description |
|---|---|
| `run_id` | Benchmark run identifier (timestamp) |
| `course_id` | Canvas course ID |
| `assignment_id` | Canvas assignment ID (or `quiz_<id>`) |
| `assignment_type` | Submission type used |
| `model` | LLM model used |
| `prompt_tokens` | Input tokens sent to LLM |
| `completion_tokens` | Output tokens received |
| `latency_ms` | LLM wall-clock latency |
| `submitted_at` | ISO timestamp of Canvas submission |
| `grade` | Canvas grade string (e.g., "A", "85") |
| `score` | Raw numeric score |
| `max_points` | Maximum possible score |
| `score_pct` | `score / max_points * 100` |
| `error` | Error message if submission failed |

## Key Stats (printed on every export)
- Mean score % across all graded assignments
- Error rate (failed submissions / total)
- Mean LLM latency (ms)
- Mean tokens per task

## Google Sheets Setup
1. Create a Google Cloud service account with Sheets + Drive access
2. Share your target spreadsheet with the service account email
3. Download the JSON credentials key → save as `credentials.json` in project root
4. Set `BENCHMARK_SHEET_ID` in `.env` (the sheet ID from the URL)
5. Pre-create the sheet with column headers matching the `COLUMNS` list in `export_results.py`

## Interpreting Results
- Compare `score_pct` by `assignment_type` to identify where the LLM performs best/worst
- `score_pct = null` means not yet graded — exclude from aggregate stats
- High latency + low tokens usually means API cold-start; high tokens + normal latency is expected for essays
- `error` column: `lockdown_browser_required` = expected skip; API errors = investigate
