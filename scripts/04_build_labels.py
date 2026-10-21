"""Stage 3: KDIGO AKI onset times, label, and availability/observation flags.

Design follows MIT-LCP mimic-code kdigo_creatinine / kdigo_uo (rolling lookbacks, strict inequality, join labs on
subject_id, UO windows need documented hours). Onsets are only taken at ICU times, baselines may come from the
7 days before ICU admission. Stores onset TIMES so the horizon X can be changed without a rebuild.
Writes data/cohort/cohort_stage3.parquet (all stays from stage 2 with flags; filtering is done in the flow step).
"""
from pathlib import Path
import duckdb, yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/cohort/cohort_stage2.parquet', 'data/mimiciv/3.1_parquet/hosp/labevents.parquet', 'data/mimiciv/3.1_parquet/icu/chartevents.parquet', 'data/mimiciv/3.1_parquet/icu/outputevents.parquet', 'data/mimiciv/3.1_parquet/icu/procedureevents.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))
    P = Path(cfg["paths"]["parquet_root"])
    a, t, ids = cfg["aki"], cfg["task"], cfg["itemids"]
    cr_ids = ",".join(map(str, a["creatinine_itemid_for_label"]))
    cr_lo, cr_hi = a["creatinine_plausible_mg_dl"]
    w_lo, w_hi = a["weight_plausible_kg"]
    uo_ids = ",".join(map(str, ids["outputevents"]["urine"]))
    rrt_ids = ",".join(map(str, ids["procedureevents"]["dialysis"]))
    H = t["horizon_hours"]

    con = duckdb.connect()
    con.execute("set preserve_insertion_order=false")
    con.execute("create temp table cohort as select * from 'data/cohort/cohort_stage2.parquet'")

    # --- creatinine series (labs joined on subject_id so pre-admission labs with null hadm_id are kept) ---
    con.execute(f"""
create temp table cr as
select s.stay_id, l.charttime, avg(l.valuenum) cr
from cohort s join (
    select subject_id, charttime, valuenum from '{P}/hosp/labevents.parquet'
    where itemid in ({cr_ids}) and valuenum between {cr_lo} and {cr_hi}) l
  on l.subject_id = s.subject_id and l.charttime between s.intime - interval 7 day and s.outtime
group by s.stay_id, l.charttime
""")
    con.execute(f"""
create temp table cr_roll as
select *,
  min(cr) over (partition by stay_id order by charttime range between interval 48 hour preceding and interval 1 second preceding) low48,
  min(cr) over (partition by stay_id order by charttime range between interval 7 day preceding and interval 1 second preceding) low7
from cr
""")
    con.execute(f"""
create temp table cr_events as
select r.stay_id, r.charttime,
  (r.cr - r.low48 >= {a['creatinine_rise_mg_dl']}) as by_rise,
  (r.cr >= {a['creatinine_ratio']} * r.low7) as by_ratio
from cr_roll r join cohort s using (stay_id)
where r.charttime >= s.intime and ((r.cr - r.low48 >= {a['creatinine_rise_mg_dl']}) or (r.cr >= {a['creatinine_ratio']} * r.low7))
""")

    # --- weight: admission kg, else admission lbs, else first daily weight ---
    ci = ids["chartevents"]
    con.execute(f"""
create temp table wt as
select stay_id, arg_min(w, rank_key) as weight_kg, arg_min(src, rank_key) as weight_src from (
  select c.stay_id,
    case when c.itemid = {ci['weight_admission_lbs'][0]} then c.valuenum * 0.45359237 else c.valuenum end w,
    case c.itemid when {ci['weight_admission_kg'][0]} then 'admission_kg' when {ci['weight_admission_lbs'][0]} then 'admission_lbs' else 'daily' end src,
    (case c.itemid when {ci['weight_admission_kg'][0]} then 0 when {ci['weight_admission_lbs'][0]} then 1 else 2 end) * 1e15
      + epoch(c.charttime) rank_key
  from '{P}/icu/chartevents.parquet' c join cohort s using (stay_id)
  where c.itemid in ({ci['weight_admission_kg'][0]}, {ci['weight_admission_lbs'][0]}, {ci['weight_daily_kg'][0]})
    and c.valuenum is not null and c.charttime < s.time_zero
) where w between {w_lo} and {w_hi}
group by stay_id
""")

    # --- urine output ---
    con.execute(f"""
create temp table uo as
select o.stay_id, o.charttime, sum(o.value) vol
from '{P}/icu/outputevents.parquet' o join cohort s using (stay_id)
where o.itemid in ({uo_ids}) and o.value >= 0 and o.charttime between s.intime and s.outtime
group by 1, 2
""")
    con.execute("""
create temp table uo2 as
select stay_id, charttime,
  case when gap_h is null then 0 else vol end vol,      -- first record of a stay has no known interval
  coalesce(gap_h, 0) hrs
from (select *, date_diff('second', lag(charttime) over (partition by stay_id order by charttime), charttime) / 3600.0 gap_h from uo)
""")
    con.execute(f"""
create temp table uo_roll as
select u.*, w.weight_kg,
  sum(vol) over wnd vol6, sum(hrs) over wnd tm6, max(hrs) over wnd maxgap6
from uo2 u left join wt w using (stay_id)
window wnd as (partition by u.stay_id order by u.charttime range between interval 6 hour preceding and current row)
""")
    con.execute(f"""
create temp table uo_events as
select stay_id, charttime from uo_roll
where tm6 >= 6 and tm6 < 12 and weight_kg is not null and vol6 / weight_kg / tm6 < {a['uo_threshold_ml_kg_h']}
""")

    # variant: also require every charted interval in the 6 h window to be short, so one large record after a long
    # charting gap cannot trigger the criterion
    con.execute(f"""
create temp table uo_events_gap2 as
select stay_id, charttime from uo_roll
where tm6 >= 6 and tm6 < 12 and maxgap6 <= 2 and weight_kg is not null and vol6 / weight_kg / tm6 < {a['uo_threshold_ml_kg_h']}
""")

    # --- dialysis sessions in ICU ---
    con.execute(f"""
create temp table rrt as
select stay_id, min(starttime) first_rrt_start from '{P}/icu/procedureevents.parquet'
where itemid in ({rrt_ids}) group by stay_id
""")

    # --- assemble ---
    con.execute(f"""
create table stage3 as
select s.*,
  w.weight_kg, w.weight_src,
  (select min(charttime) from cr_events e where e.stay_id = s.stay_id and e.by_rise) as onset_creat_rise,
  (select min(charttime) from cr_events e where e.stay_id = s.stay_id and e.by_ratio) as onset_creat_ratio,
  (select min(charttime) from cr_events e where e.stay_id = s.stay_id) as onset_creat,
  (select min(charttime) from uo_events e where e.stay_id = s.stay_id) as onset_uo,
  (select min(charttime) from uo_events_gap2 e where e.stay_id = s.stay_id) as onset_uo_gap2,
  (select count(*) from cr c where c.stay_id = s.stay_id and c.charttime between s.intime and s.time_zero) as n_creat_0_to_t0,
  (select count(*) from cr c where c.stay_id = s.stay_id and c.charttime > s.time_zero and c.charttime <= s.time_zero + to_hours({H})) as n_creat_in_window,
  (select coalesce(sum(hrs), 0) from uo2 u where u.stay_id = s.stay_id and u.charttime > s.time_zero and u.charttime <= s.time_zero + to_hours({H})) as uo_hours_in_window,
  r.first_rrt_start,
  (s.outtime >= s.time_zero + to_hours({H})) as icu_covers_window
from cohort s left join wt w using (stay_id) left join rrt r using (stay_id)
""")
    con.execute("alter table stage3 add column onset_aki timestamp")
    con.execute("update stage3 set onset_aki = least(onset_creat, onset_uo)")
    con.execute("copy (select * from stage3 order by stay_id) to 'data/cohort/cohort_stage3.parquet' (format parquet)")
    print(con.execute("select count(*), count(weight_kg), count(onset_creat), count(onset_uo), count(onset_aki) from stage3").fetchall())


if __name__ == "__main__":
    main()
