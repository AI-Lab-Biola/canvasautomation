# Grade Polling

## Objective
Poll Canvas submissions for grades after the benchmark run and update the benchmark log.

## When Grades Are Available

| Assignment Type | Typical Availability |
|---|---|
| Auto-graded quiz (MCQ) | Minutes |
| Survey quiz | Minutes to hours |
| Short answer quiz (manual grading) | Hours to days |
| `online_text_entry` essay | Hours to days (instructor must grade) |
| `online_upload` | Hours to days |
| `discussion_topic` | Hours to days |

## Steps

### Single check (no loop):
```bash
python tools/fetch_grades.py --run-id <run_id> --once
```

### Polling loop (recommended for full benchmark runs):
```bash
python tools/fetch_grades.py --run-id <run_id>
```
Polls every `GRADE_POLL_INTERVAL_SECONDS` (default: 3600s = 1h) up to `GRADE_POLL_MAX_HOURS` (default: 48h).

### Recommended polling schedule for mixed assignment types:
- T+5min: `--once` (catches auto-graded quizzes)
- T+1h: `--once`
- T+24h: `--once`
- T+48h: `--once` then export regardless

## Stopping Conditions
- All submissions have a `score` in the log → polling stops automatically
- `GRADE_POLL_MAX_HOURS` elapsed → stops and marks remaining as `grade_not_received` conceptually (score stays `null`)
- After 7 days without a grade, consider the assignment not graded by the instructor

## Edge Cases
- **Instructor never grades**: Score stays `null`. Export will show `null` for those rows. Calculate stats only on graded subset.
- **Grade changed after initial check**: The tool updates on the first non-null grade found. Re-running `--once` after instructor re-grades will NOT update already-recorded grades (grade is locked once written).
- **Quiz regrade**: Canvas sometimes recalculates quiz scores. Run `--once` again to capture updated scores.
