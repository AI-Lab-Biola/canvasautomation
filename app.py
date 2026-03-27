#!/usr/bin/env python3
"""
Canvas Benchmark Runner — Web UI Backend
Flask server that orchestrates the WAT framework tools
and streams live progress to the browser via Server-Sent Events.
"""

import json
import os
import queue
import subprocess
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

from dotenv import load_dotenv
from flask import Flask, Response, jsonify, render_template, request

BASE_DIR = Path(__file__).parent
load_dotenv(BASE_DIR / ".env")

app = Flask(__name__)

# In-memory run store: run_id -> RunState
runs: dict = {}


# ── Run state ─────────────────────────────────────────────────────────────────

class RunState:
    def __init__(self, run_id: str):
        self.run_id = run_id
        self.q: queue.Queue = queue.Queue()
        self.status = "pending"

    def send(self, event_type: str, **kwargs):
        self.q.put({"type": event_type, "ts": datetime.now().strftime("%H:%M:%S"), **kwargs})

    def log(self, message: str, level: str = "info"):
        self.send("log", message=message, level=level)

    def finish(self):
        self.q.put(None)  # sentinel


# ── Routes ────────────────────────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("index.html")


@app.route("/api/start", methods=["POST"])
def api_start():
    data = request.get_json(silent=True) or {}

    canvas_domain = data.get("canvas_domain", "").strip().rstrip("/")
    canvas_token  = data.get("canvas_token",  "").strip()
    course_ids    = data.get("course_ids",    "all").strip() or "all"

    if not canvas_domain:
        return jsonify({"error": "Canvas domain is required"}), 400
    if not canvas_token:
        return jsonify({"error": "Canvas API token is required"}), 400

    # Strip protocol if pasted in
    for prefix in ("https://", "http://"):
        if canvas_domain.startswith(prefix):
            canvas_domain = canvas_domain[len(prefix):]

    run_id = f"run_{int(time.time())}_{uuid.uuid4().hex[:6]}"
    state  = RunState(run_id)

    # Clean up old finished runs to prevent memory leak (keep last 10)
    finished = [k for k, v in runs.items() if v.status in ("complete", "error")]
    for old_id in finished[:-10]:
        del runs[old_id]

    runs[run_id] = state

    thread = threading.Thread(
        target=_run_benchmark,
        args=(state, canvas_domain, canvas_token, course_ids),
        daemon=True,
    )
    thread.start()

    return jsonify({"run_id": run_id})


@app.route("/api/stream/<run_id>")
def api_stream(run_id: str):
    if run_id not in runs:
        return jsonify({"error": "Run not found"}), 404

    state = runs[run_id]

    def generate():
        yield f"data: {json.dumps({'type': 'connected', 'run_id': run_id})}\n\n"
        while True:
            try:
                event = state.q.get(timeout=25)
                if event is None:
                    yield f"data: {json.dumps({'type': 'stream_end'})}\n\n"
                    break
                yield f"data: {json.dumps(event)}\n\n"
            except queue.Empty:
                yield f"data: {json.dumps({'type': 'heartbeat'})}\n\n"

    return Response(
        generate(),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no", "Connection": "keep-alive"},
    )


# ── Tool runner ───────────────────────────────────────────────────────────────

def _run_tool(state: RunState, script: str, args: list, env: dict, timeout: int = 300) -> tuple[bool, str, str]:
    """Run a Python tool script. Returns (success, stdout, stderr)."""
    cmd = ["python3", str(BASE_DIR / "tools" / script)] + [str(a) for a in args]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            env=env,
            cwd=str(BASE_DIR),
            timeout=timeout,
        )
        return result.returncode == 0, result.stdout, result.stderr
    except subprocess.TimeoutExpired:
        return False, "", f"Timeout running {script}"
    except Exception as exc:
        return False, "", str(exc)


# ── Benchmark orchestration ───────────────────────────────────────────────────

