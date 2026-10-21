"""Write data/features/default_features.json: a suggested first set of model input columns.

Wide table: static features, the drug flags, and per-variable summaries (mean, min, max, last, hours observed).
Hourly table: value, _obs and _hsl for each variable, plus the activity flags.
Left out: IDs/times, labels and onset columns, Caution columns (coded at discharge), outlier counts, variables observed in
fewer than MIN_COVERAGE of stays, and redundant summaries. Everything stays in the Parquet files; this is only a suggestion.
"""
from pathlib import Path
import json
import duckdb


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/features/hourly.parquet', 'data/features/wide.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    MIN_COVERAGE = 0.05
    con = duckdb.connect()
    wide = [r[0] for r in con.execute("describe select * from 'data/features/wide.parquet'").fetchall()]
    hourly = [r[0] for r in con.execute("describe select * from 'data/features/hourly.parquet'").fetchall()]
    n = con.execute("select count(*) from 'data/features/wide.parquet'").fetchone()[0]

    obs_vars = sorted({c[:-len("_n_hours_obs")] for c in wide if c.endswith("_n_hours_obs")})
    cover = {v: con.execute(f"select count(*) filter (where {v}_n_hours_obs > 0) from 'data/features/wide.parquet'").fetchone()[0] / n for v in obs_vars}
    sparse = sorted(v for v, p in cover.items() if p < MIN_COVERAGE)
    keep = [v for v in obs_vars if v not in sparse]

    SUM_VARS = {"urine_ml", "drain_ml", "stool_ml", "other_output_ml", "intake_ml"}
    static = ["age_at_icu", "gender", "first_careunit", "admission_type", "weight_kg", "esrd_known_at_t0", "ckd_icd_prior_adm",
              "creat_baseline_7d", "creat_last_pre_icu", "n_dialysis_sessions_before_t0", "first_dialysis_hour",
              "vasopressor_hours", "dialysis_hours", "crrt_hours", "urine_ml_kg_h_overall", "fluid_balance_ml", "rrt_before_t0"]
    atc_kid = [c for c in wide if c.startswith(("atc_", "drug_"))] + ["n_kidney_relevant_classes"]
    atc3 = [c for c in wide if c.startswith("atc3_")]
    atc3_const = [c for c in atc3 if not 0.01 <= con.execute(f"select avg({c}::int) from 'data/features/wide.parquet'").fetchone()[0] <= 0.99]
    wide_cols = list(static) + atc_kid + [c for c in atc3 if c not in atc3_const]
    for v in keep:
        if v in SUM_VARS:
            wide_cols += [f"{v}_total", f"{v}_n_hours_obs"]
        elif v == "urine_ml_kg_h":
            wide_cols += ["urine_ml_kg_h_mean", "urine_ml_kg_h_last", "urine_ml_kg_h_n_hours_obs"]
        else:
            wide_cols += [f"{v}_{s}" for s in ("mean", "min", "max", "last", "n_hours_obs")]
    for e in ("egfr_mdrd", "egfr_cg", "egfr_ckdepi"):
        wide_cols += [f"{e}_min", f"{e}_last", f"{e}_mean"]

    hourly_cols = ["hour"] + [f"{v}{s}" for v in keep for s in ("", "_obs", "_hsl")] + ["egfr_mdrd", "egfr_cg", "egfr_ckdepi"] + \
                  ["vasopressor_active", "dialysis_active", "crrt_active"]

    forbidden = ("label_", "aki_by_", "onset_", "n_outlier_", "split_")
    bad = {"stay_id", "subject_id", "hadm_id", "intime", "time_zero", "anchor_year_group", "weight_src", "hospital_expire_flag",
           "esrd_chronic_dialysis", "esrd_icd_current_adm", "ckd_icd_current_adm", "dialysis_hx_item"}
    for c in wide_cols:
        assert c in wide, f"missing in wide: {c}"
        assert c not in bad and not c.startswith(forbidden), f"must not be an input: {c}"
    for c in hourly_cols:
        assert c in hourly, f"missing in hourly: {c}"

    out = {"wide": wide_cols, "hourly": hourly_cols, "categorical": ["gender", "first_careunit", "admission_type"],
           "dropped_sparse_variables": {v: round(cover[v], 3) for v in sparse}, "dropped_atc3_ordered_in_over_99pct_of_stays": atc3_const, "min_coverage": MIN_COVERAGE,
           "label": "label_aki_next_24h", "id": "stay_id", "split_default": "split_random"}
    json.dump(out, open("data/features/default_features.json", "w"), indent=1)
    print(f"wide: {len(wide_cols)} of {len(wide)} columns, hourly: {len(hourly_cols)} of {len(hourly)}")
    print("dropped for low coverage:", out["dropped_sparse_variables"])


if __name__ == "__main__":
    main()
