#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
API_DIR = ROOT_DIR / "apps" / "api"
OUTPUT_PATH = ROOT_DIR / "packages" / "shared" / "schema" / "openapi.json"


def _ensure_test_env() -> None:
    os.environ.setdefault("TESTING", "true")
    os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./openapi_contract.db")
    os.environ.setdefault("LLM_PROVIDER", "mock")
    os.environ.setdefault("IMAGE_PROVIDER", "mock")
    os.environ.setdefault("TTS_PROVIDER", "mock")
    os.environ.setdefault("S3_ACCESS_KEY", "test-access-key")
    os.environ.setdefault("S3_SECRET_KEY", "test-secret-key")


def main() -> int:
    _ensure_test_env()
    sys.path.insert(0, str(API_DIR))

    from src.main import app

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(
        json.dumps(app.openapi(), ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"Wrote OpenAPI contract to {OUTPUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
