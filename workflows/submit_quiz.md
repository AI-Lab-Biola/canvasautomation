# Submit Quiz

## Objective
Complete a Canvas quiz using an LLM-generated response. Quizzes are stateful and time-sensitive — follow this workflow exactly.

## Required Inputs
- `course_id`
- `quiz_id`
- `run_id`
- LLM response must already exist at `.tmp/responses_<run_id>/quiz_<quiz_id>.json`

## CRITICAL TIMING RULE
**Generate the LLM response BEFORE starting the quiz session.**

Starting a session (`POST /submissions`) starts the countdown timer. If your LLM call happens after the session starts, you risk running out of time mid-session. The correct order is always:

```
build_prompt → run_llm → submit_quiz
```

Never run `submit_quiz` without the LLM response file already present.

## Steps

```bash
python tools/submit_quiz.py --course-id <id> --quiz-id <id> --run-id <run_id>
```

### Internal flow:
1. Checks `require_lockdown_browser` — skips if true
2. Checks for existing in-progress session (crash recovery)
3. **Starts session** → captures `quiz_submission_id` + `validation_token`
4. Submits answers:
   - Standard quiz: PUT all answers in one request
   - `one_question_at_a_time`: synchronous loop, one PUT per question
5. POSTs completion with `validation_token`

## Quiz Types

| Flag | Behavior |
|---|---|
| `require_lockdown_browser: true` | **SKIP** — cannot automate. Logged with error. |
| `one_question_at_a_time: true` | Sequential mode — cannot submit all at once |
| `time_limit` set | Session clock starts on POST. Always have LLM response ready first. |
| `allowed_attempts: 1` | One shot. Do not start if unsure about LLM response quality. |

## Edge Cases
- **Crashed mid-session**: The tool checks for an existing `untaken` submission before creating a new one. If found, it resumes that session rather than consuming an attempt.
- **validation_token**: Captured from session start and passed to the completion POST. If lost, the submission cannot be finalized.
- **Blank answers**: If a question ID is not found in the parsed LLM response, a blank answer is submitted rather than skipping the question.
- **Survey quizzes**: `quiz_type: graded_survey` — submit the same way but grades may be pass/fail or not graded.
- **Time limit**: The tool does not enforce time tracking internally. If a quiz has a strict time limit and the sequential loop is too slow, the session may auto-submit. Ensure LLM response is ready.
