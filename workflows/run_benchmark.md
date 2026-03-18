# Run Benchmark — Master SOP

## Objective
End-to-end benchmark run: authenticate → fetch course data → generate LLM responses → submit to Canvas → collect grades → export results.

## Pre-flight Checklist
- [ ] `.env` is populated: `CANVAS_DOMAIN`, `CANVAS_TOKEN`, `ANTHROPIC_API_KEY`
- [ ] Auth verified: `python tools/fetch_courses.py` prints courses without error
- [ ] Python dependencies installed: `pip install -r requirements.txt`
- [ ] Target course IDs identified (from fetch_courses output or `.env` `BENCHMARK_COURSE_IDS`)

## Step-by-Step Execution

### 1. Generate a run ID
```bash
export RUN_ID=$(date +%Y-%m-%dT%H-%M-%S)
echo "Run ID: $RUN_ID"
```

### 2. Fetch all courses (if running on all)
```bash
python tools/fetch_courses.py
# Review .tmp/courses.json and note target course IDs
```

### 3. For each course: fetch context + assignments + quizzes
```bash
COURSE_ID=12345

python tools/fetch_course_context.py --course-id $COURSE_ID
python tools/fetch_assignments.py --course-id $COURSE_ID
python tools/fetch_quizzes.py --course-id $COURSE_ID
```

### 4. For each assignment: build prompt → run LLM → submit
```bash
ASSIGNMENT_ID=67890

python tools/build_prompt.py --course-id $COURSE_ID --assignment-id $ASSIGNMENT_ID --run-id $RUN_ID
python tools/run_llm.py --assignment-id $ASSIGNMENT_ID --run-id $RUN_ID
python tools/submit_assignment.py --course-id $COURSE_ID --assignment-id $ASSIGNMENT_ID --run-id $RUN_ID
```

### 5. For each quiz: build prompt → run LLM → submit (ORDER MATTERS)
```bash
QUIZ_ID=11111

python tools/build_prompt.py --course-id $COURSE_ID --quiz-id $QUIZ_ID --run-id $RUN_ID
python tools/run_llm.py --quiz-id $QUIZ_ID --run-id $RUN_ID
# Only AFTER LLM response is confirmed:
python tools/submit_quiz.py --course-id $COURSE_ID --quiz-id $QUIZ_ID --run-id $RUN_ID
```

### 6. Quick grade check (auto-graded quizzes)
```bash
sleep 300  # wait 5 min
python tools/fetch_grades.py --run-id $RUN_ID --once
```

### 7. Deferred grade polling (essays/text assignments)
```bash
# Run this later — it will poll every hour for up to 48h
python tools/fetch_grades.py --run-id $RUN_ID
```

### 8. Export results
```bash
python tools/export_results.py --run-id $RUN_ID --format both
```

## Decision Tree

```
Assignment type?
├─ online_quiz
│   ├─ require_lockdown_browser? → SKIP (logged automatically)
│   └─ else → build_prompt → run_llm → submit_quiz
├─ online_text_entry / online_upload / online_url / discussion_topic
│   └─ build_prompt → run_llm → submit_assignment
└─ unsupported type → logged as error, continue
```

## Error Handling
- **API error on submission** → logged with `error` field, benchmark continues to next assignment
- **LLM response missing** → do NOT start quiz session; fix and rerun `run_llm.py` first
- **Rate limit hit** → `canvas_client.py` handles automatically with backoff
- **Locked assignment** → skipped during `fetch_assignments.py`, does not appear in run
- **Already submitted** → skipped during `fetch_assignments.py`

## Expected Outputs
- `.tmp/courses.json` — course list
- `.tmp/context_<course_id>.json` — course context per course
- `.tmp/assignments_<course_id>.json` — assignment list per course
- `.tmp/quizzes_<course_id>.json` — quiz list per course
- `.tmp/prompts_<run_id>/` — one prompt file per assignment/quiz
- `.tmp/responses_<run_id>/` — one LLM response file per assignment/quiz
- `.tmp/benchmark_<run_id>.jsonl` — full benchmark log
- `.tmp/benchmark_results_<run_id>.csv` — final results export

## After the Run
1. Review error rate in export summary
2. For any failed submissions, check `.tmp/benchmark_<run_id>.jsonl` `error` field
3. Update this workflow if new edge cases were discovered
4. Update tool scripts if API behavior changed
