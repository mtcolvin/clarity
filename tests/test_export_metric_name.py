"""
The export bundle's `metric` field is USER/PARSER-CONTROLLED free text — and it goes
off-machine. This pins the LOAD-BEARING fact behind "Model A" (see CLAUDE.md "The export
handoff"): the privacy guarantee does NOT rest on the payload being identifier-free "by
construction" (that claim is only COLUMN-level — the export never reads the name/DOB/MRN/
physician/facility columns), because a field it DOES read can still carry an identifier a
parser injected. The real, observed case: `pdf_import` glued a lab report's practice/
department header onto a metric name ("Benign Hematology White Blood Cell Count" — a
physician-practice string the charter's hard rule names explicitly).

So the control that actually catches such text is the FAITHFUL PREVIEW + per-send consent,
NOT the column choice and NOT the regex scrub. These tests exist so a future refactor can't
quietly drop the preview on the strength of a by-construction claim: they prove (1) an
injected department header reaches the preview VERBATIM and the regex scrub does NOT catch
it, and (2) the scrub is only belt-and-suspenders — it catches a "Dr. X" name but that's
the easy case, not the one that bit us.

No real provider is called — engine="hosted" with confirmation=None only ever returns a
Preview; gateway._hosted_call is never reached.
"""

from __future__ import annotations

import explain
import gateway


def _bundle_named(metric: str) -> dict:
    """A minimal but real export bundle for a given metric NAME — assembled the same way
    the export routes assemble it, so the `metric` field is carried exactly as the app
    would carry it off-machine."""
    series = [
        {"observed_on": "2024-01-01", "value": 5.0, "unit": "10*9/L",
         "ref_low": 3.9, "ref_high": 10.7, "result_type": "numeric"},
        {"observed_on": "2024-06-01", "value": 6.0, "unit": "10*9/L",
         "ref_low": 3.9, "ref_high": 10.7, "result_type": "numeric"},
    ]
    return explain.assemble_explain_context(
        metric, "10*9/L", series, [], [],
        personal_baseline_mean=None, methodology_note=None,
        latest_change=None, personal_baseline_mode=False,
    )


def _preview_for(metric: str):
    result = gateway.complete(
        gateway.LLMRequest(task="explain_metric", engine="hosted",
                           fields=[_bundle_named(metric)]),
        confirmation=None,
    )
    assert result.status == "needs_confirmation"
    return result.preview


# ---- 1. the load-bearing pin: an injected department header reaches the preview verbatim,
#         and the regex scrub does NOT catch it -> the PREVIEW is the control ----

def test_injected_practice_header_reaches_preview_and_scrub_misses_it():
    # The exact shape of the real incident: a benign-hematology (practice/department)
    # header glued onto a CBC white-count name by the PDF parser.
    contaminated = "Benign Hematology White Blood Cell Count"
    preview = _preview_for(contaminated)
    # It IS sent (allowlisted) and reaches the preview payload VERBATIM — so a reviewer
    # reading the preview before consent is the one who sees (and can stop) it.
    assert preview.payload[0]["metric"] == contaminated
    # The regex scrub matches NONE of its patterns on this string, so it's not what
    # protects here. (If a future scrub change starts catching it, great — but the
    # guarantee must NOT depend on that; this asserts today's reality that it doesn't.)
    assert preview.redactions == []
    assert preview.excluded_fields == []  # allowlisted => included, never silently dropped


# ---- 2. the scrub is belt-and-suspenders, not the primary defense: it catches an easy
#         "Dr. X" name, which is exactly NOT the case that bit us ----

def test_scrub_catches_an_easy_physician_name_but_that_is_the_easy_case():
    preview = _preview_for("White Blood Cell Count Dr. Roe")
    # The physician regex (\bDr\.?\s+[A-Z][a-z]+) DOES fire here — the scrub redacts it in
    # the payload and records it...
    assert any(r["type"] == "physician" for r in preview.redactions)
    assert "[REDACTED:physician]" in preview.payload[0]["metric"]
    # ...proving the scrub helps for the obvious pattern, while test 1 proves it misses the
    # arbitrary-header case — which is why Model A rests on the preview, not on scrubbing.
