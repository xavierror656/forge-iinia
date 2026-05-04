"""Compare keys in .env against .env.example.

Fails when .env defines a key that's not documented in .env.example, or
when .env is missing a key that .env.example marks as present (the
example is the schema).

Run as a pre-commit hook or by hand:

    python scripts/check_env_keys.py
"""

from __future__ import annotations

import sys
from pathlib import Path


def keys_in(path: Path) -> set[str]:
    if not path.exists():
        return set()
    out: set[str] = set()
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key = line.split("=", 1)[0].strip()
        if key:
            out.add(key)
    return out


def main() -> int:
    repo = Path(__file__).resolve().parent.parent
    example = keys_in(repo / ".env.example")
    actual = keys_in(repo / ".env")

    if not actual:
        return 0  # no .env on this machine; nothing to compare

    extra = actual - example
    missing = example - actual

    problems: list[str] = []
    if extra:
        problems.append(f".env has keys not in .env.example: {sorted(extra)}")
    if missing:
        problems.append(f".env.example has keys missing from .env: {sorted(missing)}")

    if problems:
        for problem in problems:
            print(f"env-drift: {problem}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
