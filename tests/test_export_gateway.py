"""
Phase (a) of the Phase B export arc — the privacy foundation, backend-only, no
route, no UI, NO EGRESS POSSIBLE (see ROADMAP.md "PLAN OF RECORD" under #1).

Proves the two things the eventual export feature's privacy posture ("Model A":
PII-clean-by-construction + faithful full preview + per-send consent, NOT
automated redaction) actually rests on, rather than asserting them:

1. The `explain_metric` allowlist in gateway.py matches the bundle's top-level
   keys EXACTLY — so a future field added to assemble_explain_context can't
   silently ride into an external payload unreviewed (it would fail loudly here
   first), and conversely the allowlist can't silently start dropping a bundle
   key without this test catching it.
2. Running a REALISTIC bundle (built from a real analyze_series() flag, not a
   hand-crafted "obviously clean" one) through the gateway's actual hosted
   preview path produces ZERO redactions and ZERO excluded fields — proving the
   bundle is PII-clean by construction, and that the full nested payload
   (readings/engine_findings/cited_thresholds) survives the allowlist+scrub
   pipeline faithfully into what a confirm-screen UI would render (Phase (b)).

Nothing here calls a real provider — engine="hosted" with confirmation=None
only ever returns a Preview; gateway._hosted_call is never reached.
"""

from __future__ import annotations

import analysis
import explain
import gateway
from analysis import Flag


def _real_bundle():
    """A bundle built from a REAL analyze_series() run (not synthetic flags), so
    the Flag.detail dicts feeding engine_findings are production-shaped: numeric
    stats (z-scores, deltas, slopes), never stray strings. This is the realistic
    case the "PII-clean by construction" claim needs to hold against, not a
    contrived one."""
    series = [
        {"observed_on": "2024-01-01", "value": 100.0, "unit": "mg/dL",
         "ref_low": 70.0, "ref_high": 99.0, "result_type": "numeric"},
        {"observed_on": "2024-02-01", "value": 105.0, "unit": "mg/dL",
         "ref_low": 70.0, "ref_high": 99.0, "result_type": "numeric"},
        {"observed_on": "2024-03-01", "value": 210.0, "unit": "mg/dL",
         "ref_low": 70.0, "ref_high": 99.0, "result_type": "numeric"},
    ]
    flags = analysis.analyze_series(
        "Glucose Serum/Plasma", series,
        thresholds=[{"cutoff": 200, "source": "ADA", "direction": "up",
                     "boundary": "inclusive"}],
    )
    assert flags, "test needs a real, non-empty finding to be a meaningful proof"
    threshold_detailed = [{
        "cutoff": 200, "source": "ADA",
        "definition": "ADA's casual-glucose diagnostic threshold for diabetes.",
        "status_note": None,
    }]
    return explain.assemble_explain_context(
        "Glucose Serum/Plasma", "mg/dL", series, flags, threshold_detailed,
        personal_baseline_mean=91.7,
        methodology_note="Fasting state affects interpretation; not confirmed per draw.",
        latest_change=None, personal_baseline_mode=False,
    )


# --------------------------------------------------------- 1. allowlist invariant

def test_explain_metric_allowlist_matches_bundle_keys():
    """A future bundle field must fail THIS test, not silently ship unreviewed in
    an external payload (and vice versa — the allowlist can't silently drop one)."""
    bundle = _real_bundle()
    assert set(gateway._ALLOWLISTS["explain_metric"]) == set(bundle.keys())


# ------------------------------------------------- 2. PII-clean-by-construction proof

def test_hosted_preview_scrubs_nothing_from_real_bundle():
    """The privacy-critical proof: route a REAL bundle through the gateway's
    actual hosted-preview path (allowlist -> scrub -> preview) and confirm zero
    redactions, zero exclusions. This is what "Model A" (structural cleanliness,
    not scrubbing) rests on — proven here, not assumed."""
    bundle = _real_bundle()
    result = gateway.complete(
        gateway.LLMRequest(task="explain_metric", engine="hosted", fields=[bundle]),
        confirmation=None,
    )
    assert result.status == "needs_confirmation"
    preview = result.preview
    assert preview.excluded_fields == []
    assert preview.redactions == []


def test_hosted_preview_carries_the_full_nested_payload_faithfully():
    """The OTHER half of the item-1 finding: Preview.payload isn't a hash or a
    flattened summary — it's the full bundle, nested lists and all, exactly as
    assembled. This is what a Phase (b) confirm-screen renders faithfully FROM —
    proven here to actually survive the gateway's allowlist+scrub pipeline
    unchanged, not just true of the bundle in isolation (already pinned by
    test_explain.py::test_assemble_shape)."""
    bundle = _real_bundle()
    result = gateway.complete(
        gateway.LLMRequest(task="explain_metric", engine="hosted", fields=[bundle]),
        confirmation=None,
    )
    sent = result.preview.payload[0]
    assert sent["readings"] == bundle["readings"]
    assert sent["engine_findings"] == bundle["engine_findings"]
    assert sent["cited_thresholds"] == bundle["cited_thresholds"]
    assert sent["methodology_note"] == bundle["methodology_note"]
    assert sent["personal_baseline_mean"] == bundle["personal_baseline_mean"]
