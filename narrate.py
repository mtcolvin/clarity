"""
narrate.py — the optional "narrate" half of detect-deterministically / narrate.

Turns the Flag objects the deterministic engine (analysis.py) already produced
into plain language. It does NO detection and NO math: every number, threshold,
and slope is decided upstream and arrives finished inside `Flag.message`; this
module only rephrases. It touches no SQL and never imports the detectors' logic.

It does NOT talk to any model provider directly — the one call it makes (the
template's in_program path) goes through the privacy gateway (gateway.py), the
single chokepoint, which runs it locally and enforces the privacy machinery.

Narration is the deterministic, no-model `TemplateSummarizer` (runs in-program
via the gateway's local path — nothing leaves the machine, can't invent
anything). The former swappable local-model option (`OllamaSummarizer`,
engine="ollama") was REMOVED as a QoL cleanup — it added a model dependency for
a rephrase the template already does on-device. Summarization is therefore
on-device-only; a hosted engine is reserved for the separate export handoff, not
this path.

The REASONING counterpart lives in explain.py (the sanctioned interpretation tier,
which may reason around the engine's findings and raise questions); narrate stays
restate-only and never interprets.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Protocol

from analysis import Flag
from gateway import LLMRequest, complete


@dataclass
class SummaryResult:
    """The result of a summarization call, carried as one object to the API
    boundary (mirrors gateway.GatewayResult). `engine` is always "in_program"
    now. `model`/`fallback_reason` are RETAINED (always None) so SummaryOut's
    shape and the /summary route stay unchanged — they existed to distinguish an
    Ollama run and its template fallback, both gone with the Ollama removal."""
    text: str
    engine: str                          # always "in_program" (Ollama removed)
    model: str | None = None             # vestigial (always None)
    fallback_reason: str | None = None   # vestigial (always None)


# Appended in code (never model-generated) so the caveat is always present and
# exact, whichever summarizer ran.
DISCLAIMER = (
    "This is a plain-language summary of automated findings, not a diagnosis — "
    "discuss anything concerning with a clinician."
)

_EMPTY = "Nothing notable stood out in these readings. " + DISCLAIMER


class Summarizer(Protocol):
    """The swappable interface: finished Flags in, `(text, served_model)` out.
    Every summarizer returns the SAME tuple shape — `served_model` is the model
    tag that actually served (Ollama echoes one) or None for engines that have
    no served model (the deterministic template). The uniform contract lets the
    caller unpack both without knowing the concrete type."""

    name: str

    def summarize(self, flags: list[Flag]) -> tuple[str, str | None]: ...


# The fields the gateway is allowed to see for this task (must stay within the
# `summarize_flags` allowlist in gateway.py).
def _fields(flags: list[Flag]) -> list[dict]:
    return [
        {"metric": f.metric, "kind": f.kind, "severity": f.severity, "message": f.message}
        for f in flags
    ]


def _stitch(fields: list[dict]) -> str:
    """Deterministic prose body from the field dicts — no model. Runs on-machine
    via the gateway's in_program path; reuses the engine's own message text so it
    can never invent anything."""
    order = {"high": 0, "watch": 1, "info": 2}
    by_metric: dict[str, list[dict]] = defaultdict(list)
    for row in fields:
        by_metric[row["metric"]].append(row)
    parts = []
    for metric in sorted(by_metric):
        rows = sorted(by_metric[metric], key=lambda r: order.get(r["severity"], 9))
        n = len(rows)
        sentences = " ".join(r["message"] for r in rows)
        parts.append(f"For {metric}, {n} finding{'s' if n != 1 else ''} stood out. {sentences}")
    return " ".join(parts)


class TemplateSummarizer:
    """Deterministic baseline — no model. Runs through the gateway's in_program
    local path (logged + engine-labelled), stitching the engine's own messages."""

    name = "in_program"

    def summarize(self, flags: list[Flag]) -> tuple[str, str | None]:
        """Returns (text, None) — the template has no served model, but conforms
        to the uniform Summarizer tuple contract so callers unpack uniformly."""
        if not flags:
            return _EMPTY, None
        res = complete(LLMRequest(
            task="summarize_flags", engine="in_program",
            fields=_fields(flags), local_runner=_stitch,
        ))
        return res.output + " " + DISCLAIMER, None


def summarize_with_engine(flags: list[Flag], engine: str = "in_program") -> SummaryResult:
    """Narrate the finished flags with the on-device deterministic template —
    local, no model, no network (the strongest privacy posture, and now the ONLY
    engine: the local-Ollama option was removed, a QoL cleanup, since it added a
    model dependency for a rephrase the template already does on-device). The
    `engine` parameter is retained so the caller's resolved-setting plumbing
    (api.py reads the persisted summarizer_engine) is unchanged; it's always the
    template today. Returns a SummaryResult; `model`/`fallback_reason` stay None
    (they existed to distinguish an Ollama run and its fallback — both gone)."""
    if not flags:
        return SummaryResult(text=_EMPTY, engine="in_program")
    text, _ = TemplateSummarizer().summarize(flags)
    return SummaryResult(text=text, engine="in_program")


def summarize(flags: list[Flag], engine: str = "in_program") -> str:
    """Clean entry point matching the design contract: Flag list -> plain text."""
    return summarize_with_engine(flags, engine).text
