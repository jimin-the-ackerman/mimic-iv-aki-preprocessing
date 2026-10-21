"""Compare the outputs of two pipeline runs: python scripts/compare_runs.py <project_dir_A> <project_dir_B>

Parquet files are compared after sorting by their key columns (row order may differ), floats with a relative tolerance of 1e-9;
CSV, JSON and Markdown outputs must match exactly. Exit code 1 if anything differs.
"""
import sys
from pathlib import Path
import pandas as pd
from pandas.testing import assert_frame_equal


def main():
    A, B = Path(sys.argv[1]), Path(sys.argv[2])
    KEYS = {"hourly": ["stay_id", "hour"], "drug_map": ["kind", "key"]}
    PARQUET = ["data/cohort/base_cohort", "data/cohort/cohort_stage2", "data/cohort/cohort_stage3", "data/cohort/cohort_final",
               "data/external/drug_map", "data/features/hourly", "data/features/wide", "data/features/splits"]
    TEXT = ["data/cohort/flow_base.csv", "data/cohort/flow_final.csv", "data/features/default_features.json",
            "docs/feature_dictionary.md", "docs/feature_dictionary_kr.md"]
    bad = 0
    for p in PARQUET:
        a, b = pd.read_parquet(A / f"{p}.parquet"), pd.read_parquet(B / f"{p}.parquet")
        keys = KEYS.get(Path(p).name, ["stay_id"])
        a, b = a.sort_values(keys).reset_index(drop=True), b.sort_values(keys).reset_index(drop=True)
        try:
            assert_frame_equal(a, b, check_exact=False, rtol=1e-9, atol=1e-12)
            print(f"same   {p}  {a.shape}")
        except AssertionError as e:
            bad += 1; print(f"DIFFER {p}: {str(e).splitlines()[0]}")
    for t in TEXT:
        same = (A / t).read_bytes() == (B / t).read_bytes()
        bad += not same; print(("same   " if same else "DIFFER ") + t)
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
