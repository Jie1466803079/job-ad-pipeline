"""Create .env from .env.example, or add the keys an existing .env is missing.

Never changes a value that is already set. A secret that is missing or empty gets a new random value.
Prints key names only, never values. Needs Python 3.9 or later and no packages, so it runs before
the virtualenv exists.

Usage: make env   (or: python3 scripts/make_env.py)
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path

SECRETS = ("MACHINE_API_KEY", "SESSION_SECRET", "WEBHOOK_SECRET", "N8N_ENCRYPTION_KEY")
SETTING = re.compile(r"^([A-Z][A-Z0-9_]*)=(.*)$")


def _key(line: str) -> str | None:
    match = SETTING.match(line)
    return match.group(1) if match else None


def _fill(line: str, generated: list[str]) -> str:
    """The line, with a random value when it is a secret that has none."""
    match = SETTING.match(line)
    if not match or match.group(1) not in SECRETS or match.group(2).strip():
        return line
    generated.append(match.group(1))
    return f"{match.group(1)}={secrets.token_hex(32)}"


def update_env(example: str, current: str | None) -> tuple[str, list[str], list[str]]:
    """The new .env text, the keys added to it, and the secrets given a random value.

    current is None when there is no .env yet. The example is then copied whole, comments included.
    """
    generated: list[str] = []
    if current is None:
        lines = [_fill(line, generated) for line in example.splitlines()]
        return "\n".join(lines) + "\n", [], generated
    lines = [_fill(line, generated) for line in current.splitlines()]
    present = {_key(line) for line in lines}
    missing = [line for line in example.splitlines() if _key(line) and _key(line) not in present]
    if missing:
        lines += ["", "# Added by make env from .env.example"] + [_fill(line, generated) for line in missing]
    return "\n".join(lines) + "\n", [_key(line) for line in missing], generated


def main(root: Path | None = None) -> None:
    root = root or Path(__file__).resolve().parents[1]
    env_path = root / ".env"
    current = env_path.read_text(encoding="utf-8") if env_path.exists() else None
    text, added, generated = update_env((root / ".env.example").read_text(encoding="utf-8"), current)
    if text != current:
        temporary = root / ".env.tmp"
        descriptor = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(text)
        os.replace(temporary, env_path)
    os.chmod(env_path, 0o600)
    if current is None:
        print("Created .env from .env.example.")
    elif added:
        print(f"Added to .env: {', '.join(added)}.")
    if generated:
        print(f"New random values for: {', '.join(generated)}.")
    if current is not None and not added and not generated:
        print(".env already has every key in .env.example.")


if __name__ == "__main__":
    main()
