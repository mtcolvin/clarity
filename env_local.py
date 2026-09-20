"""
env_local.py — load a gitignored `.env.local` file into os.environ at startup.

Why this exists (billing/scoping, not a secrets store upgrade): the export
handoff's provider key (`ANTHROPIC_API_KEY`, read by gateway._anthropic_call
from the environment at call time) must be visible to THIS backend process
only. Setting it as a global Windows env var would leak it into every other
process on the machine — including Claude Code, which bills coding sessions
to the metered API instead of the user's subscription if it adopts the key.
A project-local, gitignored file that only this process reads keeps the
key's blast radius to the app.

Posture: stdlib only; values are never logged, stored in the DB, or returned
by any API response (same rule as $OLLAMA_HOST — see CLAUDE.md "narrate.py":
secrets stay in env). A variable already present in the environment WINS over
the file, so a deliberate per-shell override still works.

Format: one KEY=VALUE per line; blank lines and `#` comments ignored; an
optional single layer of matching quotes around VALUE is stripped. Keys must
look like environment variable names ([A-Za-z_][A-Za-z0-9_]*). Anything else
is skipped silently — this is a five-line convenience, not a dotenv clone.
"""

from __future__ import annotations

import os
import re

_KEY_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

DEFAULT_FILENAME = ".env.local"


def load_env_local(path: str = DEFAULT_FILENAME) -> int:
    """Merge KEY=VALUE lines from `path` into os.environ (existing env wins).

    Returns the number of variables actually set. A missing file is a normal
    no-op (0) — the file is optional by design. Never logs or returns values.
    """
    try:
        with open(path, encoding="utf-8") as f:
            lines = f.readlines()
    except OSError:
        return 0

    loaded = 0
    for line in lines:
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        if not _KEY_RE.fullmatch(key):
            continue
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
            value = value[1:-1]
        if key in os.environ:  # a deliberately-set shell var always wins
            continue
        if value:  # a blank placeholder line (KEY=) sets nothing
            os.environ[key] = value
            loaded += 1
    return loaded
