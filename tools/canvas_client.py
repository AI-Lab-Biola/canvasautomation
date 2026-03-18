"""
canvas_client.py — Base HTTP client for the Canvas LMS API.

All other tools import CanvasClient from here. Handles:
  - Bearer token auth
  - Automatic pagination (follows Link: rel="next" headers)
  - Proactive rate limiting (5 req/s by default)
  - Exponential backoff on 429/403
"""

import os
import re
import time
import requests
from dotenv import load_dotenv

load_dotenv()


class CanvasClient:
    def __init__(self):
        domain = os.getenv("CANVAS_DOMAIN")
        token = os.getenv("CANVAS_TOKEN")
        if not domain or not token:
            raise EnvironmentError(
                "CANVAS_DOMAIN and CANVAS_TOKEN must be set in .env"
            )
        self.base_url = f"https://{domain}/api/v1"
        self.session = requests.Session()
        self.session.headers.update({"Authorization": f"Bearer {token}"})
        self._req_interval = 1.0 / float(os.getenv("CANVAS_REQUESTS_PER_SECOND", "5"))
        self._last_request_time = 0.0

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _throttle(self):
        elapsed = time.monotonic() - self._last_request_time
        wait = self._req_interval - elapsed
        if wait > 0:
            time.sleep(wait)
        self._last_request_time = time.monotonic()

    def _check_rate_limit_header(self, response):
        remaining = response.headers.get("X-Rate-Limit-Remaining")
        if remaining is not None and float(remaining) < 10:
            time.sleep(2)

    def _request(self, method, path, retries=3, **kwargs):
        url = f"{self.base_url}{path}" if path.startswith("/") else path
        for attempt in range(retries):
            self._throttle()
            resp = self.session.request(method, url, **kwargs)
            self._check_rate_limit_header(resp)

            if resp.status_code in (429, 403):
                wait = 2 ** attempt
                print(f"[canvas_client] Rate limited ({resp.status_code}), waiting {wait}s...")
                time.sleep(wait)
                continue

            if not resp.ok:
                raise RuntimeError(
                    f"Canvas API error {resp.status_code} on {method} {url}: {resp.text[:300]}"
                )
            return resp

        raise RuntimeError(f"Canvas API failed after {retries} retries: {method} {url}")

    @staticmethod
    def _next_url(response):
        link_header = response.headers.get("Link", "")
        for part in link_header.split(","):
            if 'rel="next"' in part:
                match = re.search(r"<([^>]+)>", part)
                if match:
                    return match.group(1)
        return None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get(self, path, params=None):
        """Single GET request. Returns parsed JSON."""
        resp = self._request("GET", path, params=params or {})
        return resp.json()

    def get_all(self, path, params=None):
        """Paginated GET. Returns flat list of all items across all pages."""
        p = dict(params or {})
        p.setdefault("per_page", 100)
        results = []
        resp = self._request("GET", path, params=p)
        data = resp.json()
        results.extend(data if isinstance(data, list) else [data])
        next_url = self._next_url(resp)
        while next_url:
            resp = self._request("GET", next_url)
            data = resp.json()
            results.extend(data if isinstance(data, list) else [data])
            next_url = self._next_url(resp)
        return results

    def post(self, path, data=None, json=None):
        """POST request. Returns parsed JSON."""
        resp = self._request("POST", path, data=data, json=json)
        return resp.json()

    def put(self, path, data=None, json=None):
        """PUT request. Returns parsed JSON."""
        resp = self._request("PUT", path, data=data, json=json)
        return resp.json()

    def post_raw(self, url, data=None, files=None, headers=None):
        """
        Raw POST — used for direct S3 uploads (no Authorization header).
        Does NOT go through the Canvas base URL.
        """
        self._throttle()
        resp = requests.post(url, data=data, files=files, headers=headers or {})
        if not resp.ok:
            raise RuntimeError(
                f"Raw POST failed {resp.status_code}: {resp.text[:300]}"
            )
        return resp
