"""Curated DISPLAY aliases — friendly names shown in the UI for verbose lab metrics.

The MATCH KEY is the metric's id. `metrics.name` (the lab's verbose wording) and
`metrics.alias` (the shorthand) are two LABELS that both resolve to that id, so adding a
shorthand never costs the metric its lab-wording label — which is what keeps a future
import resolving to the same id. This module maps a verbose label -> a friendlier
shorthand, seeded on startup like metric_config's SEED.

Curation principles (see CLAUDE.md / ROADMAP):
  - Pick ONE display convention: common clinical shorthand the reader recognizes.
  - Drop a SPECIMEN suffix (Serum/Plasma, Whole Blood) ONLY in the shorthand — the suffix
    is real provenance and survives on the verbose label, so a future different-specimen
    test (urine metals, a glucometer glucose) still resolves to its own distinct id.
  - Drop a METHOD only in the shorthand where an alternative could coexist (Testosterone
    Total/Free have other assay methods) — the verbose label keeps the method, so the two
    would resolve to different ids.

seed_aliases() sets an alias ONLY where the metric currently has none (alias IS NULL), so
a user's own display-name edit is never clobbered by a later startup (unlike the blunt
metric_config re-seed — an alias is user-editable, so first-run-default semantics fit).
"""

from __future__ import annotations

import sqlite3

import db

# canonical (lab) name  ->  friendly display name
ALIASES: dict[str, str] = {
    # Abbreviations the reader knows better than the spelled-out form.
    "Blood Urea Nitrogen": "BUN",
    "Aspartate Aminotransferase": "AST",
    "Alanine Aminotransferase": "ALT",
    "Alkaline Phosphatase Total": "ALP",
    "Insulin-like Growth Factor 1": "IGF-1",
    "Insulin-like Growth Factor 1 Z-Score Calculation": "IGF-1 Z-Score",
    # Method survives on the verbose label; the shorthand is the short clinical name.
    "Testosterone Total by LC-MS/MS": "Testosterone Total",
    "Testosterone Free by Equilibrium Dialysis/LC-MS/MS": "Testosterone Free",
    # SPEP fraction fragment -> its proper name (the lab's "Gamma" survives as a label).
    "Gamma": "Gamma Globulin",
    # Drop the "Serum/Plasma" specimen suffix in the shorthand (kept on the verbose label).
    "Sodium Serum/Plasma": "Sodium",
    "Potassium Serum/Plasma": "Potassium",
    "Chloride Serum/Plasma": "Chloride",
    "Calcium Serum/Plasma": "Calcium",
    "Magnesium Serum/Plasma": "Magnesium",
    "Glucose Serum/Plasma": "Glucose",
    "Creatinine Serum/Plasma": "Creatinine",
    "Iron Serum/Plasma": "Iron",
    "Copper Serum/Plasma": "Copper",
    "Zinc Serum/Plasma": "Zinc",
    "Ferritin Serum/Plasma": "Ferritin",
    "Protein Total Serum/Plasma": "Total Protein",
    "Nicotinic Acid Serum/Plasma": "Nicotinic Acid",
    # Drop the "Whole Blood" specimen suffix in the shorthand (kept on the verbose label).
    "Arsenic Whole Blood": "Arsenic",
    "Cadmium Whole Blood": "Cadmium",
    "Lead Whole Blood": "Lead",
    "Mercury Whole Blood": "Mercury",
    "Vitamin B1 (Thiamine) Whole Blood": "Vitamin B1 (Thiamine)",
}


def seed_aliases(conn: sqlite3.Connection) -> int:
    """Apply the curated display aliases on startup. Sets an alias ONLY for a metric that
    (a) exists in the registry and (b) has no alias yet (alias IS NULL) — so a user's own
    edit is never overwritten. Skips any mapping that would conflict with a name/alias
    already in use (defensive; the curated map is internally clean). Returns the count
    applied. Idempotent: a metric that already carries its default (or a user's) alias is
    left alone."""
    applied = 0
    for canonical, display in ALIASES.items():
        if db.get_metric_alias(conn, canonical) is not None:
            continue  # already has an alias (curated default or the user's) -> leave it
        try:
            # Returns False for a metric that isn't in the registry — a curated entry for a
            # test this user hasn't had yet is simply skipped, not an error.
            if db.set_metric_alias(conn, canonical, display):
                applied += 1
        except db.AliasConflictError:
            continue  # a name collision (shouldn't happen for the curated map) -> skip
    return applied
