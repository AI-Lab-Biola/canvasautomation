"""
generate_excel.py — Execute LLM-generated Python code to produce an Excel workbook.

Flow:
  1. Read the LLM response JSON which contains "excel_code" and "reflection_text".
  2. Write excel_code to a temp .py file.
  3. Execute it in a subprocess with EXCEL_OUTPUT_PATH and DATASET_PATH env vars.
  4. Return the path to the generated .xlsx file.

The generated code is expected to:
  - import pandas / openpyxl
  - read the dataset from os.environ["DATASET_PATH"]
  - write the workbook to os.environ["EXCEL_OUTPUT_PATH"]

Usage:
  python tools/generate_excel.py --assignment-id 904598 --run-id <run_id> --dataset-path <path>
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

BASE_DIR = Path(__file__).parent.parent


def generate_excel(assignment_id: int, run_id: str, dataset_path: str | None = None) -> tuple[str, str]:
    """
    Execute LLM-generated code to produce the .xlsx file.

    Returns (excel_path, reflection_text).
    Raises RuntimeError if code execution fails after retries.
    """
    response_path = BASE_DIR / f".tmp/responses_{run_id}/{assignment_id}.json"
    if not response_path.exists():
        raise FileNotFoundError(f"LLM response not found: {response_path}")

    with open(response_path) as f:
        resp = json.load(f)

    excel_code      = resp.get("excel_code", "")
    reflection_text = resp.get("reflection_text", "")

    if not excel_code:
        raise ValueError(f"No excel_code found in response for assignment {assignment_id}")

    out_path  = BASE_DIR / f".tmp/responses_{run_id}/{assignment_id}.xlsx"
    code_path = BASE_DIR / f".tmp/responses_{run_id}/{assignment_id}_gen.py"

    _write_code(code_path, excel_code)

    env = os.environ.copy()
    env["EXCEL_OUTPUT_PATH"] = str(out_path)
    env["DATASET_PATH"]      = str(dataset_path) if dataset_path else ""

    success, stderr = _execute_code(code_path, env)

    if not success:
        print(f"[generate_excel] First attempt failed. Trying to fix...\n{stderr[:400]}")
        fixed_code = _attempt_fix(excel_code, stderr)
        if fixed_code != excel_code:
            _write_code(code_path, fixed_code)
            success, stderr = _execute_code(code_path, env)

    if not success:
        raise RuntimeError(
            f"Excel generation failed for assignment {assignment_id} after retry.\n{stderr[:500]}"
        )

    if not out_path.exists():
        raise RuntimeError(f"Code ran successfully but no .xlsx was created at {out_path}")

    print(f"[generate_excel] Workbook written → {out_path}")
    return str(out_path), reflection_text


def _write_code(path: Path, code: str):
    """Write the Python code to a file, stripping markdown fences if present."""
    # Strip ```python ... ``` fences
    code = re.sub(r"^```(?:python)?\s*\n", "", code.strip(), flags=re.MULTILINE)
    code = re.sub(r"\n```\s*$", "", code.strip(), flags=re.MULTILINE)
    with open(path, "w") as f:
        f.write(code)


def _execute_code(code_path: Path, env: dict) -> tuple[bool, str]:
    """Run code_path as a Python subprocess. Returns (success, stderr)."""
    try:
        result = subprocess.run(
            ["python3", str(code_path)],
            capture_output=True,
            text=True,
            env=env,
            cwd=str(BASE_DIR),
            timeout=120,
        )
        if result.returncode != 0:
            return False, result.stderr + result.stdout
        return True, ""
    except subprocess.TimeoutExpired:
        return False, "Timeout: code took more than 120 seconds"
    except Exception as exc:
        return False, str(exc)


def _attempt_fix(code: str, error: str) -> str:
    """
    Apply simple heuristic fixes for common LLM code errors.
    More complex errors need a re-prompt (handled upstream if needed).
    """
    import re

    # Fix 1: missing openpyxl import when ExcelWriter is used
    if "openpyxl" in error and "import openpyxl" not in code:
        code = "import openpyxl\n" + code

    # Fix 2: xlsxwriter used instead of openpyxl
    if "xlsxwriter" in code:
        code = code.replace(
            "engine='xlsxwriter'",
            "engine='openpyxl'",
        )

    # Fix 3: EXCEL_OUTPUT_PATH not imported from env
    if "EXCEL_OUTPUT_PATH" in error and "os.environ" not in code:
        code = "import os\n" + code

    # Fix 4: MergedCell has no column_letter — use get_column_letter(col[0].column)
    if "MergedCell" in error and "column_letter" in error:
        code = re.sub(r'\bcol\[0\]\.column_letter\b', 'get_column_letter(col[0].column)', code)
        if "get_column_letter" in code and "from openpyxl.utils import get_column_letter" not in code:
            code = "from openpyxl.utils import get_column_letter\n" + code

    # Fix 5: scipy not installed — drop the import so the except-block fallback activates.
    # The generated code typically wraps scipy_stats.mode in try/except Exception, so
    # removing the import causes a NameError that the fallback catches.
    # If no try/except exists, replace the call directly with a pandas equivalent.
    if "No module named 'scipy'" in error:
        code = re.sub(r'[ \t]*from scipy import[^\n]*\n', '', code)
        code = re.sub(r'[ \t]*import scipy[^\n]*\n', '', code)
        if "scipy_stats" in code and "except" not in code:
            # No fallback present — replace the call with a pandas equivalent
            code = re.sub(
                r'scipy_stats\.mode\(([^,)]+(?:\(\))?),?\s*(?:keepdims=\w+)?\)(?:\.mode\[\d+\])?',
                r'\1.mode().iloc[0] if not \1.mode().empty else float("nan")',
                code,
            )

    return code


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Generate Excel workbook from LLM code")
    parser.add_argument("--assignment-id", type=int, required=True)
    parser.add_argument("--run-id",        required=True)
    parser.add_argument("--dataset-path",  default=None)
    args = parser.parse_args()

    excel_path, reflection = generate_excel(args.assignment_id, args.run_id, args.dataset_path)
    print(f"Excel: {excel_path}")
    print(f"Reflection ({len(reflection)} chars)")
