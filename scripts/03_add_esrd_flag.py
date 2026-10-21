"""Stage 2: add the ESRD / chronic dialysis flag to the base cohort (stays are kept, only flagged).

Flag = ICD ESRD/dialysis-dependence code on this or an earlier admission of the patient
       OR the admission-history item 'Dialysis patient' (225126) = 1 charted before time zero.
esrd_known_at_t0 leaves out current-admission ICD codes (assigned at discharge) and is the one to use as a model input.
Writes data/cohort/cohort_stage2.parquet.
"""
from pathlib import Path
import duckdb, yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/cohort/base_cohort.parquet', 'data/mimiciv/3.1_parquet/hosp/admissions.parquet', 'data/mimiciv/3.1_parquet/hosp/diagnoses_icd.parquet', 'data/mimiciv/3.1_parquet/icu/chartevents.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))
    P = Path(cfg["paths"]["parquet_root"])
    c = cfg["cohort"]
    icd10 = ",".join(f"'{x}'" for x in c["esrd_icd10"])
    icd9 = ",".join(f"'{x}'" for x in c["esrd_icd9"])
    items = ",".join(str(x) for x in c["esrd_chartevent_itemids"])

    con = duckdb.connect()
    con.execute(f"""
create temp table esrd_dx as
select distinct d.subject_id, d.hadm_id, a.admittime
from '{P}/hosp/diagnoses_icd.parquet' d join '{P}/hosp/admissions.parquet' a using (subject_id, hadm_id)
where (d.icd_version = 10 and d.icd_code in ({icd10})) or (d.icd_version = 9 and d.icd_code in ({icd9}))
""")
    con.execute(f"""
create temp table dial_item as
select distinct e.stay_id from '{P}/icu/chartevents.parquet' e join 'data/cohort/base_cohort.parquet' b using (stay_id)
where e.itemid in ({items}) and e.value = '1' and e.charttime < b.time_zero
""")
    con.execute("""
create temp table flagged as
select b.*,
  exists (select 1 from esrd_dx x where x.hadm_id = b.hadm_id) as esrd_icd_current_adm,
  exists (select 1 from esrd_dx x where x.subject_id = b.subject_id and x.admittime < b.admittime) as esrd_icd_prior_adm,
  b.stay_id in (select stay_id from dial_item) as dialysis_hx_item
from 'data/cohort/base_cohort.parquet' b
""")
    con.execute("""
create temp table out as
select *, (esrd_icd_current_adm or esrd_icd_prior_adm or dialysis_hx_item) as esrd_chronic_dialysis,
  (esrd_icd_prior_adm or dialysis_hx_item) as esrd_known_at_t0 from flagged
""")
    con.execute("copy (select * from out order by stay_id) to 'data/cohort/cohort_stage2.parquet' (format parquet)")
    print(con.execute("""
select count(*) stays, sum(esrd_chronic_dialysis::int) flagged,
  sum(esrd_icd_current_adm::int) icd_current, sum(esrd_icd_prior_adm::int) icd_prior, sum(dialysis_hx_item::int) item,
  sum((esrd_chronic_dialysis and not esrd_icd_current_adm and not esrd_icd_prior_adm)::int) item_only,
  sum((esrd_chronic_dialysis and not dialysis_hx_item)::int) icd_only
from out""").df().to_string())


if __name__ == "__main__":
    main()
