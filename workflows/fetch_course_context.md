# Fetch Course Context

## Objective
Pull all course material (syllabus, pages, modules) for a given course and cache it for prompt assembly.

## Required Inputs
- `course_id` (from `fetch_courses.py` output or Canvas URL)

## Steps

```bash
python tools/fetch_course_context.py --course-id <course_id>
```

Output: `.tmp/context_<course_id>.json`

Contents:
- `syllabus_text`: plain text, truncated to 4000 chars
- `pages[]`: title + body excerpt per page
- `modules[]`: module names and item titles

## When to Run
- Once per course before any benchmark run
- Re-run to refresh if course content has been updated
- Does NOT need to re-run before every assignment — cached context is reused

## Truncation Logic
The syllabus is truncated to `4000` characters (~1000 tokens) to leave room for assignment descriptions and rubrics within the LLM context budget.

If the syllabus is empty (some instructors don't populate it), the context will fall back to module descriptions. Check `pages` and `modules` in the output JSON to verify meaningful content exists.

## Edge Cases
- **Empty syllabus**: normal — the prompt builder will use module structure instead
- **HTML-heavy pages**: BeautifulSoup strips all tags; output is plain text
- **Private pages**: Canvas may return 403 on restricted pages — these are silently skipped
- **Large courses**: pagination is handled automatically; all pages and modules are fetched
