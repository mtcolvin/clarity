"""
settings.py — user-adjustable settings: the DEFINITIONS layer.

Sits above db.py (raw key/value storage) and beside analysis.py (the named
constants that are the authoritative defaults). This module ties a key to its
default, type, label, description, and — for the future — its bounds, in one
registry. db.py stays ignorant of what a key means; analysis.py stays pure (no
DB). The API resolves a value here and passes it into the engine as a kwarg.

Resolution precedence: a value stored in the settings table OVERRIDES the code
constant; an absent key falls back to the constant. So settings tune, constants
backstop — the app works even when the table is empty.

THIS build exposes three DISPLAY-VOLUME settings only (how much is shown, never
what counts as a flag). The SettingDef carries optional `minimum`/`maximum`
fields that stay None here; the next pass adds bounded, safety-relevant knobs
(baseline z-thresholds, noise-gate fractions) by filling them in — no schema,
model, or component change needed. Bound ENFORCEMENT is deliberately not built
yet (see apply_updates): this pass only type-validates.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable

import db
from analysis import (
    CHANGES_RECENT_DAYS,
    ANOMALY_DETAIL_CAP,
    ANOMALY_CONDENSE_THRESHOLD,
    PERSONAL_BASELINE_SUGGEST_MIN_FRACTION,
    PERSONAL_BASELINE_SUGGEST_MIN_READINGS,
)


# The persisted-setting key that selects which engine narrates the summary. This
# REPLACES the former $SUMMARIZER env-only selection: the persisted value is the
# source of truth, and env is consulted only to SEED the initial value (see
# _env_seed_engine + seed_defaults). Secrets/endpoints (OLLAMA_HOST/_MODEL, any
# future provider key) stay in env — only the *selection* moves to settings.
SUMMARIZER_ENGINE_KEY = "summarizer_engine"


def _env_seed_engine() -> str:
    """The engine to seed when nothing is persisted yet. With Ollama removed,
    on-device 'in_program' is the only summarizer engine — a constant now. (The
    legacy $SUMMARIZER env var is no longer consulted; a stale $SUMMARIZER=ollama
    is simply ignored.)"""
    return "in_program"


@dataclass(frozen=True)
class SettingDef:
    """One adjustable setting's definition. `default` is the code constant that
    backstops it; `cast` types the stored text on read (int now, float later).
    `minimum`/`maximum` are the seam for future bounded (safety-relevant) knobs —
    None means unbounded, and the panel renders min/max only when present."""
    key: str
    default: int | float | str
    cast: Callable[[str], int | float | str]
    label: str
    description: str
    minimum: float | None = None
    maximum: float | None = None
    step: float | None = None        # UI input step (1 for integer settings)
    unit: str | None = None          # optional display suffix, e.g. "days"
    group: str | None = None         # panel section heading; settings sharing a
                                     # group render together under one label
    # For a CATEGORICAL (enum) setting: the closed allowlist of choices, each
    # {value, label, description}. None means a numeric setting (int/float). The
    # `value`s here are the ONLY values the server accepts (see _coerce/resolve),
    # and the panel renders a picker instead of a number input.
    options: list[dict] | None = None

    @property
    def type_name(self) -> str:
        if self.options is not None:
            return "enum"
        return "int" if self.cast is int else "float"


# The registry — the single source of truth for these settings. Defaults are the
# named constants from analysis.py (imported above), so there is exactly one
# place each default lives. Add a setting by adding an entry; a future bounded
# one just fills minimum/maximum.
SETTINGS: list[SettingDef] = [
    SettingDef(
        key="changes_recent_days",
        default=CHANGES_RECENT_DAYS,
        cast=int,
        label="Changes digest: recency window",
        description=(
            "Only surface a metric in the changes digest when its latest reading "
            "is within this many days. Larger shows older movement; smaller keeps "
            "it to the most recent results."
        ),
        step=1,
        unit="days",
        group="Display volume",
    ),
    SettingDef(
        key="anomaly_detail_cap",
        default=ANOMALY_DETAIL_CAP,
        cast=int,
        label="Anomaly panel: max readings per group",
        description=(
            "How many individual readings each historical-anomaly group lists "
            "before the rest are folded into its summary. Display only — does not "
            "change which readings are flagged."
        ),
        step=1,
        unit="readings",
        group="Display volume",
    ),
    SettingDef(
        key="anomaly_condense_threshold",
        default=ANOMALY_CONDENSE_THRESHOLD,
        cast=int,
        label="Anomaly panel: condense threshold",
        description=(
            "An anomaly group with at least this many readings collapses to a "
            "single summary line instead of listing each one. Display only."
        ),
        step=1,
        unit="readings",
        group="Display volume",
    ),
    # Suggestion-trigger thresholds for personal-baseline mode. Purely statistical
    # — they gate when the app OFFERS personal-baseline tracking for a metric; they
    # do NOT change what counts as a flag (you still confirm the switch).
    SettingDef(
        key="personal_baseline_suggest_min_fraction",
        default=PERSONAL_BASELINE_SUGGEST_MIN_FRACTION,
        cast=float,
        label="Suggest when out-of-range fraction exceeds",
        description=(
            "Offer personal-baseline tracking for a metric whose readings fall "
            "outside the lab reference range more than this fraction of the time. "
            "Only gates the suggestion — you still confirm the switch."
        ),
        step=0.05,
        unit="fraction",
        group="Personal-baseline suggestions",
    ),
    SettingDef(
        key="personal_baseline_suggest_min_readings",
        default=PERSONAL_BASELINE_SUGGEST_MIN_READINGS,
        cast=int,
        label="…with at least this many readings",
        description=(
            "Require at least this many numeric readings that carry a lab range "
            "before offering personal-baseline tracking, so a metric isn't "
            "suggested on too little data."
        ),
        step=1,
        unit="readings",
        group="Personal-baseline suggestions",
    ),
    # Categorical (enum) setting — selects which engine narrates the summary. Was
    # $SUMMARIZER (env-only); now persisted, with env seeding the initial value
    # via _env_seed_engine(). Both options keep all data ON THE MACHINE: the
    # default makes no model/network call at all; Ollama runs a local model. A
    # 'hosted' option is deliberately NOT exposed here, permanently — CLAUDE.md
    # "The export handoff" states summarization stays local-only; only the
    # separate export task (export_provider below) may reach a hosted engine.
    SettingDef(
        key=SUMMARIZER_ENGINE_KEY,
        default=_env_seed_engine(),
        cast=str,
        label="Summary narration engine",
        description=(
            "Turns the deterministic findings into plain language on-device, with "
            "no AI model and no network call. (The former local-Ollama option was "
            "removed; a hosted engine is never offered for summarization.)"
        ),
        group="Narration engine",
        options=[
            {
                "value": "in_program",
                "label": "On-device, no model (deterministic template)",
                "description": (
                    "Stitches the analysis engine's own finding text into prose. "
                    "Uses no AI model and makes no network call — the most private "
                    "option, and now the only one."
                ),
            },
        ],
    ),
    # Which external provider the export handoff (CLAUDE.md "The export
    # handoff") would send a metric's picture to, IF the separate
    # export_hosted_enabled capability (a raw setting, not this typed registry
    # — see api.py) is also on AND the user confirms a specific send. This
    # setting alone sends nothing — provider SELECTION is architecture (which
    # option a pluggable design offers). The charter deliberately stays
    # provider-agnostic (naming a vendor/duration there would go stale); THIS
    # file is exactly where the specifics belong instead, and each option's
    # `description` is the SINGLE SOURCE both the Settings picker and the
    # export preview's destination banner read from — so the two surfaces can
    # never say something different about the same provider. Re-verify these
    # against each vendor's current terms at build/release time (see
    # ROADMAP.md's "PLAN OF RECORD" for the research + citations behind them).
    SettingDef(
        key="export_provider",
        default="anthropic",
        cast=str,
        label="External export provider",
        description=(
            "Which external model would receive a metric's exported picture, if "
            "external export is enabled and you confirm a specific send. "
            "Selecting a provider here sends nothing by itself."
        ),
        group="External export",
        options=[
            {
                "value": "anthropic",
                "label": "Anthropic",
                "description": (
                    "Default. Standard (non-enterprise) API usage: excludes your "
                    "data from model training by default, no opt-in needed, and "
                    "retains it approximately 7 days before auto-deletion. True "
                    "zero-retention requires a separate enterprise arrangement "
                    "this project doesn't have."
                ),
            },
            {
                "value": "openai",
                "label": "OpenAI",
                "description": (
                    "Standard (non-enterprise) API usage: excludes your data from "
                    "model training by default, no opt-in needed, and retains it "
                    "approximately 30 days before auto-deletion. True "
                    "zero-retention requires a separate enterprise arrangement "
                    "this project doesn't have."
                ),
            },
        ],
    ),
]

BY_KEY: dict[str, SettingDef] = {d.key: d for d in SETTINGS}


def resolve(conn, key: str) -> int | float | str:
    """The effective value for `key`: the stored override if present, else the
    code-constant default. Cast to the setting's type.

    For an enum the persisted value WINS, but only if it's still a known option;
    a stale/malformed stored value falls back to the default (which, for the
    summarizer engine, is env-seeded — so an un-persisted install resolves to its
    current env engine, i.e. zero behavior change)."""
    d = BY_KEY[key]
    raw = db.get_setting(conn, key)
    if raw is None:
        return d.default
    if d.options is not None:
        allowed = {o["value"] for o in d.options}
        return raw if raw in allowed else d.default
    try:
        return d.cast(raw)
    except (TypeError, ValueError):
        # A malformed stored value should never break a view — fall back.
        return d.default


def seed_defaults(conn) -> None:
    """Populate the table with each default, INSERT-OR-IGNORE so it never
    overwrites a value the user has edited and never disturbs existing data.
    Idempotent; safe to call on every startup. The resolve() fallback means this
    is belt-and-suspenders, not load-bearing."""
    for d in SETTINGS:
        if db.get_setting(conn, d.key) is None:
            db.set_setting(conn, d.key, str(d.default))


def view(conn, d: SettingDef) -> dict:
    """One setting serialized for the API/UI: its current effective value plus
    everything the panel needs to render and label it. Bounds are included even
    when None so the shape is stable as future bounded settings arrive."""
    return {
        "key": d.key,
        "value": resolve(conn, d.key),
        "default": d.default,
        "type": d.type_name,
        "label": d.label,
        "description": d.description,
        "minimum": d.minimum,
        "maximum": d.maximum,
        "step": d.step,
        "unit": d.unit,
        "group": d.group,
        "options": d.options,
    }


def views(conn) -> list[dict]:
    """All settings serialized for the panel, in registry order."""
    return [view(conn, d) for d in SETTINGS]


class SettingError(ValueError):
    """An update was rejected (unknown key or a value that isn't the right type).
    The API maps this to a 400."""


def _coerce(d: SettingDef, value) -> int | float | str:
    """Type-validate one incoming value against its definition. Rejects a
    non-integer for an int setting (int(10.5) silently truncates, so guard).
    Bound CLAMPING is intentionally not done here yet — the future pass adds it
    against d.minimum/d.maximum; this build is type-validation only.

    For an enum the value must be one of the closed allowlist of option values —
    this is the SERVER-SIDE validation; the client is never trusted, and an
    out-of-allowlist value raises before anything is written."""
    if d.options is not None:
        allowed = {o["value"] for o in d.options}
        if value not in allowed:
            raise SettingError(
                f"{d.key}: '{value}' is not one of {sorted(allowed)}."
            )
        return value
    try:
        num = float(value)
    except (TypeError, ValueError):
        raise SettingError(f"{d.key}: '{value}' is not a number.")
    if d.cast is int:
        if not num.is_integer():
            raise SettingError(f"{d.key}: must be a whole number, got {value}.")
        return int(num)
    return num


def apply_updates(conn, values: dict) -> list[dict]:
    """Validate and persist a batch of {key: value} edits, then return the
    refreshed views. All-or-nothing on validation: an unknown key or bad type
    raises before anything is written, so a bad field can't half-apply."""
    coerced: dict[str, int | float] = {}
    for key, value in values.items():
        d = BY_KEY.get(key)
        if d is None:
            raise SettingError(f"Unknown setting '{key}'.")
        coerced[key] = _coerce(d, value)
    for key, num in coerced.items():
        db.set_setting(conn, key, str(num))
    return views(conn)