def _run_benchmark(state: RunState, canvas_domain: str, canvas_token: str, course_ids: str):
    state.status = "running"

    env = os.environ.copy()
    env["CANVAS_DOMAIN"]        = canvas_domain
    env["CANVAS_TOKEN"]         = canvas_token
    env["BENCHMARK_COURSE_IDS"] = course_ids

    run_id  = state.run_id
    tmp_dir = BASE_DIR / ".tmp"
    tmp_dir.mkdir(exist_ok=True)

    PHASES = ["fetch", "context", "classify", "prompts", "llm", "excel", "submit", "grades"]
    total_phases = len(PHASES)

    def phase(name: str, current: int):
        state.send("phase", phase=name, current=current, total=total_phases)

    try:
        # ── 1. Fetch courses ──────────────────────────────────────────────────
        phase("fetch", 0)
        state.log("Connecting to Canvas…")

        ok, _, err = _run_tool(state, "fetch_courses.py", [], env)
        if not ok:
            state.send("error", message=f"Failed to fetch courses: {err[:300]}")
            state.status = "error"
            return

        courses_file = tmp_dir / "courses.json"
        if not courses_file.exists():
            state.send("error", message="courses.json not created — check your domain and token.")
            state.status = "error"
            return

        with open(courses_file) as f:
            courses = json.load(f)

        if not courses:
            state.send("error", message="No active courses found for this account.")
            state.status = "error"
            return

        state.log(f"Found {len(courses)} active course(s)", "success")
        state.send("courses", courses=[
            {"id": c.get("id"), "name": c.get("name", f"Course {c.get('id')}")}
            for c in courses
        ])
        phase("fetch", 1)

        # ── 2. Fetch contexts, assignments, quizzes ───────────────────────────
        phase("context", 1)

        all_assignments: list[dict] = []
        all_quizzes:     list[dict] = []

        for course in courses:
            cid   = course["id"]
            cname = course.get("name", f"Course {cid}")
            state.log(f"Loading {cname}…")

            # Context (best-effort)
            _run_tool(state, "fetch_course_context.py", ["--course-id", cid], env)

            # Assignments
            ok, _, err = _run_tool(state, "fetch_assignments.py", ["--course-id", cid], env)
            if ok:
                af = tmp_dir / f"assignments_{cid}.json"
                if af.exists():
                    with open(af) as f:
                        items = json.load(f)
                    for item in items:
                        item["_course_id"]   = cid
                        item["_course_name"] = cname
                    all_assignments.extend(items)
                    state.log(f"{cname}: {len(items)} assignment(s)")
            else:
                state.log(f"Warning — assignments fetch failed for {cname}: {err[:120]}", "warning")

            # Quizzes
            ok, _, err = _run_tool(state, "fetch_quizzes.py", ["--course-id", cid], env)
            if ok:
                qf = tmp_dir / f"quizzes_{cid}.json"
                if qf.exists():
                    with open(qf) as f:
                        items = json.load(f)
                    for item in items:
                        item["_course_id"]   = cid
                        item["_course_name"] = cname
                    all_quizzes.extend(items)
                    state.log(f"{cname}: {len(items)} quiz(zes)")
            else:
                state.log(f"Warning — quiz fetch failed for {cname}: {err[:120]}", "warning")

        total_items = len(all_assignments) + len(all_quizzes)
        state.send("items_total",
                   assignments=len(all_assignments),
                   quizzes=len(all_quizzes),
                   total=total_items)
        state.log(f"Total items: {total_items} ({len(all_assignments)} assignments + {len(all_quizzes)} quizzes)", "success")
        phase("context", 2)

        if total_items == 0:
            state.send("complete", success=True,
                       summary={"total": 0, "submitted": 0, "errors": 0, "run_id": run_id})
            state.status = "complete"
            return

        # ── 3. Classify assignments ───────────────────────────────────────────
        phase("classify", 2)
        from tools.classify_assignment import classify, SKIP, NEEDS_HUMAN, AUTOMATABLE_EXCEL, AUTOMATABLE_TEXT

        for item in all_assignments:
            cat, reason = classify(item)
            item["_category"] = cat
            name = item.get("name", f"Assignment {item['id']}")
            if cat == SKIP:
                state.log(f"Skipping (external platform): {name}", "warning")
                state.send("item_skipped", kind="assignment", name=name, reason=reason)
            elif cat == NEEDS_HUMAN:
                state.log(f"Needs human action: {name}", "warning")
                state.send("item_needs_human", kind="assignment", name=name, reason=reason)
            elif cat == AUTOMATABLE_EXCEL:
                state.log(f"Excel assignment: {name}")
            else:
                state.log(f"Text assignment: {name}")

        # Count only actionable items
        actionable = [a for a in all_assignments if a["_category"] not in (SKIP, NEEDS_HUMAN)]
        actionable_quizzes = all_quizzes  # quizzes are always actionable
        total_actionable = len(actionable) + len(actionable_quizzes)

        skipped    = len([a for a in all_assignments if a["_category"] == SKIP])
        need_human = len([a for a in all_assignments if a["_category"] == NEEDS_HUMAN])

        state.log(
            f"Classification: {len(actionable)} automatable, "
            f"{skipped} skipped (external), "
            f"{need_human} need human action",
            "success"
        )
        state.send("items_total",
                   assignments=len(actionable),
                   quizzes=len(actionable_quizzes),
                   total=total_actionable)
        phase("classify", 3)

        if total_actionable == 0:
            state.send("complete", success=True,
                       summary={"total": 0, "submitted": 0, "errors": 0, "run_id": run_id})
            state.status = "complete"
            return

        # ── 4. Fetch datasets + build prompts ─────────────────────────────────
        phase("prompts", 3)

        for item in actionable:
            name = item.get("name", f"Assignment {item['id']}")
            state.send("item_start", kind="assignment", name=name, action="prompt")
            state.log(f"Building prompt: {name}")

            if item["_category"] == AUTOMATABLE_EXCEL:
                # Fetch / synthesize dataset first
                ok, _, err = _run_tool(state, "fetch_attachments.py", [
                    "--course-id",     item["_course_id"],
                    "--assignment-id", item["id"],
                ], env)
                if not ok:
                    state.log(f"Dataset fetch note for {name}: {err[:120]}", "warning")

                # Find dataset path
                dataset_dir = BASE_DIR / f".tmp/attachments_{item['_course_id']}_{item['id']}"
                dataset_path = ""
                if dataset_dir.exists():
                    files = [f for f in dataset_dir.iterdir() if not f.name.startswith(".")]
                    if files:
                        dataset_path = str(files[0])

                ok, _, err = _run_tool(state, "build_prompt.py", [
                    "--course-id",     item["_course_id"],
                    "--assignment-id", item["id"],
                    "--run-id",        run_id,
                    "--excel",
                    *(["--dataset-path", dataset_path] if dataset_path else []),
                ], env)
            else:
                ok, _, err = _run_tool(state, "build_prompt.py", [
                    "--course-id",     item["_course_id"],
                    "--assignment-id", item["id"],
                    "--run-id",        run_id,
                ], env)

            item["_prompt_ok"] = ok
            if not ok:
                state.log(f"Prompt build failed for {name}: {err[:120]}", "warning")

        for item in actionable_quizzes:
            name = item.get("title", f"Quiz {item['id']}")
            state.send("item_start", kind="quiz", name=name, action="prompt")
            state.log(f"Building prompt: {name}")
            ok, _, err = _run_tool(state, "build_prompt.py", [
                "--course-id", item["_course_id"],
                "--quiz-id",   item["id"],
                "--run-id",    run_id,
            ], env)
            item["_prompt_ok"] = ok
            if not ok:
                state.log(f"Prompt build failed for {name}: {err[:120]}", "warning")

        phase("prompts", 4)

        # ── 5. Run LLM ────────────────────────────────────────────────────────
        phase("llm", 4)

        for item in actionable:
            if not item.get("_prompt_ok"):
                item["_llm_ok"] = False
                continue
            name = item.get("name", f"Assignment {item['id']}")
            state.send("item_start", kind="assignment", name=name, action="llm")
            state.log(f"Generating response: {name}")

            if item["_category"] == AUTOMATABLE_EXCEL:
                ok, _, err = _run_tool(state, "run_llm.py", [
                    "--assignment-id", item["id"],
                    "--run-id",        run_id,
                    "--excel",
                ], env)
            else:
                ok, _, err = _run_tool(state, "run_llm.py", [
                    "--assignment-id", item["id"],
                    "--run-id",        run_id,
                ], env)

            item["_llm_ok"] = ok
            if not ok:
                state.log(f"LLM failed for {name}: {err[:120]}", "warning")

        for item in actionable_quizzes:
            if not item.get("_prompt_ok"):
                item["_llm_ok"] = False
                continue
            name = item.get("title", f"Quiz {item['id']}")
            state.send("item_start", kind="quiz", name=name, action="llm")
            state.log(f"Generating response: {name}")
            ok, _, err = _run_tool(state, "run_llm.py", [
                "--quiz-id", item["id"], "--run-id", run_id,
            ], env)
            item["_llm_ok"] = ok
            if not ok:
                state.log(f"LLM failed for {name}: {err[:120]}", "warning")

        phase("llm", 5)

        # ── 6. Generate Excel workbooks ───────────────────────────────────────
        phase("excel", 5)

        excel_assignments = [a for a in actionable if a["_category"] == AUTOMATABLE_EXCEL]
        if excel_assignments:
            state.log(f"Generating {len(excel_assignments)} Excel workbook(s)…")

        for item in excel_assignments:
            name = item.get("name", f"Assignment {item['id']}")
            if not item.get("_llm_ok"):
                item["_excel_ok"] = False
                continue
            state.send("item_start", kind="assignment", name=name, action="excel")
            state.log(f"Building Excel workbook: {name}")

            dataset_dir = BASE_DIR / f".tmp/attachments_{item['_course_id']}_{item['id']}"
            dataset_path = ""
            if dataset_dir.exists():
                files = [f for f in dataset_dir.iterdir() if not f.name.startswith(".")]
                if files:
                    dataset_path = str(files[0])

            ok, _, err = _run_tool(state, "generate_excel.py", [
                "--assignment-id", item["id"],
                "--run-id",        run_id,
                *(["--dataset-path", dataset_path] if dataset_path else []),
            ], env)
            item["_excel_ok"] = ok
            if ok:
                state.log(f"Excel workbook ready: {name}", "success")
            else:
                state.log(f"Excel generation failed for {name}: {err[:120]}", "warning")

        phase("excel", 6)

        # ── 7. Submit ─────────────────────────────────────────────────────────
        phase("submit", 6)

        submitted  = 0
        errors     = 0
        completed  = 0

        for item in actionable:
            name = item.get("name", f"Assignment {item['id']}")
            if not item.get("_llm_ok"):
                errors += 1
                state.send("item_done", kind="assignment", name=name, success=False,
                           error="LLM response unavailable")
                completed += 1
                state.send("progress", current=completed, total=total_items,
                           percent=int(completed / max(total_actionable, 1) * 100))
                continue

            state.send("item_start", kind="assignment", name=name, action="submit")
            state.log(f"Submitting: {name}")
            ok, _, err = _run_tool(state, "submit_assignment.py", [
                "--course-id", item["_course_id"],
                "--assignment-id", item["id"],
                "--run-id", run_id,
            ], env, timeout=600)

            completed += 1
            if ok:
                submitted += 1
                state.send("item_done", kind="assignment", name=name, success=True)
                state.log(f"Submitted: {name}", "success")
            else:
                errors += 1
                state.send("item_done", kind="assignment", name=name,
                           success=False, error=err[:200])
                state.log(f"Submit failed — {name}: {err[:100]}", "error")

            state.send("progress", current=completed, total=total_items,
                       percent=int(completed / max(total_actionable, 1) * 100))

        for item in actionable_quizzes:
            name = item.get("title", f"Quiz {item['id']}")
            if not item.get("_llm_ok"):
                errors += 1
                state.send("item_done", kind="quiz", name=name, success=False,
                           error="LLM response unavailable")
                completed += 1
                state.send("progress", current=completed, total=total_actionable,
                           percent=int(completed / total_actionable * 100))
                continue

            state.send("item_start", kind="quiz", name=name, action="submit")
            state.log(f"Submitting quiz: {name}")
            ok, _, err = _run_tool(state, "submit_quiz.py", [
                "--course-id", item["_course_id"],
                "--quiz-id", item["id"],
                "--run-id", run_id,
            ], env, timeout=600)

            completed += 1
            if ok:
                submitted += 1
                state.send("item_done", kind="quiz", name=name, success=True)
                state.log(f"Submitted quiz: {name}", "success")
            else:
                errors += 1
                state.send("item_done", kind="quiz", name=name,
                           success=False, error=err[:200])
                state.log(f"Quiz submit failed — {name}: {err[:100]}", "error")

            state.send("progress", current=completed, total=total_actionable,
                       percent=int(completed / total_actionable * 100))

        phase("submit", 7)

        # ── 8. Grades & export ────────────────────────────────────────────────
        phase("grades", 7)
        state.log("Fetching auto-graded results…")

        ok, _, err = _run_tool(state, "fetch_grades.py", ["--run-id", run_id, "--once"], env)
        if not ok:
            state.log(f"Grade fetch note: {err[:120]}", "warning")

        state.log("Exporting results to CSV…")
        ok, _, err = _run_tool(state, "export_results.py",
                               ["--run-id", run_id, "--format", "csv"], env)
        if not ok:
            state.log(f"Export note: {err[:120]}", "warning")

        # Read final JSONL for results table
        benchmark_file = tmp_dir / f"benchmark_{run_id}.jsonl"
        result_items: list[dict] = []
        if benchmark_file.exists():
            with open(benchmark_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        try:
                            result_items.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass

        phase("grades", 8)
        state.send("results", items=result_items)
        state.send("complete", success=True, summary={
            "total":     total_actionable,
            "submitted": submitted,
            "errors":    errors,
            "run_id":    run_id,
        })
        state.log(f"Done — {submitted}/{total_items} submitted, {errors} error(s).", "success")
        state.status = "complete"

    except Exception as exc:
        import traceback
        state.log(f"Fatal: {exc}", "error")
        state.send("error", message=str(exc), traceback=traceback.format_exc())
        state.status = "error"

    finally:
        state.finish()


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("\n  Canvas Benchmark Runner")
    print("  ─────────────────────────────────────")
    print("  http://localhost:5050\n")
    app.run(debug=False, host="0.0.0.0", port=5050, threaded=True)
