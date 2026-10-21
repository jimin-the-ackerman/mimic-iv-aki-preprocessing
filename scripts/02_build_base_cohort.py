"""Stage 1 of the cohort: one row per ICU stay after the eligibility filters that need no labels.

Writes data/cohort/base_cohort.parquet and data/cohort/flow_base.csv.
Later stages (ESRD flag, creatinine/weight availability, AKI label and its exclusions) build on this.
"""
from pathlib import Path
import duckdb, yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/mimiciv/3.1_parquet/icu/icustays.parquet', 'data/mimiciv/3.1_parquet/hosp/patients.parquet', 'data/mimiciv/3.1_parquet/hosp/admissions.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))
    P = Path(cfg["paths"]["parquet_root"])
    OUT = Path("data/cohort"); OUT.mkdir(parents=True, exist_ok=True)
    min_age = cfg["cohort"]["min_age"]
    min_los_h = cfg["cohort"]["min_icu_los_hours"]
    tz_h = cfg["task"]["time_zero_hours"]

    con = duckdb.connect()
    con.execute(f"""
create temp view stays as
select i.subject_id, i.hadm_id, i.stay_id, i.first_careunit, i.last_careunit, i.intime, i.outtime,
       date_diff('minute', i.intime, i.outtime) / 60.0 as icu_los_hours,
       p.gender, p.anchor_age, p.anchor_year, p.anchor_year_group, p.dod,
       a.admittime, a.dischtime, a.deathtime, a.admission_type, a.race, a.insurance,
       a.hospital_expire_flag,
       p.anchor_age + (year(i.intime) - p.anchor_year) as age_at_icu,
       i.intime + to_hours({tz_h}) as time_zero,
       row_number() over (partition by i.hadm_id order by i.intime) as stay_rank
from '{P}/icu/icustays.parquet' i
join '{P}/hosp/patients.parquet' p using (subject_id)
join '{P}/hosp/admissions.parquet' a using (hadm_id)
""")

    steps = [
        ("all ICU stays", "true"),
        ("first ICU stay per hospital admission", "stay_rank = 1"),
        (f"age >= {min_age}", f"age_at_icu >= {min_age}"),
        (f"ICU stay >= {min_los_h} h", f"icu_los_hours >= {min_los_h}"),
    ]
    rows, cond = [], []
    for name, c in steps:
        cond.append(f"({c})")
        n, s = con.execute(f"select count(*), count(distinct subject_id) from stays where {' and '.join(cond)}").fetchone()
        rows.append((name, n, s))
    con.execute(f"copy (select * from stays where {' and '.join(cond)} order by stay_id) to '{OUT}/base_cohort.parquet' (format parquet)")

    prev = None
    lines = ["step,stays,patients,removed"]
    for name, n, s in rows:
        lines.append(f'"{name}",{n},{s},{"" if prev is None else prev - n}')
        prev = n
    (OUT / "flow_base.csv").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))


if __name__ == "__main__":
    main()
