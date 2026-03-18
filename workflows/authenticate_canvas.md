# Authenticate Canvas

## Objective
Generate a Canvas API access token and verify it works.

## Required Inputs
- Canvas institution URL (e.g., `canvas.university.edu`)

## Steps

### 1. Generate an access token
1. Log into Canvas in your browser
2. Go to: **Account → Settings → Approved Integrations**
3. Click **+ New Access Token**
4. Set purpose: `AI Benchmark Research`
5. Leave expiry blank (tokens do not expire by default unless your institution enforces it)
6. Click **Generate Token** and copy it immediately — it is shown only once

### 2. Set environment variables
Add to `.env`:
```
CANVAS_DOMAIN=canvas.youruniversity.edu
CANVAS_TOKEN=<paste token here>
```
Do NOT include `https://` or a trailing slash in `CANVAS_DOMAIN`.

### 3. Verify auth
```bash
python tools/fetch_courses.py
```
Expected: prints a table of your active courses.

If you get a 401 error → token is wrong or expired. Regenerate it.
If you get a 404 error → `CANVAS_DOMAIN` is incorrect.

## Edge Cases
- **Institution SSO**: Some schools disable personal access tokens and require OAuth2. If token generation is unavailable, contact your Canvas admin.
- **Token expiry**: If your institution sets a token expiry, regenerate before each benchmark run and update `.env`.
- **Domain variations**: Some institutions use `elearning.uni.edu` or `lms.uni.edu` — use the exact hostname from your Canvas browser URL.
