from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def main() -> int:
    env_port = os.getenv("PIVOTDESK_PORT", "").strip()
    if env_port.isdigit():
        print(env_port)
        return 0

    config_path = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("config.json")

    try:
        if config_path.exists():
            data = json.loads(config_path.read_text(encoding="utf-8"))
            port = int(data.get("port", 8091))
            print(port)
            return 0
    except Exception:
        pass

    print(8091)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())