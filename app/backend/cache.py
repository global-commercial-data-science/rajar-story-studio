"""Local JSON cache for agent results, so angles and drafts are computed once per input.

Keys hash everything that changes the result (release, facts, model, request fields),
so new RAJAR figures or a different model never serve a stale answer.
"""

import hashlib
import json
import time
from pathlib import Path

from . import config

CACHE_DIR = Path(__file__).resolve().parents[1] / ".cache"


def make_key(kind, **parts):
    blob = json.dumps({"kind": kind, "model": f"{config.LLM_PROVIDER}:{config.LLM_MODEL}", **parts}, sort_keys=True, default=str)
    return f"{kind}_{hashlib.sha256(blob.encode()).hexdigest()[:20]}"


def get(key):
    path = CACHE_DIR / f"{key}.json"
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except (OSError, json.JSONDecodeError):
        return None


def put(key, value):
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    record = {"cached_at": time.strftime("%Y-%m-%d %H:%M"), "value": value}
    tmp = CACHE_DIR / f"{key}.json.tmp"
    tmp.write_text(json.dumps(record, default=str))
    tmp.replace(CACHE_DIR / f"{key}.json")
    return record


def facts_fingerprint(factset):
    """Changes whenever any published figure changes."""
    blob = json.dumps([(f.key, f.display, f.status) for f in factset.facts])
    return hashlib.sha256(blob.encode()).hexdigest()[:16]
