"""Trigger the authenticated daily-report check on the QOR web service."""
import os
import sys
from urllib.parse import urlparse

import httpx


def main():
    url = os.getenv("QOR_DAILY_REPORT_TRIGGER_URL", "").strip()
    token = os.getenv("QOR_DAILY_REPORT_TRIGGER_TOKEN", "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.netloc or not token:
        print("Daily report trigger is not configured", file=sys.stderr)
        return 2
    if parsed.path.rstrip("/") != "/api/internal/daily-report/run":
        print("Daily report trigger URL path is invalid", file=sys.stderr)
        return 2
    try:
        response = httpx.post(url, headers={"Authorization": f"Bearer {token}"}, timeout=30)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        print(f"Daily report trigger failed ({type(exc).__name__})", file=sys.stderr)
        return 1
    try:
        result = response.json()
    except ValueError:
        print("Daily report trigger returned invalid JSON", file=sys.stderr)
        return 1
    print(f"Daily report check complete: {result.get('sent', 0)} sent")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
