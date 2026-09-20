"""
Personal-baseline detector — robust median/MAD version (analysis.personal_baseline_z
+ personal_baseline_mean). The point of the switch: a single extreme reading (an
acute AST spike from an injury) must NOT poison the baseline — under the old
mean/SD it dragged the mean up AND exploded the SD, masking every later reading.
"""

from __future__ import annotations

import numpy as np

from analysis import personal_baseline_z, personal_baseline_mean


def test_outlier_does_not_mask_later_readings():
    """The core fix. History holds one acute spike (850) among a tight cluster
    (~25). A later genuinely-elevated reading (60) is well below the spike but far
    above the user's real baseline — the robust detector still flags it, whereas the
    old mean/SD z-score would have been masked to silence by the inflated SD."""
    hist = [25.0, 24.0, 26.0, 25.0, 850.0]
    new = 60.0

    # Old behavior (mean/SD): the outlier inflates the SD so the real deviation
    # looks trivial — proving the masking the robust version removes.
    mean, sd = np.mean(hist), np.std(hist, ddof=1)
    assert abs((new - mean) / sd) < 2.0            # old detector: MISSED (masked)

    f = personal_baseline_z("AST", hist, new)
    assert f is not None                            # robust detector: still catches it
    assert f.kind == "personal_baseline"
    assert "median" in f.message
    assert f.detail["personal_center"] == 25.0      # median, not the mean (~190)


def test_center_is_median_not_mean():
    series = [{"value": v} for v in (10.0, 10.0, 11.0, 10.0, 500.0)]
    # mean would be 108.2; the robust center is the median.
    assert personal_baseline_mean(series) == 10.0


def test_mad_zero_falls_back_to_mean_abs_dev():
    """MAD is 0 when > half the history is identical; the meanAD fallback still
    yields a usable spread so a real deviation flags."""
    hist = [5.0, 5.0, 5.0, 7.0]          # median 5, deviations [0,0,0,2] -> MAD 0
    f = personal_baseline_z("X", hist, 9.0)
    assert f is not None
    assert f.detail["personal_center"] == 5.0


def test_perfectly_flat_history_is_silent():
    """All-identical history has no personal spread to judge against — stay silent
    (out_of_range catches a genuine excursion separately), exactly as the old
    sd==0 guard did."""
    assert personal_baseline_z("X", [5.0, 5.0, 5.0, 5.0], 100.0) is None


def test_too_few_points_is_silent():
    assert personal_baseline_z("X", [10.0, 11.0, 9.0], 40.0) is None  # < min_points (4)


def test_direction_and_severity():
    hist = [100.0, 101.0, 99.0, 100.0, 100.0]
    below = personal_baseline_z("X", hist, 70.0)
    assert below is not None and "below" in below.message
    above = personal_baseline_z("X", hist, 130.0)
    assert above is not None and "above" in above.message
    assert above.severity in ("watch", "high")


def test_clean_data_unchanged_sensitivity():
    """Without outliers, median==mean and MAD/0.6745==SD, so a clear jump still
    flags and a trivial wiggle still doesn't — the switch didn't dull the detector."""
    hist = [50.0, 51.0, 49.0, 50.0, 50.0]
    assert personal_baseline_z("X", hist, 50.4) is None       # trivial: no flag
    assert personal_baseline_z("X", hist, 62.0) is not None    # clear move: flags


def test_noise_gate_with_range_still_applies():
    """A statistically-unusual but clinically-trivial move (a thin slice of the lab
    band) is still gated out — the robust switch preserves the noise gate."""
    hist = [4.30, 4.31, 4.29, 4.30, 4.30]  # tight cluster
    # A 0.02 move: big in z, tiny vs a wide 3.5-5.5 band -> gated out.
    assert personal_baseline_z("X", hist, 4.32, ref_low=3.5, ref_high=5.5) is None
