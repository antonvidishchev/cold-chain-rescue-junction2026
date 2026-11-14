"""Explicit provisioning and fictional demo bootstrap: python -m app.cloud.bootstrap."""

import argparse
import json
import os
from pathlib import Path

from app.cloud.service import bootstrap_demo
from app.cloud.store import get_store


def main() -> None:
    parser = argparse.ArgumentParser(description="Initialize cloud storage and seed five fictional clinics explicitly")
    parser.add_argument("--settings", type=Path, help="Optional local.settings.json to load Values without overriding environment")
    args = parser.parse_args()
    if args.settings:
        values = json.loads(args.settings.read_text(encoding="utf-8"))["Values"]
        if not isinstance(values, dict) or any(not isinstance(k, str) or not isinstance(v, str) for k, v in values.items()):
            raise ValueError("settings Values must be a string-to-string object")
        for key, value in values.items():
            os.environ.setdefault(key, value)
    from app.cloud.media import initialize_media
    store = get_store()
    store.initialize()
    initialize_media()
    print(json.dumps(bootstrap_demo(store)))


if __name__ == "__main__":
    main()
