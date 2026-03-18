"""
build_prompt.py — Assemble course context + assignment/quiz into an LLM-ready prompt.

Token budget (approximate):
  - System instructions:  ~500 tokens
  - Course context:      ~2000 tokens  (syllabus excerpt)
  - Assignment:          ~1500 tokens  (description + rubric)
  Total input:           ~4000 tokens
  Max output:             4096 tokens

Writes: .tmp/prompts_<run_id>/<assignment_id>.json
Usage:
  python tools/build_prompt.py --course-id 12345 --assignment-id 67890 --run-id <run_id>
  python tools/build_prompt.py --course-id 12345 --quiz-id 11111 --run-id <run_id>
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

# Rough token estimate: 1 token ≈ 4 characters
CHARS_PER_TOKEN = 4
CONTEXT_TOKEN_BUDGET = 2000
ASSIGNMENT_TOKEN_BUDGET = 1500

SYSTEM_PROMPT = """You are a student completing an academic assignment as part of an AI benchmarking study. \
Your goal is to produce a well-reasoned, academically appropriate response based on the course context \
and assignment instructions provided. Follow the rubric criteria if provided. \
Write in a clear, academic style appropriate for undergraduate coursework."""


def _truncate(text, token_budget):
    char_limit = token_budget * CHARS_PER_TOKEN
    if len(text) > char_limit:
        return text[:char_limit] + "\n[... truncated for context window ...]"
    return text


def build_assignment_prompt(course_id, assignment_id, run_id):
    context_path = f".tmp/context_{course_id}.json"
    assignments_path = f".tmp/assignments_{course_id}.json"

    if not os.path.exists(assignments_path):
        raise FileNotFoundError(f"Assignments not found: {assignments_path}. Run fetch_assignments.py first.")

    # Context is best-effort — proceed without it if missing
    if os.path.exists(context_path):
        with open(context_path) as f:
            context = json.load(f)
    else:
        print(f"[build_prompt] Warning: Context not found at {context_path}, proceeding without course context.")
        context = {"course_name": f"Course {course_id}", "syllabus_text": "", "pages": [], "modules": []}

    with open(assignments_path) as f:
        assignments = json.load(f)

    assignment = next((a for a in assignments if a["id"] == assignment_id), None)
    if not assignment:
        raise ValueError(f"Assignment {assignment_id} not found in {assignments_path}")

    # Build context block
    syllabus_block = _truncate(context.get("syllabus_text", ""), CONTEXT_TOKEN_BUDGET)
    course_name = context.get("course_name", f"Course {course_id}")

    # Build assignment block
    desc_block = _truncate(assignment.get("description", ""), ASSIGNMENT_TOKEN_BUDGET // 2)

    rubric_lines = []
    for r in assignment.get("rubric", []):
        rubric_lines.append(f"- {r['description']} ({r['points']} pts): {r.get('long_description', '')}")
    rubric_block = "\n".join(rubric_lines) if rubric_lines else "(No rubric provided)"

    sub_type = (assignment.get("submission_types") or ["online_text_entry"])[0]
    format_guidance = {
        "online_text_entry": "Write your response as a clear, well-structured essay or answer.",
        "online_upload": "Write your response as a document (will be saved as .txt and uploaded).",
        "online_url": "Your response must end with a valid URL on its own line, prefixed with 'URL: '.",
        "discussion_topic": "Write a discussion post response, engaging with the prompt as if posting to a class forum.",
    }.get(sub_type, "Write your response clearly and directly.")

    user_prompt = f"""COURSE: {course_name}

COURSE CONTEXT (Syllabus):
{syllabus_block}

---

ASSIGNMENT: {assignment['name']}
POINTS: {assignment.get('points_possible', 'N/A')}
DUE: {assignment.get('due_at', 'N/A')}

INSTRUCTIONS:
{desc_block}

RUBRIC CRITERIA:
{rubric_block}

SUBMISSION FORMAT: {format_guidance}

---

