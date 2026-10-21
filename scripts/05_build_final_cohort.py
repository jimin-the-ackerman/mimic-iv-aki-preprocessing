"""Stage 4: apply the label-dependent exclusions and write the final cohort with labels.

Label y = first-onset KDIGO AKI in (time_zero, time_zero + horizon]. Urine criterion = gap-limited version
(every charted interval in the 6 h window <= uo_max_interval_hours); the reference onset (any gap < 12 h) is kept
as `onset_uo_reference` for sensitivity analysis. Writes data/cohort/cohort_final.parquet and flow_final.csv.
"""
from pathlib import Path
import duckdb, yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/cohort/cohort_stage3.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))
    H = cfg["task"]["horizon_hours"]
    assert cfg["aki"]["uo_max_interval_hours"] == 2, "04_build_labels.py computes the 2 h variant (onset_uo_gap2)"
    min_cr = cfg["aki"]["min_creatinine_values_0_to_t0"]

    con = duckdb.connect()
    con.execute(f"""
create temp table s as
select * exclude (onset_uo, onset_aki), onset_uo as onset_uo_reference, onset_uo_gap2 as onset_uo,
  least(onset_creat, onset_uo_gap2) as onset_aki,
  coalesce(onset_creat > time_zero and onset_creat <= time_zero + to_hours({H}), false) as aki_by_creat,
  coalesce(onset_uo_gap2 > time_zero and onset_uo_gap2 <= time_zero + to_hours({H}), false) as aki_by_uo
from 'data/cohort/cohort_stage3.parquet'
""")
    con.execute("""
create temp table t as select *, (aki_by_creat or aki_by_uo) as y,
  coalesce(first_rrt_start <= time_zero, false) as rrt_before_t0,
  (n_creat_in_window = 0 and uo_hours_in_window < 6) as no_data_in_window
from s""")
    steps = [
        ("stage 2 cohort (base + ESRD flag)", "true"),
        ("weight available", "weight_kg is not null"),
        (f">= {min_cr} creatinine values in [0, 48 h]", f"n_creat_0_to_t0 >= {min_cr}"),
        ("no AKI by time zero", "(onset_aki is null or onset_aki > time_zero)"),
        (f"outcome observed (event in window or ICU stay covers {H} h)", "(y or icu_covers_window)"),
        ("drop non-ESRD stays with dialysis before time zero", "not (rrt_before_t0 and not esrd_chronic_dialysis)"),
        ("drop negatives with no creatinine / <6 h urine data in window", "(y or not no_data_in_window)"),
    ]
    cond, lines, prev = [], ["step,stays,patients,removed"], None
    for name, c in steps:
        cond.append(f"({c})")
        n, p = con.execute(f"select count(*), count(distinct subject_id) from t where {' and '.join(cond)}").fetchone()
        lines.append(f'"{name}",{n},{p},{"" if prev is None else prev - n}'); prev = n
    where = " and ".join(cond)
    con.execute(f"copy (select * from t where {where} order by stay_id) to 'data/cohort/cohort_final.parquet' (format parquet)")
    open("data/cohort/flow_final.csv", "w").write("\n".join(lines) + "\n")
    print("\n".join(lines))
    print(con.execute(f"""select count(*) n, sum(y::int) pos, round(avg(y::int),4) prev, sum(aki_by_creat::int) pos_creat, sum(aki_by_uo::int) pos_uo,
  sum((aki_by_uo and not aki_by_creat)::int) uo_only, sum((aki_by_creat and not aki_by_uo)::int) creat_only,
  sum(esrd_chronic_dialysis::int) esrd, sum(rrt_before_t0::int) rrt_before_t0, sum(no_data_in_window::int) no_data_in_window
  from t where {where}""").df().T.to_string())


if __name__ == "__main__":
    main()
