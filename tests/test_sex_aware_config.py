"""#18 Phase 1 — sex-aware detector-config resolution (the seam, zero behavior
change until a variant is seeded).

Proves three things against a synthetic DB:
  1. sex-INDEPENDENT config resolves IDENTICALLY for male / female / null / other
     (so no current metric — none of which is sex-tagged — changes),
  2. a sex-TAGGED threshold resolves per sex, with null/'other' seeing only the
     untagged lines, in BOTH the engine reader (get_config) and the display reader
     (get_thresholds_detailed),
  3. a sex-KEYED rcv_cv resolves per sex with the 'default' fallback, while a flat
     rcv_cv (today's shape) passes through for everyone.
"""

from __future__ import annotations

import json

import db
import metric_config as mc


def _set(conn, metric, key, value):
    db.set_metric_config(conn, metric, key, json.dumps(value))
    conn.commit()


def _sex(conn, sex):
    db.update_profile(conn, sex=sex, date_of_birth=None)


# --- 1. sex-independent config is identical across every sex ------------------

def test_sex_independent_config_identical_across_sexes(db_conn):
    # An untagged threshold list + a flat rcv_cv — the shape every metric uses today.
    _set(db_conn, "Widget", "thresholds",
         [{"cutoff": 10, "source": "SRC", "direction": "up"}])
    _set(db_conn, "Widget", "rcv_cv", {"analytical": 0.01, "intra": 0.02})

    results = []
    for s in ("male", "female", "other", None):
        _sex(db_conn, s)
        results.append(mc.get_config(db_conn, "Widget"))

    first = results[0]
    assert all(r == first for r in results), "untagged config must not vary by sex"
    # And it is exactly the engine shape (no leaked 'sex' key).
    assert first["thresholds"] == [
        {"cutoff": 10, "source": "SRC", "direction": "up", "boundary": "inclusive"}
    ]
    assert first["rcv_cv"] == {"analytical": 0.01, "intra": 0.02}


# --- 2. sex-tagged thresholds resolve per sex ---------------------------------

def _cutoffs(cfg):
    return sorted(t["cutoff"] for t in cfg.get("thresholds", []))


def test_sex_tagged_thresholds_filter_by_profile_sex(db_conn):
    _set(db_conn, "Hormone", "thresholds", [
        {"cutoff": 1, "source": "S"},                       # untagged -> everyone
        {"cutoff": 2, "source": "S", "sex": "male"},        # male only
        {"cutoff": 3, "source": "S", "sex": "female"},      # female only
    ])

    _sex(db_conn, "male")
    assert _cutoffs(mc.get_config(db_conn, "Hormone")) == [1, 2]
    _sex(db_conn, "female")
    assert _cutoffs(mc.get_config(db_conn, "Hormone")) == [1, 3]
    # null and 'other' see ONLY the untagged line (a sex number can't be confirmed).
    _sex(db_conn, None)
    assert _cutoffs(mc.get_config(db_conn, "Hormone")) == [1]
    _sex(db_conn, "other")
    assert _cutoffs(mc.get_config(db_conn, "Hormone")) == [1]


def test_engine_thresholds_never_carry_the_sex_tag(db_conn):
    _set(db_conn, "Hormone", "thresholds", [{"cutoff": 2, "source": "S", "sex": "male"}])
    _sex(db_conn, "male")
    cfg = mc.get_config(db_conn, "Hormone")
    assert cfg["thresholds"] == [
        {"cutoff": 2, "source": "S", "direction": "up", "boundary": "inclusive"}
    ]  # 'sex' stripped before the engine sees it


def test_display_reader_filters_sex_the_same_way(db_conn):
    _set(db_conn, "Hormone", "thresholds", [
        {"cutoff": 1, "source": "S", "definition": "d1"},
        {"cutoff": 2, "source": "S", "sex": "male", "definition": "d2"},
    ])
    _sex(db_conn, "male")
    got = [t["cutoff"] for t in mc.get_thresholds_detailed(db_conn, "Hormone")]
    assert got == [1, 2]
    _sex(db_conn, "female")
    got = [t["cutoff"] for t in mc.get_thresholds_detailed(db_conn, "Hormone")]
    assert got == [1]


# --- 3. sex-keyed rcv_cv resolves per sex, flat passes through ----------------

