#!/usr/bin/env python
"""
PreToolUse hook: refuse a shell command that screenshots the app straight from
the real database.

This exists because a note didn't work. Twice in one session a UI verification
screenshot captured the user's actual medical record — once the imaging viewer
(a scanned requisition with a name, MRN and DOB burned into the pixels), once
the Timeline (a stub that silently missed, because the app calls 127.0.0.1 and
the stub matched localhost). After the first, the response was a warning written
into frontend/CLAUDE.md; it named one page, and the next slip was on another.

So this is a control instead of a reminder: any command that both drives a
browser screenshot AND reaches the live app is blocked, and the message points
at `verify/ui_shots.py`, which runs its own backend against a SYNTHETIC database
and empty media folders. Screenshots taken through it cannot contain the real
record no matter which page they point at.

Deliberately narrow, so it blocks the mistake and nothing else:
  * only Bash/PowerShell commands,
  * only when the command takes a screenshot (playwright's `.screenshot(`),
  * only when it also names a live app origin (:5173 / :8000, the real servers),
  * and NEVER when it is the harness itself, or targets the harness ports.

Exit 2 = block, with stderr shown to the model. Anything unexpected exits 0:
a broken guard that blocks every command would be worse than the risk it
guards, and the pattern match is the whole of its job.
"""

import json
import re
import sys

SHOOTS = re.compile(r"\.screenshot\s*\(|screenshot\s*=|--screenshot\b")
LIVE_APP = re.compile(r"localhost:5173|127\.0\.0\.1:5173|localhost:8000|127\.0\.0\.1:8000")
HARNESS = re.compile(r"ui_shots\.py|:5199|:8123|HEALTH_DB\s*=")

MESSAGE = """BLOCKED: this command screenshots the LIVE app, which renders the real
medical record — a picture of it then lives wherever the screenshot went.

Use the harness instead, which serves a synthetic database and empty media
folders, so no real record is present to capture:

    .venv/Scripts/python.exe verify/ui_shots.py --out shots \\
        home:/ metrics:/metrics profile:/profile?tab=immunizations

    # one element only:
    .venv/Scripts/python.exe verify/ui_shots.py --out shots rail:/metrics:.metric__rail

If you need to check something against the REAL data, read the DOM as text
(page.inner_text / eval_on_selector_all) instead of taking a picture, and
report only the specific fact you needed."""


def main() -> int:
    try:
        payload = json.load(sys.stdin)
    except Exception:
        return 0

    if payload.get("tool_name") not in ("Bash", "PowerShell"):
        return 0
    command = str(payload.get("tool_input", {}).get("command", ""))
    if not command:
        return 0

    if SHOOTS.search(command) and LIVE_APP.search(command) and not HARNESS.search(command):
        print(MESSAGE, file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
