"""
gateway.py — the privacy gateway: the SINGLE chokepoint for every LLM call.

THE RULE: this is the only module in the project allowed to make a call to a
model provider — local or external. No other module (not narrate.py, not api.py,
not a future import path) may call a provider directly. Everything routes through
`complete()`.

Two paths, chosen by the engine — NOT by the caller. The caller picks an engine;
the gateway maps it to a destination from a fixed registry and enforces that
path, so a `hosted` call can never be routed through the friction-free local
side:

  * local    (in_program) — stays on the machine. No redaction or confirmation
             friction; still logged and engine-labeled.
  * external (hosted)             — full privacy machinery: an allowlist-built,
             scrubbed payload; a "here is exactly what I would send" preview; an
             explicit confirmation that must match the previewed bytes before
             anything is sent; enforced provider settings; and a local audit log.

Redaction is by construction: the gateway only ever accepts STRUCTURED fields
(`list[dict]`) and builds the outbound payload from an explicit per-task
allowlist. It has no parameter for raw text, so a raw document can never be sent
— and hosted extraction from a raw document is therefore impossible here by
design (such extraction must run locally).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import urllib.error
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable


# --------------------------------------------------------------------------- config

LOCAL = "local"
EXTERNAL = "external"

# Engine -> destination. FIXED here so a caller can never route a hosted call
# through the friction-free local path; the gateway decides and enforces it.
_ENGINE_DESTINATION = {
    "in_program": LOCAL,
    "hosted": EXTERNAL,
}

# Per-task allowlist of fields that MAY appear in an outbound payload. Anything
# not listed is excluded by construction (never copied), not stripped after the
# fact. The lab set is the charter's example: test name, value, unit, range.
_ALLOWLISTS: dict[str, set[str]] = {
    "summarize_labs": {"metric", "value", "unit", "ref_low", "ref_high"},
    "extract_labs": {"metric", "value", "unit", "ref_low", "ref_high"},
    "summarize_flags": {"metric", "kind", "severity", "message"},
    # explain_metric — the EXPORT handoff's bundle (assembled by
    # explain.assemble_explain_context; sent via the hosted path from api.py's
    # /export routes). The former local interpretation tier that also used this task
    # was removed as dead code, so hosted is now the ONLY caller. NOTE — this
    # allowlist filters only TOP-LEVEL keys; the export bundle's readings / findings
    # / thresholds carry sub-fields, so its PII-clean guarantee rests on the bundle
    # being assembled ONLY from observations/flags/thresholds (structural cleanliness,
    # proven by tests/test_export_gateway.py), not on this top-level filter.
    "explain_metric": {
        "metric", "unit", "n_readings", "readings", "engine_findings",
        "cited_thresholds", "personal_baseline_mean", "methodology_note",
        "latest_change", "personal_baseline_mode",
    },
    # export_metrics — the MULTI-metric export handoff (CLAUDE.md "Hypothesis floating &
    # multi-metric scope"). The bundle is {metrics: [per-metric explain_metric bundle...],
    # scope: label}, plus — for a FULL-PICTURE export — the non-metric context assembled by
    # picture.py. Same top-level-only filter caveat as explain_metric: each nested
    # per-metric bundle is PII-clean by construction (assembled only from observations/
    # flags/thresholds), so the guarantee rests on that structural cleanliness, not this
    # filter. `scope` is a plain label string (e.g. "Full health picture") — no PII.
    #
    # The context keys are listed INDIVIDUALLY rather than folded into one opaque
    # `context` blob on purpose: a single key would make this filter vacuous for the
    # entire addition, whereas naming each one means a future assembler that starts
    # emitting, say, `documents` is excluded by construction until someone deliberately
    # adds it here. `profile` carries sex + age + weight/height ONLY — picture.py consumes
    # the date of birth to compute age and never copies it, so no DOB can arrive.
    # `reports` is free clinician prose and is the one key with no structural guarantee:
    # it carries only text the user reviewed and edited in the preview (see _PROSE_FIELDS).
    "export_metrics": {
        "metrics", "scope",
        "profile", "conditions", "medications", "events", "imaging", "reports",
    },
}

# Enforced wherever a real hosted provider is eventually wired (see _hosted_call).
# Realistic individual posture: API tier, no training, shortest retention.
_PROVIDER_SETTINGS = {
    "tier": "api",
    "training": "disabled",
    "retention": "shortest-available",
}

_PLACEHOLDER_PROVIDER = "placeholder (no provider wired)"

# Local-only audit log; never transmitted. Gitignored.
_AUDIT_LOG = os.environ.get("GATEWAY_AUDIT_LOG", "gateway_audit.log")


# --------------------------------------------------------------------------- types

@dataclass
class LLMRequest:
    task: str                                  # keys the allowlist + labels the log
    engine: str                                # "in_program" | "hosted"
    fields: list[dict]                         # STRUCTURED data only — never raw text
    instruction: str = ""                      # static, developer-defined, PII-free
    local_runner: Callable[[list[dict]], str] | None = None  # in_program: on-machine compute
    # hosted only: which provider (e.g. "anthropic"/"openai") — a settings.py
    # selection the CALLER resolves and passes in; gateway.py stays ignorant of
    # the settings registry (module-boundary discipline, see the header). Falls
    # back to _PLACEHOLDER_PROVIDER when unset (e.g. the __main__ self-demo
    # below, which predates provider selection existing at all).
    provider: str | None = None


@dataclass
class Preview:
    task: str
    provider: str
    payload: list[dict]            # EXACTLY what would be sent (allowlisted + scrubbed)
    excluded_fields: list[str]     # input keys dropped by the allowlist
    redactions: list[dict]         # [{type, count}] removed by the scrubber
    provider_settings: dict        # enforced at send time
    confirmation_token: str        # sha256 of the canonical payload
    # The system instruction that will accompany `payload` — static, developer-defined
    # and PII-free, so it is NOT part of the token (which binds the DATA) and carries
    # none of the user's information. Surfaced anyway because the preview's promise is
    # "see what will be sent," and the instruction is half of what the provider receives:
    # it shapes the entire answer, so a user reviewing only the data cannot tell why the
    # response looks the way it does.
    instruction: str = ""


@dataclass
class GatewayResult:
    # "ok" | "needs_confirmation" | "refused" (bad/mismatched confirmation —
    # re-preview, the DATA changed) | "provider_error" (the confirmation was
    # valid but the provider call itself failed — re-preview won't help; a
    # deliberately DISTINCT status from "refused" so the two failure modes
    # aren't conflated at the API boundary).
    status: str
    engine: str                    # which engine handled it (for UI labelling)
    destination: str               # "local" | "external"
    output: str | None = None      # the text, when status == "ok"
    preview: Preview | None = None # when status == "needs_confirmation"
    reason: str | None = None      # when status == "refused"
    model: str | None = None       # served-model tag echoed by the hosted provider
    # Id of the audit-log entry this call wrote (external calls only; None for a
    # preview or a refusal, neither of which sends or audits). Lets a caller that
    # stores the RESPONSE elsewhere — api.py's export_results table — record which
    # send it belongs to, so "what left" and "what came back" can be shown together
    # instead of living in two unjoined records.
    audit_id: str | None = None


# --------------------------------------------------------------------------- redaction

# Belt-and-suspenders structured-PII patterns, run over the already-allowlisted
# payload's string values. NOTE: regex cannot reliably catch arbitrary names —
# the allowlist is the PRIMARY defense (names never appear in numeric lab
# fields); this layer catches structured identifiers that rode along in a string.
_PII_PATTERNS = [
    ("email", re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")),
    ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("phone", re.compile(r"\b(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b")),
    ("mrn", re.compile(r"\bMRN[:#]?\s*\w+", re.IGNORECASE)),
    ("date", re.compile(r"\b\d{4}-\d{2}-\d{2}\b|\b\d{1,2}/\d{1,2}/\d{2,4}\b")),
    ("address", re.compile(
        r"\b\d+\s+[A-Za-z0-9.\s]{2,}\s(?:St|Street|Ave|Avenue|Rd|Road|Blvd|Lane|Ln|Dr|Drive|Ct|Court)\b",
        re.IGNORECASE,
    )),
    ("physician", re.compile(r"\bDr\.?\s+[A-Z][a-z]+")),
    ("zip", re.compile(r"\b\d{5}(?:-\d{4})?\b")),
]


def _scrub_value(value):
    """Scrub one value if it's a string; non-strings (e.g. numeric lab values)
    pass through untouched. Returns (scrubbed_value, [type, ...] applied)."""
    if not isinstance(value, str):
        return value, []
    found: list[str] = []
    out = value
    for label, pat in _PII_PATTERNS:
        out, n = pat.subn(f"[REDACTED:{label}]", out)
        found.extend([label] * n)
    return out, found


# Per-task set of FREE-PROSE field names — keys whose value is human-written text with
# no field structure, so an identifier can sit anywhere inside it. The scrub reaches
# these AT ANY DEPTH; every other nested value passes through untouched.
#
# The depth limit is not laziness, it is correctness. Applying these patterns to every
# nested string would corrupt the data: `observed_on` is literally a "date" match, and a
# lab value that stringifies to five digits (10025.0) is literally a "zip" match — so a
# blanket recursion would redact the readings the export exists to send. Naming the prose
# fields keeps the structured bundle byte-identical while giving the free text the scrub
# the charter calls belt-and-suspenders. It IS only that: the charter concedes regex
# cannot catch an arbitrary name, which is exactly why report text is user-edited in the
# preview first (CLAUDE.md "The export handoff"). Note the cost inside prose — a
# comparison exam date in a report reads as [REDACTED:date], because the pattern that
# catches a stray date of birth cannot tell the two apart, and privacy wins that trade.
#
# `metric` is included so a nested metric name gets the same scrub the single-metric
# task's top-level one already gets — the observed `Benign Hematology ...` department-
# header injection rides that exact field.
_PROSE_FIELDS: dict[str, frozenset[str]] = {
    "export_metrics": frozenset({"text", "notes", "title", "metric"}),
}


def _scrub_prose(value, key: str, prose: frozenset[str]):
    """Walk a nested value, scrubbing only strings that sit under a prose KEY name.
    Returns (value, [type, ...]). Structure is rebuilt, never mutated in place."""
    if isinstance(value, dict):
        found: list[str] = []
        out = {}
        for k, v in value.items():
            out[k], f = _scrub_prose(v, k, prose)
            found.extend(f)
        return out, found
    if isinstance(value, list):
        found = []
        out = []
        for item in value:
            sv, f = _scrub_prose(item, key, prose)   # a list inherits its key's meaning
            out.append(sv)
            found.extend(f)
        return out, found
    if isinstance(value, str) and key in prose:
        return _scrub_value(value)
    return value, []


def _scrub(payload: list[dict], prose: frozenset[str] = frozenset()) -> tuple[list[dict], list[dict]]:
    counts: dict[str, int] = {}
    scrubbed = []
    for row in payload:
        new_row = {}
        for k, v in row.items():
            # Top-level strings are scrubbed unconditionally (unchanged); nested values
            # only where `prose` names the key, so a task that declares none behaves
            # exactly as before.
            sv, found = _scrub_value(v) if isinstance(v, str) else _scrub_prose(v, k, prose)
            new_row[k] = sv
            for label in found:
                counts[label] = counts.get(label, 0) + 1
        scrubbed.append(new_row)
    redactions = [{"type": t, "count": c} for t, c in sorted(counts.items())]
    return scrubbed, redactions


# --------------------------------------------------------------------------- payload

def _build_payload(task: str, fields: list[dict]) -> tuple[list[dict], list[str]]:
    """Project each field dict onto the task's allowlist by INCLUSION (copy only
    allowed keys), never by stripping. Returns (payload, sorted excluded keys)."""
    allow = _ALLOWLISTS.get(task)
    if allow is None:
        raise ValueError(f"No allowlist defined for task {task!r}")
    payload = [{k: v for k, v in row.items() if k in allow} for row in fields]
    excluded = sorted({k for row in fields for k in row if k not in allow})
    return payload, excluded


def _canonical(payload: list[dict]) -> str:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def _token(payload: list[dict]) -> str:
    """Integrity binding (not a secret): ties a confirmation to the exact bytes
    that were previewed, so what's confirmed == what's sent."""
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


# --------------------------------------------------------------------------- audit log

def _audit(entry: dict) -> str:
    """Append one line to the local-only audit log. Never transmitted. Returns the
    entry's `id` — a random per-entry key so a caller storing the RESPONSE elsewhere
    can point back at the exact send (see GatewayResult.audit_id). A random id rather
    than a timestamp: two entries can share a timestamp, and a payload hash would
    collide across identical re-sends, which are exactly the case worth telling apart.
    Entries written before this existed have no `id`; readers must treat it as
    optional."""
    entry_id = uuid.uuid4().hex
    line = {"ts": datetime.now(timezone.utc).isoformat(), "id": entry_id, **entry}
    with open(_AUDIT_LOG, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(line, default=str) + "\n")
    return entry_id


def read_external_audit(limit: int = 50) -> list[dict]:
    """The after-the-fact half of the charter's transparency rule: read the
    local-only audit log back and return the EXTERNAL entries (attempted or
    completed sends — an entry with an `error` key was attempted but no
    response was served), newest first. Read-only over a local file — no
    egress, no DB. Malformed or blank lines are skipped so one corrupt line
    can't hide the rest of the record; a missing log (nothing ever attempted)
    is an empty list, not an error."""
    try:
        with open(_AUDIT_LOG, encoding="utf-8") as fh:
            lines = fh.readlines()
    except OSError:
        return []
    entries: list[dict] = []
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        try:
            entry = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(entry, dict) and entry.get("destination") == EXTERNAL:
            entries.append(entry)
    entries.reverse()  # the log is append-only, so file order is oldest-first
    return entries[: max(0, limit)]


# --------------------------------------------------------------------------- engines

class HostedCallError(RuntimeError):
    """A hosted provider call failed in a way that must surface as a clean,
    honest error to the user — never a raw traceback, never a silent partial.
    Caught by complete(), never allowed to propagate past this module."""


# Anthropic Messages API — the wired provider (Phase B / #1 "PLAN OF RECORD"
# phase (c)). Model string is the single source here; VERIFY it against
# Anthropic's own GET /v1/models at build/release time rather than trusting a
# hardcoded guess (checked live 2026-07-09 — see ROADMAP.md "PLAN OF RECORD"
# for the verification ceremony). A future model bump is one line.
_ANTHROPIC_MODEL = "claude-sonnet-5"
_ANTHROPIC_API_KEY_ENV = "ANTHROPIC_API_KEY"
_ANTHROPIC_ENDPOINT = "https://api.anthropic.com/v1/messages"
_ANTHROPIC_VERSION = "2023-06-01"
# Output-token ceiling for a hosted call. Two things draw from it: claude-sonnet-5's
# adaptive thinking (used BY DEFAULT, no `thinking` param requested — confirmed live:
# a 987-token response included 632 thinking tokens) AND the visible output. The
# export task's output is short prose, but the PDF-import cleanup task returns a
# STRUCTURED JSON array that grows with the number of draft rows — a 22-row import
# plus thinking blew past the old 4096 ceiling and truncated with
# stop_reason="max_tokens" (surfaced cleanly by the guard below, never a silent
# partial). Sized generously so thinking + a large structured response both fit;
# billing is by tokens actually generated, so a high ceiling costs nothing when
# unused. (If a very large import ever truncates even this, chunk the cleanup
# payload rather than raising further.)
_ANTHROPIC_MAX_TOKENS = 16384

# Read timeout for the provider call, in seconds. Sized for the WORST realistic case,
# not the typical one: a full-picture export is ~50k input tokens and may generate up to
# _ANTHROPIC_MAX_TOKENS in reply, which takes MINUTES — the old 60s was tuned when the
# export was one metric capped at 12 readings, and became a routine failure once the
# payload grew to the full series across every metric. A generous ceiling costs nothing
# when unused (it's a timeout, not a delay); too low a one costs the whole send, since
# the request is not resumable and the provider has already done the work.
_ANTHROPIC_TIMEOUT_S = 600


def _hosted_error_message(status: int) -> str:
    """Maps an HTTP failure to a clean, provider-agnostic message. Deliberately
    does NOT surface the provider's raw error body — that's implementation
    detail, not something a user reviewing an export failure needs — but the
    STATUS CLASS (auth/billing/rate-limit/server) is real and actionable."""
    if status == 401:
        return "The external provider rejected the API key (unauthorized)."
    if status == 402:
        return "The external provider reports a billing issue on this account."
    if status == 429:
        return "The external provider is rate-limiting requests — try again shortly."
    if status >= 500:
        return "The external provider is temporarily unavailable (server error)."
    return f"The external provider returned an error (HTTP {status})."


def _anthropic_call(payload: list[dict], instruction: str) -> tuple[str, str | None]:
    """The ONLY network call to Anthropic — the sole seam other than the
    module docstring's chokepoint rule. Standard (non-enterprise) API-tier
    access already excludes training by default and applies Anthropic's
    shortest-available retention for this tier (~7 days, auto-deleted); no
    special header enforces this — it's the account-tier default, verified
    against current docs (see CLAUDE.md "The export handoff" — the provider
    bar; ROADMAP.md "PLAN OF RECORD" for the specifics). Raises
    HostedCallError with an honest message on any failure; never lets a raw
    exception or an empty/partial response reach the caller."""
    api_key = os.environ.get(_ANTHROPIC_API_KEY_ENV)
    if not api_key:
        raise HostedCallError(
            f"{_ANTHROPIC_API_KEY_ENV} is not set — the external provider can't be reached.")

    body = json.dumps({
        "model": _ANTHROPIC_MODEL,
        "max_tokens": _ANTHROPIC_MAX_TOKENS,
        "system": instruction,
        "messages": [{"role": "user", "content": _canonical(payload)}],
    }).encode("utf-8")
    req = urllib.request.Request(
        _ANTHROPIC_ENDPOINT, data=body, method="POST",
        headers={
            "x-api-key": api_key,
            "anthropic-version": _ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=_ANTHROPIC_TIMEOUT_S) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise HostedCallError(_hosted_error_message(e.code)) from e
    # A timeout while READING the response body raises a bare TimeoutError (== socket.
    # timeout), NOT a URLError — only a CONNECT timeout gets wrapped as URLError(reason=
    # timeout). The two are SIBLING subclasses of OSError (neither catches the other, so
    # this needs its own clause; their order relative to each other doesn't matter).
    # Without this clause a read timeout escapes every handler here, escapes complete()'s
    # `except HostedCallError`, and surfaces as an unhandled 500 with no CORS headers —
    # which the browser reports as an opaque "NetworkError", and which writes NO audit
    # entry even though the send was attempted and the bytes left the machine. That
    # silent-egress gap is why this catch is a correctness requirement, not merely a
    # nicer error message.
    except TimeoutError as e:
        raise HostedCallError(
            "The external provider did not respond in time. The data was sent, so it may "
            "still have been processed on their side — check the send record in Settings "
            "before retrying.") from e
    except urllib.error.URLError as e:
        raise HostedCallError(f"Network error reaching the external provider: {e.reason}") from e

    # A cut-off response (stop_reason "max_tokens") is worse than no response —
    # a mid-sentence fragment could misrepresent what the model actually
    # concluded. Treat it as a clean failure, never silently return a partial.
    if data.get("stop_reason") == "max_tokens":
        raise HostedCallError(
            "The external provider's response was cut off before completing — try again.")

    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    ).strip()
    if not text:
        raise HostedCallError("The external provider returned an empty response.")
    return text, data.get("model")


def _hosted_call(payload: list[dict], instruction: str, provider: str,
                 settings: dict) -> tuple[str, str | None]:
    """The sole external seam — the ONLY place a network call to an external
    provider may live. `settings` documents the enforced posture (API-tier,
    training, retention); for the wired provider that posture is the account-
    tier default (see _anthropic_call), not something toggled per-request
    here. Dispatches on `provider`; an unwired provider fails honestly rather
    than silently pretending to work."""
    if provider == "anthropic":
        return _anthropic_call(payload, instruction)
    raise HostedCallError(
        f"The '{provider}' provider isn't wired yet — select Anthropic in Settings.")


# --------------------------------------------------------------------------- entry point

def complete(req: LLMRequest, confirmation: str | None = None) -> GatewayResult:
    """The single chokepoint. Local engines run friction-free; the hosted engine
    returns a preview and only sends on a confirmation matching the previewed
    bytes. See module docstring for the rule."""
    destination = _ENGINE_DESTINATION.get(req.engine)
    if destination is None:
        return GatewayResult("refused", req.engine, "unknown", reason=f"Unknown engine {req.engine!r}.")

    # ---- LOCAL: nothing leaves the machine; no redaction/confirmation friction.
    # in_program is the only local engine (the ollama engine was removed with the
    # dead interpretation tier); it runs the caller's on-machine local_runner.
    if destination == LOCAL:
        if req.local_runner is None:
            return GatewayResult("refused", req.engine, LOCAL,
                                 reason="in_program engine requires a local_runner.")
        output = req.local_runner(req.fields)
        _audit({"task": req.task, "engine": req.engine, "destination": LOCAL, "model": None})
        return GatewayResult("ok", req.engine, LOCAL, output=output, model=None)

    # ---- EXTERNAL: allowlist -> scrub -> preview -> confirm -> send.
    try:
        payload, excluded = _build_payload(req.task, req.fields)
    except ValueError as e:
        # Fail closed: no allowlist for this task means we will not send anything.
        return GatewayResult("refused", req.engine, EXTERNAL,
                             reason=f"{e}; refusing to build an external payload.")
    payload, redactions = _scrub(payload, _PROSE_FIELDS.get(req.task, frozenset()))
    token = _token(payload)

    provider = req.provider or _PLACEHOLDER_PROVIDER

    if confirmation is None:
        return GatewayResult(
            "needs_confirmation", req.engine, EXTERNAL,
            preview=Preview(
                task=req.task,
                provider=provider,
                payload=payload,
                excluded_fields=excluded,
                redactions=redactions,
                provider_settings=dict(_PROVIDER_SETTINGS),
                confirmation_token=token,
                instruction=req.instruction,
            ),
        )

    if confirmation != token:
        return GatewayResult("refused", req.engine, EXTERNAL,
                             reason="Confirmation does not match the previewed payload; nothing sent.")

    # Confirmed and unchanged — the ONLY point an external send happens.
    try:
        output, served_model = _hosted_call(payload, req.instruction, provider, _PROVIDER_SETTINGS)
    except HostedCallError as e:
        # The send was ATTEMPTED (bytes may have left the machine) even though
        # it failed — audit the attempt honestly, with no served model (none
        # served it) and the failure reason, rather than pretending nothing
        # happened.
        audit_id = _audit({
            "task": req.task, "engine": req.engine, "provider": provider,
            "destination": EXTERNAL, "payload": payload,
            "provider_settings": dict(_PROVIDER_SETTINGS), "redactions": redactions,
            "error": str(e),
        })
        return GatewayResult("provider_error", req.engine, EXTERNAL, reason=str(e),
                             audit_id=audit_id)
    audit_id = _audit({
        "task": req.task, "engine": req.engine, "provider": provider,
        "model": served_model, "destination": EXTERNAL, "payload": payload,
        "provider_settings": dict(_PROVIDER_SETTINGS), "redactions": redactions,
    })
    return GatewayResult("ok", req.engine, EXTERNAL, output=output, model=served_model,
                         audit_id=audit_id)


# --------------------------------------------------------------------------- self-demo

if __name__ == "__main__":
    # Exercises the local path with no provider needed.
    print("== LOCAL (in_program) ==")
    r = complete(LLMRequest(
        task="summarize_flags", engine="in_program",
        fields=[{"metric": "hba1c", "message": "hba1c is 5.9, above the reference high of 5.6."}],
        local_runner=lambda fields: " ".join(f["message"] for f in fields),
    ))
    print(r.status, r.engine, r.destination, "->", r.output)

    print("\n== EXTERNAL (hosted) step 1: preview (NOT sent) ==")
    labs = [
        {"metric": "hba1c", "value": 5.9, "unit": "%", "ref_low": 4.0, "ref_high": 5.6,
         "observed_on": "2024-08-01", "patient_name": "Jane Doe", "mrn": "123456"},
        {"metric": "glucose drawn 08/01/2024", "value": 99, "unit": "mg/dL"},  # stray PII in a string
    ]
    r1 = complete(LLMRequest(task="summarize_labs", engine="hosted", fields=labs))
    print("status:", r1.status)
    print("would send:", r1.preview.payload)
    print("excluded by allowlist:", r1.preview.excluded_fields)
    print("redacted by scrubber:", r1.preview.redactions)
    print("token:", r1.preview.confirmation_token[:16], "...")

    print("\n== EXTERNAL step 2: confirm + send (placeholder) ==")
    r2 = complete(LLMRequest(task="summarize_labs", engine="hosted", fields=labs),
                  confirmation=r1.preview.confirmation_token)
    print(r2.status, "->", r2.output)

    print("\n== refusal on a non-matching confirmation ==")
    r3 = complete(LLMRequest(task="summarize_labs", engine="hosted", fields=labs),
                  confirmation="not-the-token")
    print(r3.status, "-", r3.reason)

    print("\naudit log ->", _AUDIT_LOG)