Complete this assignment now."""

    result = {
        "run_id": run_id,
        "course_id": course_id,
        "assignment_id": assignment_id,
        "assignment_name": assignment["name"],
        "submission_type": sub_type,
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "estimated_input_tokens": len(SYSTEM_PROMPT + user_prompt) // CHARS_PER_TOKEN,
    }

    out_dir = f".tmp/prompts_{run_id}"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{assignment_id}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[build_prompt] Assignment {assignment_id} prompt written → {out_path}")
    print(f"  Estimated input tokens: {result['estimated_input_tokens']}")
    return result


def build_quiz_prompt(course_id, quiz_id, run_id):
    context_path = f".tmp/context_{course_id}.json"
    quizzes_path = f".tmp/quizzes_{course_id}.json"

    if not os.path.exists(quizzes_path):
        raise FileNotFoundError(f"Quizzes not found: {quizzes_path}")

    # Context is best-effort — proceed without it if missing
    if os.path.exists(context_path):
        with open(context_path) as f:
            context = json.load(f)
    else:
        print(f"[build_prompt] Warning: Context not found at {context_path}, proceeding without course context.")
        context = {"course_name": f"Course {course_id}", "syllabus_text": "", "pages": [], "modules": []}

    with open(quizzes_path) as f:
        quizzes = json.load(f)

    quiz = next((q for q in quizzes if q["id"] == quiz_id), None)
    if not quiz:
        raise ValueError(f"Quiz {quiz_id} not found in {quizzes_path}")

    course_name = context.get("course_name", f"Course {course_id}")
    syllabus_block = _truncate(context.get("syllabus_text", ""), CONTEXT_TOKEN_BUDGET)

    # Format questions
    q_lines = []
    answer_labels = "ABCDEFGHIJKLMNOP"
    for i, q in enumerate(quiz["questions"], 1):
        q_lines.append(f"Q{i} [{q['question_type']}] ({q['points_possible']} pts): {q['question_text']}")
        if q["answers"]:
            for j, a in enumerate(q["answers"]):
                label = answer_labels[j] if j < len(answer_labels) else str(j)
                q_lines.append(f"   {label}) {a['text']}")
        q_lines.append("")

    questions_block = "\n".join(q_lines)

    user_prompt = f"""COURSE: {course_name}

COURSE CONTEXT (Syllabus):
{syllabus_block}

---

QUIZ: {quiz['title']}
QUESTIONS: {len(quiz['questions'])}

{questions_block}

---

Answer each question. Format your answers EXACTLY as follows (one per line):
Q1: [A/B/C/D for multiple choice, or your answer text for short answer/essay]
Q2: [answer]
... and so on for each question.

For multiple choice, give only the letter (e.g., Q1: B).
For short answer or essay, write your answer after the Q#: prefix."""

    result = {
        "run_id": run_id,
        "course_id": course_id,
        "quiz_id": quiz_id,
        "quiz_name": quiz["title"],
        "submission_type": "online_quiz",
        "one_question_at_a_time": quiz.get("one_question_at_a_time", False),
        "system_prompt": SYSTEM_PROMPT,
        "user_prompt": user_prompt,
        "questions": quiz["questions"],
        "estimated_input_tokens": len(SYSTEM_PROMPT + user_prompt) // CHARS_PER_TOKEN,
    }

    out_dir = f".tmp/prompts_{run_id}"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/quiz_{quiz_id}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[build_prompt] Quiz {quiz_id} prompt written → {out_path}")
    return result


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build LLM prompt for an assignment or quiz")
    parser.add_argument("--course-id", type=int, required=True)
    parser.add_argument("--assignment-id", type=int)
    parser.add_argument("--quiz-id", type=int)
    parser.add_argument("--run-id", required=True)
    args = parser.parse_args()

    if args.assignment_id:
        build_assignment_prompt(args.course_id, args.assignment_id, args.run_id)
    elif args.quiz_id:
        build_quiz_prompt(args.course_id, args.quiz_id, args.run_id)
    else:
        print("Error: provide --assignment-id or --quiz-id")
        sys.exit(1)
