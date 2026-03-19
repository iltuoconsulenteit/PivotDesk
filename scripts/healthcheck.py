from __future__ import annotations

import sys
import urllib.request


def main() -> int:
    if len(sys.argv) < 3:
        return 1

    host = sys.argv[1]
    port = sys.argv[2]
    url = f"http://{host}:{port}/health"

    try:
        with urllib.request.urlopen(url, timeout=2) as response:
            if response.status != 200:
                return 1

            body = response.read().decode("utf-8", "ignore").lower()

            if '"ok": true' in body or '"ok":true' in body or '"status": "ready"' in body:
                return 0

            return 0
    except Exception:
        return 1


if __name__ == "__main__":
    raise SystemExit(main())