def test_sex_keyed_rcv_cv_resolves_with_default_fallback(db_conn):
    _set(db_conn, "Cell", "rcv_cv", {
        "male": {"analytical": 0.03, "intra": 0.06},
        "female": {"analytical": 0.04, "intra": 0.08},
        "default": {"analytical": 0.05, "intra": 0.10},
    })
    _sex(db_conn, "male")
    assert mc.get_config(db_conn, "Cell")["rcv_cv"] == {"analytical": 0.03, "intra": 0.06}
    _sex(db_conn, "female")
    assert mc.get_config(db_conn, "Cell")["rcv_cv"] == {"analytical": 0.04, "intra": 0.08}
    # 'other' and null both fall back to 'default'.
    _sex(db_conn, "other")
    assert mc.get_config(db_conn, "Cell")["rcv_cv"] == {"analytical": 0.05, "intra": 0.10}
    _sex(db_conn, None)
    assert mc.get_config(db_conn, "Cell")["rcv_cv"] == {"analytical": 0.05, "intra": 0.10}


def test_sex_keyed_rcv_cv_without_default_omits_kwarg(db_conn):
    # A sex-keyed dict with no 'default' and no matching sex -> the kwarg is omitted
    # (no rcv_delta) rather than guessing a noise band.
    _set(db_conn, "Cell", "rcv_cv", {"male": {"analytical": 0.03, "intra": 0.06}})
    _sex(db_conn, "female")
    assert "rcv_cv" not in mc.get_config(db_conn, "Cell")
    _sex(db_conn, None)
    assert "rcv_cv" not in mc.get_config(db_conn, "Cell")


def test_flat_rcv_cv_passes_through_for_every_sex(db_conn):
    _set(db_conn, "Cell", "rcv_cv", {"analytical": 0.01, "intra": 0.02})
    for s in ("male", "female", "other", None):
        _sex(db_conn, s)
        assert mc.get_config(db_conn, "Cell")["rcv_cv"] == {"analytical": 0.01, "intra": 0.02}


# --- Phase 2: the first curated sex-variant (Testosterone AUA 300 -> male) -----

TESTO = "Testosterone Total by LC-MS/MS"


def test_testosterone_seed_line_is_male_gated():
    # Pins the curation itself: the AUA 300 line carries sex="male" in SEED.
    line = [t for t in mc.SEED[TESTO]["thresholds"] if t["cutoff"] == 300][0]
    assert line["sex"] == "male"


def test_testosterone_seed_resolves_per_profile_sex(db_conn):
    # End-to-end with the REAL seeded threshold JSON: the 300 line shows for a male
    # profile and is hidden for female / null (a male cutoff can't be confirmed there).
    _set(db_conn, TESTO, "thresholds", mc.SEED[TESTO]["thresholds"])
    _sex(db_conn, "male")
    assert [t["cutoff"] for t in mc.get_thresholds_detailed(db_conn, TESTO)] == [300]
    # The engine gets the crossing line too (male), with no sex tag leaked.
    assert [t["cutoff"] for t in mc.get_config(db_conn, TESTO)["thresholds"]] == [300]
    for hidden in ("female", "other", None):
        _sex(db_conn, hidden)
        assert mc.get_thresholds_detailed(db_conn, TESTO) == []
        assert mc.get_config(db_conn, TESTO).get("thresholds") == []


# --- Phase 2: WHO hemoglobin — first sex-variant with DIFFERENT cutoff VALUES -----

def test_hemoglobin_who_lines_are_sex_tagged():
    thr = mc.SEED["Hemoglobin"]["thresholds"]
    assert {t["sex"]: t["cutoff"] for t in thr} == {"male": 13.0, "female": 12.0}
    assert all(t["source"] == "WHO" and t["direction"] == "down"
               and t["boundary"] == "exclusive" for t in thr)
    assert "WHO" in mc.SOURCES


def test_hemoglobin_who_resolves_per_sex(db_conn):
    # Unlike testosterone (gate one line), here the CUTOFF differs by sex: male -> 13.0,
    # female -> 12.0, null/'other' -> neither (WHO's cutoff can't be picked without sex).
    _set(db_conn, "Hemoglobin", "thresholds", mc.SEED["Hemoglobin"]["thresholds"])
    _sex(db_conn, "male")
    assert [t["cutoff"] for t in mc.get_thresholds_detailed(db_conn, "Hemoglobin")] == [13.0]
    _sex(db_conn, "female")
    assert [t["cutoff"] for t in mc.get_thresholds_detailed(db_conn, "Hemoglobin")] == [12.0]
    for none_sex in ("other", None):
        _sex(db_conn, none_sex)
        assert mc.get_thresholds_detailed(db_conn, "Hemoglobin") == []
    # engine side: male gets the 13.0 crossing line, sex tag stripped before the engine.
    _sex(db_conn, "male")
    eng = mc.get_config(db_conn, "Hemoglobin")["thresholds"]
    assert [t["cutoff"] for t in eng] == [13.0]
    assert all("sex" not in t for t in eng)
