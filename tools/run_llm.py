"""
run_llm.py — Call Claude API with a built prompt. Returns structured response.

Reads:  .tmp/prompts_<run_id>/<assignment_id>.json  (or quiz_<quiz_id>.json)
Writes: .tmp/responses_<run_id>/<assignment_id>.json

Usage:
  python tools/run_llm.py --assignment-id 67890 --run-id <run_id>
  python tools/run_llm.py --quiz-id 11111 --run-id <run_id>
  python tools/run_llm.py --assignment-id 67890 --run-id <run_id> --dry-run
"""

import argparse
import json
import os
import re
import sys
import time

import anthropic
from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))


def run_llm(prompt_data, dry_run=False):
    model = os.getenv("BENCHMARK_MODEL", "claude-sonnet-4-6")
    max_tokens = int(os.getenv("BENCHMARK_MAX_TOKENS", "4096"))

    if dry_run:
        print(f"[run_llm] DRY RUN — would call {model} with ~{prompt_data['estimated_input_tokens']} input tokens")
        print(f"\n--- SYSTEM PROMPT ---\n{prompt_data['system_prompt'][:200]}...\n")
        print(f"--- USER PROMPT (first 500 chars) ---\n{prompt_data['user_prompt'][:500]}...\n")
        return {
            "text": "[DRY RUN — no LLM call made]",
            "token_in": 0,
            "token_out": 0,
            "latency_ms": 0,
            "model": model,
        }

    client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

    print(f"[run_llm] Calling {model}...")
    t0 = time.monotonic()

    message = client.messages.create(
        model=model,
        max_tokens=max_tokens,
        system=prompt_data["system_prompt"],
        messages=[{"role": "user", "content": prompt_data["user_prompt"]}],
    )

    latency_ms = int((time.monotonic() - t0) * 1000)
    response_text = message.content[0].text if message.content else ""

    result = {
        "text": response_text,
        "token_in": message.usage.input_tokens,
        "token_out": message.usage.output_tokens,
        "latency_ms": latency_ms,
        "model": model,
        "stop_reason": message.stop_reason,
    }

    print(f"[run_llm] Done. Tokens: {result['token_in']} in / {result['token_out']} out | {latency_ms}ms")
    return result


def run_for_assignment(assignment_id, run_id, dry_run=False):
    prompt_path = f".tmp/prompts_{run_id}/{assignment_id}.json"
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Prompt not found: {prompt_path}. Run build_prompt.py first.")

    with open(prompt_path) as f:
        prompt_data = json.load(f)

    result = run_llm(prompt_data, dry_run=dry_run)
    result["assignment_id"] = assignment_id
    result["run_id"] = run_id

    out_dir = f".tmp/responses_{run_id}"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/{assignment_id}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[run_llm] Response saved → {out_path}")
    return result


def run_for_quiz(quiz_id, run_id, dry_run=False):
    prompt_path = f".tmp/prompts_{run_id}/quiz_{quiz_id}.json"
    if not os.path.exists(prompt_path):
        raise FileNotFoundError(f"Prompt not found: {prompt_path}. Run build_prompt.py first.")

    with open(prompt_path) as f:
        prompt_data = json.load(f)

    result = run_llm(prompt_data, dry_run=dry_run)
    result["quiz_id"] = quiz_id
    result["run_id"] = run_id

    # Parse quiz answers from response text
    parsed_answers = parse_quiz_answers(result["text"], prompt_data.get("questions", []))
    result["parsed_answers"] = parsed_answers

    out_dir = f".tmp/responses_{run_id}"
    os.makedirs(out_dir, exist_ok=True)
    out_path = f"{out_dir}/quiz_{quiz_id}.json"
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    print(f"[run_llm] Quiz response saved → {out_path}")
    return result


def parse_quiz_answers(response_text, questions):
    """
    Parse LLM response into a dict of {question_id: answer_text_or_choice}.
    Expected format: Q1: B, Q2: some answer text, ...
    """
    answers = {}
    lines = response_text.strip().split("\n")
    q_map = {i + 1: q for i, q in enumerate(questions)}

    for line in lines:
        line = line.strip()
        if not line:
            continue
        # Match Q<n>: <answer>
        match = re.match(r"Q(\d+):\s*(.+)", line, re.IGNORECASE)
        if match:
            q_num = int(match.group(1))
            answer = match.group(2).strip()
            if q_num in q_map:
                question = q_map[q_num]
                # For MCQ: map letter to answer ID
                if question.get("answers"):
                    labels = "ABCDEFGHIJKLMNOP"
                    if len(answer) == 1 and answer.upper() in labels:
                        idx = labels.index(answer.upper())
                        if idx < len(question["answers"]):
                            answer_id = question["answers"][idx]["id"]
                            answers[question["id"]] = {"answer_id": answer_id, "raw": answer}
                            continue
                # For text-based answers
                answers[question["id"]] = {"answer_text": answer, "raw": answer}

    return answers


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Run LLM on a built prompt")
    parser.add_argument("--assignment-id", type=int)
    parser.add_argument("--quiz-id", type=int)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--dry-run", action="store_true", help="Preview prompt without calling API")
    args = parser.parse_args()

    if args.assignment_id:
        run_for_assignment(args.assignment_id, args.run_id, dry_run=args.dry_run)
    elif args.quiz_id:
        run_for_quiz(args.quiz_id, args.run_id, dry_run=args.dry_run)
    else:
        print("Error: provide --assignment-id or --quiz-id")
        sys.exit(1)
