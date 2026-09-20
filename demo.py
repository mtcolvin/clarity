"""
demo.py — end-to-end smoke test.

    python demo.py

Builds the schema in an in-memory DB, seeds three illustrative series, runs the
analysis engine, and prints the flags. Each seeded series is designed to trip a
different detector:

  creatinine  rises steadily but stays INSIDE its range  -> trend catches it
  hba1c       creeps up and crosses the 5.7% line        -> range + threshold
  weight      stable, then a sudden drop                 -> personal-baseline z
"""

from db import connect, init_db, add_observation, get_series
from analysis import analyze_series


def seed(conn):
    # Creatinine: slow rise, never leaves the 0.7-1.3 mg/dL reference range.
    for d, v in [("2023-01-10", 0.90), ("2023-07-15", 0.96), ("2024-01-20", 1.02),
                 ("2024-07-18", 1.08), ("2025-01-22", 1.14), ("2025-07-19", 1.20)]:
        add_observation(conn, "creatinine", v, "mg/dL", d, ref_low=0.7, ref_high=1.3)

    # HbA1c: climbs across the ADA 5.7% A1c guideline threshold (and past ref_high 5.6).
    for d, v in [("2023-02-01", 5.3), ("2023-08-01", 5.5),
                 ("2024-02-01", 5.6), ("2024-08-01", 5.9)]:
        add_observation(conn, "hba1c", v, "%", d, ref_low=4.0, ref_high=5.6)

    # Weight: flat, then a sharp drop the trend tests may miss but z-score won't.
    for d, v in [("2024-01-01", 82.0), ("2024-04-01", 81.5), ("2024-07-01", 82.3),
                 ("2024-10-01", 81.8), ("2025-01-01", 75.0)]:
        add_observation(conn, "weight", v, "kg", d)


def main():
    conn = connect(":memory:")        # swap for 'health.db' to persist
    init_db(conn)
    seed(conn)

    # Thresholds use the engine's CURRENT dict shape {cutoff, source, direction,
    # boundary} — the same shape metric_config._threshold_pairs produces on the
    # real app path. (A1c climbs, so 'up'; 'inclusive' means a value landing
    # exactly on the cutoff counts as a crossing — the default for 'up'.)
    checks = {
        "creatinine": {},
        "hba1c": {"thresholds": [
            {"cutoff": 5.7, "source": "ADA", "direction": "up", "boundary": "inclusive"},
            {"cutoff": 6.5, "source": "ADA", "direction": "up", "boundary": "inclusive"},
        ]},
        "weight": {},
    }

    for metric, opts in checks.items():
        series = get_series(conn, metric)
        flags = analyze_series(metric, series, thresholds=opts.get("thresholds"))
        print(f"\n=== {metric}  ({len(series)} readings) ===")
        if not flags:
            print("  nothing stands out")
        for f in flags:
            print(f"  [{f.severity:>5}] {f.kind}: {f.message}")


if __name__ == "__main__":
    main()
