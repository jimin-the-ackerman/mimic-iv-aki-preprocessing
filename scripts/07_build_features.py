"""Stage 5: hourly feature table (48 steps per stay) and the wide per-stay table derived from it.

Inputs : data/cohort/cohort_final.parquet, data/external/drug_map.parquet (from 06), Parquet tables, config.yaml
Outputs: data/features/hourly.parquet  (one row per stay and hour 0..47, values + *_obs mask + *_hsl hours-since-last)
         data/features/wide.parquet    (one row per stay: static features + summaries of the hourly table + labels)
Rules  : only data with charttime in [intime, time_zero) and storetime <= time_zero is used (no leakage);
         implausible values -> missing and counted; missing stays missing (no imputation).
Test   : LIMIT=300 python scripts/07_build_features.py  builds a small subset.
"""
import os
from pathlib import Path
import duckdb, yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/cohort/cohort_final.parquet', 'data/external/drug_map.parquet', 'data/mimiciv/3.1_parquet/hosp/labevents.parquet', 'data/mimiciv/3.1_parquet/hosp/admissions.parquet', 'data/mimiciv/3.1_parquet/hosp/diagnoses_icd.parquet', 'data/mimiciv/3.1_parquet/hosp/prescriptions.parquet', 'data/mimiciv/3.1_parquet/icu/chartevents.parquet', 'data/mimiciv/3.1_parquet/icu/inputevents.parquet', 'data/mimiciv/3.1_parquet/icu/outputevents.parquet', 'data/mimiciv/3.1_parquet/icu/procedureevents.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))
    P = Path(cfg["paths"]["parquet_root"])
    ids = cfg["itemids"]
    ranges = cfg["plausible_ranges"]
    drugs = cfg["drugs"]
    vaso = ",".join(map(str, drugs["vasopressor_itemids"]))
    OUT = Path(os.environ.get("OUT", "data/features")); OUT.mkdir(parents=True, exist_ok=True)
    LIMIT = os.environ.get("LIMIT")
    T = cfg["task"]["time_zero_hours"]
    L = lambda xs: ",".join(map(str, xs))

    con = duckdb.connect()
    con.execute("set preserve_insertion_order=false")
    lim = f"order by stay_id limit {int(LIMIT)}" if LIMIT else ""
    con.execute(f"create temp table c as select * from 'data/cohort/cohort_final.parquet' {lim}")
    # ---------------------------------------------------------------- raw events (stay_id, ts, var, val)
    ch = ids["chartevents"]
    chart_vars = {  # var -> (itemids, expression on valuenum)
        "hr": (ch["heart_rate"], "valuenum"), "sbp": (ch["sbp"], "valuenum"), "dbp": (ch["dbp"], "valuenum"),
        "mbp": (ch["mbp"], "valuenum"), "rr": (ch["resp_rate"], "valuenum"),
        "temp_c": (ch["temp_c"], "valuenum"), "weight_daily": (ch["weight_daily_kg"], "valuenum"),
        "dial_blood_flow": (ch["dialysis_blood_flow"], "valuenum"), "dialysate_rate": (ch["dialysate_rate"], "valuenum"),
        "ultrafiltrate_ml": (ch["ultrafiltrate_output"], "valuenum"),
    }
    lab = ids["labevents"]
    lab_vars = {
        "creatinine": [50912], "creatinine_wb": [52024], "bun": lab["bun"], "urine_creat": lab["urine_creatinine"],
        "na": lab["sodium"], "k": lab["potassium"], "cl": lab["chloride"], "hco3": lab["bicarbonate"],
        "phosphate": lab["phosphate"], "mg": lab["magnesium"], "uric_acid": lab["uric_acid"],
    }
    parts = []
    for v, (items, expr) in chart_vars.items():
        parts.append(f"select e.stay_id, e.charttime ts, '{v}' var, e.{expr} val from '{P}/icu/chartevents.parquet' e "
                     f"join c using (stay_id) where e.itemid in ({L(items)}) and e.valuenum is not null "
                     f"and e.charttime >= c.intime and e.charttime < c.time_zero and coalesce(e.storetime, e.charttime) <= c.time_zero")
    parts.append(f"select e.stay_id, e.charttime ts, 'temp_c', (e.valuenum - 32) * 5.0 / 9 from '{P}/icu/chartevents.parquet' e "
                 f"join c using (stay_id) where e.itemid in ({L(ch['temp_f'])}) and e.valuenum is not null "
                 f"and e.charttime >= c.intime and e.charttime < c.time_zero and coalesce(e.storetime, e.charttime) <= c.time_zero")
    for v, items in lab_vars.items():
        parts.append(f"select c.stay_id, l.charttime ts, '{v}' var, l.valuenum val from '{P}/hosp/labevents.parquet' l "
                     f"join c on c.subject_id = l.subject_id where l.itemid in ({L(items)}) and l.valuenum is not null "
                     f"and l.charttime >= c.intime and l.charttime < c.time_zero and coalesce(l.storetime, l.charttime) <= c.time_zero")
    uo = ids["outputevents"]
    def out_part(var, cond):
        return (f"select o.stay_id, o.charttime, '{var}', sum(o.value) from '{P}/icu/outputevents.parquet' o join c using (stay_id) "
                f"where {cond} and o.value is not null and o.charttime >= c.intime and o.charttime < c.time_zero "
                f"and coalesce(o.storetime, o.charttime) <= c.time_zero group by 1, 2")
    other_excl = uo["urine"] + uo["urine_excluded"] + uo["drainage"] + uo["stool"] + uo["not_output"]
    parts.append(out_part("urine_ml", f"o.itemid in ({L(uo['urine'])})"))
    parts.append(out_part("drain_ml", f"o.itemid in ({L(uo['drainage'])})"))
    parts.append(out_part("stool_ml", f"o.itemid in ({L(uo['stool'])})"))
    parts.append(out_part("other_output_ml", f"o.itemid not in ({L(other_excl)})"))
    con.execute("create temp table raw_ev as " + " union all ".join(parts))

    # plausibility: count and drop
    rng = " or ".join(f"(var = '{v}' and (val < {lo} or val > {hi}))" for v, (lo, hi) in ranges.items() if v not in ("intake_ml", "urine_ml_kg_h"))
    con.execute(f"create temp table outl as select stay_id, var, count(*) n from raw_ev where {rng} group by 1, 2")
    con.execute(f"create temp table ev as select r.stay_id, r.var, r.val, cast(floor(epoch(r.ts - c.intime) / 3600) as int) h "
                f"from raw_ev r join c using (stay_id) where not ({rng.replace('var', 'r.var').replace('val', 'r.val')})")

    # ---------------------------------------------------------------- intake (mL, allocated proportionally over hours), vasopressor and dialysis flags
    con.execute(f"""
create temp table intake_seg as
select i.stay_id, greatest(i.starttime, c.intime) s, least(i.endtime, c.time_zero) e, i.starttime s0, i.endtime e0, i.amount, c.intime
from '{P}/icu/inputevents.parquet' i join c using (stay_id)
where i.amountuom = 'mL' and i.amount > 0 and i.amount <= 10000 and i.starttime < c.time_zero and i.endtime > c.intime
""")
    con.execute(f"""
create temp table intake_h as
select stay_id, h, sum(amt) val from (
  select stay_id, h,
    case when epoch(e0 - s0) <= 0 then amount
         else amount * greatest(0, epoch(least(e, intime + to_hours(h + 1)) - greatest(s, intime + to_hours(h)))) / epoch(e0 - s0) end amt
  from (select *, unnest(range(cast(floor(epoch(s - intime) / 3600) as int), cast(least({T} - 1, floor(epoch(e - intime) / 3600)) as int) + 1)) h from intake_seg)
) where amt > 0 group by 1, 2
""")
    def interval_flag(table_sql, name):
        con.execute(f"""
    create temp table {name} as
    select distinct stay_id, h from (
      select stay_id, unnest(range(cast(floor(epoch(s - intime) / 3600) as int), cast(least({T} - 1, floor(epoch(e - intime) / 3600)) as int) + 1)) h
      from ({table_sql}) where e > s)""")
    interval_flag(f"""select v.stay_id, greatest(v.starttime, c.intime) s, least(v.endtime, c.time_zero) e, c.intime
    from '{P}/icu/inputevents.parquet' v join c using (stay_id) where v.itemid in ({vaso}) and v.starttime < c.time_zero and v.endtime > c.intime""", "vaso_h")
    dial = f"""select p.stay_id, greatest(p.starttime, c.intime) s, least(p.endtime, c.time_zero) e, c.intime
    from '{P}/icu/procedureevents.parquet' p join c using (stay_id) where p.itemid in ({{items}}) and p.starttime < c.time_zero and p.endtime > c.intime"""
    interval_flag(dial.format(items=L(ids["procedureevents"]["dialysis"])), "dial_h")
    interval_flag(dial.format(items="225802"), "crrt_h")

    # urine output RATE (mL/kg/h): each record's volume covers the time since the previous record; only intervals <= 6 h are used,
    # the volume is spread over the hours the interval covers; an hour needs >= 30 min of covered time to get a rate.
    ulo, uhi = ranges["urine_ml"]
    con.execute(f"""
create temp table uo_int as
select * from (
  select r.stay_id, r.ts, r.val vol, lag(r.ts) over (partition by r.stay_id order by r.ts) prev_ts, c.intime, c.weight_kg
  from raw_ev r join c using (stay_id) where r.var = 'urine_ml' and r.val between {ulo} and {uhi})
where prev_ts is not null and epoch(ts - prev_ts) between 1 and 6 * 3600 and weight_kg is not null""")
    con.execute(f"""
create temp table uo_rate_h as
select stay_id, h, sum(vol_a) / any_value(weight_kg) / (sum(sec) / 3600.0) as val from (
  select stay_id, weight_kg, h,
    vol * greatest(0, epoch(least(ts, intime + to_hours(h + 1)) - greatest(prev_ts, intime + to_hours(h)))) / epoch(ts - prev_ts) as vol_a,
    greatest(0, epoch(least(ts, intime + to_hours(h + 1)) - greatest(prev_ts, intime + to_hours(h)))) as sec
  from (select *, unnest(range(cast(floor(epoch(prev_ts - intime) / 3600) as int), least({T} - 1, cast(floor(epoch(ts - intime) / 3600) as int)) + 1)) h from uo_int)
  where h >= 0)
group by stay_id, h having sum(sec) >= 1800""")
    rlo, rhi = ranges["urine_ml_kg_h"]
    con.execute(f"delete from uo_rate_h where val < {rlo} or val > {rhi}")
    con.execute("""
create temp table uo_rate_stay as
select * from (select stay_id, sum(vol) / any_value(weight_kg) / (sum(epoch(ts - prev_ts)) / 3600.0) as urine_ml_kg_h_overall from uo_int group by 1)
where urine_ml_kg_h_overall <= 20""")

    # ---------------------------------------------------------------- hourly table
    meas = list(chart_vars) + list(lab_vars) + ["urine_ml", "drain_ml", "stool_ml", "other_output_ml"]
    sums = {"urine_ml", "drain_ml", "stool_ml", "other_output_ml", "ultrafiltrate_ml"}
    sel, ob = [], []
    for v in meas:
        agg = "sum" if v in sums else "avg"
        con.execute(f"create temp table a_{v} as select stay_id, h, {agg}(val) val from ev where var = '{v}' group by 1, 2")
        sel.append(f"a_{v}.val as {v}"); ob.append(v)
    SPECIAL = {"intake_ml": "intake_h", "urine_ml_kg_h": "uo_rate_h"}   # already one value per (stay, hour)
    for v, tbl in SPECIAL.items():
        con.execute(f"create temp table a_{v} as select * from {tbl}"); sel.append(f"a_{v}.val as {v}"); ob.append(v)
    joins = "".join(f" left join a_{v} on a_{v}.stay_id = g.stay_id and a_{v}.h = g.hour" for v in ob if v not in SPECIAL)
    joins += "".join(f" left join a_{v} on a_{v}.stay_id = g.stay_id and a_{v}.h = g.hour" for v in SPECIAL)
    joins += " left join vaso_h on vaso_h.stay_id = g.stay_id and vaso_h.h = g.hour"
    joins += " left join dial_h on dial_h.stay_id = g.stay_id and dial_h.h = g.hour"
    joins += " left join crrt_h on crrt_h.stay_id = g.stay_id and crrt_h.h = g.hour"
    con.execute(f"""
create temp table hourly0 as
select g.stay_id, g.hour, {", ".join(sel)},
  (vaso_h.h is not null)::int as vasopressor_active, (dial_h.h is not null)::int as dialysis_active, (crrt_h.h is not null)::int as crrt_active
from (select stay_id, unnest(range(0, {T})) as hour from c) g {joins}
""")
    # computed eGFR from hourly creatinine (age, sex, weight are static); no race term
    con.execute("""
create temp table hourly1 as
select h.*,
  case when creatinine is not null then 175 * power(creatinine, -1.154) * power(c.age_at_icu, -0.203) * (case when c.gender = 'F' then 0.742 else 1 end) end as egfr_mdrd,
  case when creatinine is not null and c.weight_kg is not null then (140 - c.age_at_icu) * c.weight_kg / (72 * creatinine) * (case when c.gender = 'F' then 0.85 else 1 end) end as egfr_cg,
  case when creatinine is not null then 142 * power(least(creatinine / (case when c.gender = 'F' then 0.7 else 0.9 end), 1), case when c.gender = 'F' then -0.241 else -0.302 end)
     * power(greatest(creatinine / (case when c.gender = 'F' then 0.7 else 0.9 end), 1), -1.2) * power(0.9938, c.age_at_icu) * (case when c.gender = 'F' then 1.012 else 1 end) end as egfr_ckdepi
from hourly0 h join c using (stay_id)
""")
    obs_cols = ", ".join(f"({v} is not null)::int as {v}_obs" for v in ob)
    con.execute(f"create temp table hourly2 as select *, {obs_cols} from hourly1")
    hsl = ", ".join(f"hour - max(case when {v}_obs = 1 then hour end) over (partition by stay_id order by hour rows between unbounded preceding and current row) as {v}_hsl" for v in ob)
    con.execute(f"create temp table hourly as select *, {hsl} from hourly2 order by stay_id, hour")
    con.execute(f"copy hourly to '{OUT}/hourly.parquet' (format parquet)")
    print("hourly:", con.execute("select count(*), count(distinct stay_id) from hourly").fetchone())

    # ---------------------------------------------------------------- static features
    con.execute(f"""
create temp table cr_base as
select c.stay_id,
  min(l.valuenum) filter (where l.charttime < c.time_zero) as creat_baseline_7d,
  arg_max(l.valuenum, l.charttime) filter (where l.charttime < c.intime) as creat_last_pre_icu
from c join '{P}/hosp/labevents.parquet' l on l.subject_id = c.subject_id
where l.itemid = 50912 and l.valuenum between {ranges['creatinine'][0]} and {ranges['creatinine'][1]}
  and l.charttime >= c.intime - interval 7 day and l.charttime < c.time_zero and coalesce(l.storetime, l.charttime) <= c.time_zero
group by 1""")
    con.execute(f"""
create temp table ckd as
select c.stay_id,
  bool_or(d.hadm_id = c.hadm_id) as ckd_icd_current_adm,
  bool_or(a.admittime < c.admittime) as ckd_icd_prior_adm
from c join '{P}/hosp/diagnoses_icd.parquet' d on d.subject_id = c.subject_id
join '{P}/hosp/admissions.parquet' a on a.hadm_id = d.hadm_id
where (d.icd_version = 10 and d.icd_code like 'N18%' and d.icd_code <> 'N186')
   or (d.icd_version = 9 and d.icd_code in ('5851','5852','5853','5854','5855','5859'))
group by 1""")
    # ---- drug features: orders -> ATC classes (drug_map from 06), NDC match first, then name match
    LOCAL = "EYE|EAR|^TP$|^OU$|^OD$|^OS$|INTRAVITREAL|^IVT$"      # skin, eye and ear routes
    ORAL = "^PO|^NG$|ORAL"
    con.execute(f"""
create temp table rx_orders as
select c.stay_id, lower(p.drug) drug, upper(p.route) route,
  case when p.ndc is null or p.ndc in ('0', '') then null else p.ndc end ndc
from c join '{P}/hosp/prescriptions.parquet' p on p.hadm_id = c.hadm_id
where p.starttime < c.time_zero and coalesce(p.stoptime, p.starttime) >= c.intime""")
    con.execute("""
create temp table rx_atc as
select o.stay_id, o.route, unnest(string_split(coalesce(nullif(mn.atc_codes, ''), nullif(mm.atc_codes, ''), ''), ';')) code
from rx_orders o
left join 'data/external/drug_map.parquet' mn on mn.kind = 'ndc' and mn.key = o.ndc
left join 'data/external/drug_map.parquet' mm on mm.kind = 'name' and mm.key = o.drug""")
    con.execute(f"""
create temp table rx_codes as
select distinct stay_id, code, regexp_matches(coalesce(route, ''), '^IV($|[ _-])') as is_iv, coalesce(route, '') = 'IM' as is_im
from rx_atc
where code <> '' and (
  case when regexp_matches(coalesce(route, ''), '{LOCAL}') then left(code, 1) in ('D', 'S')
       else left(code, 1) not in ('D', 'S') and (left(code, 3) <> 'A07' or regexp_matches(coalesce(route, ''), '{ORAL}')) end)""")
    con.execute("""
create temp table rx_ing as
select o.stay_id, lower(coalesce(nullif(mn.ingredients, ''), nullif(mm.ingredients, ''), '')) ing,
  regexp_matches(coalesce(o.route, ''), '^IV($|[ _-])') as is_iv, coalesce(o.route, '') = 'IM' as is_im
from rx_orders o
left join 'data/external/drug_map.parquet' mn on mn.kind = 'ndc' and mn.key = o.ndc
left join 'data/external/drug_map.parquet' mm on mm.kind = 'name' and mm.key = o.drug""")
    code_sel, ing_sel, kid_names = [], [], []
    for key, d in drugs["kidney_relevant"].items():
        route = (" and (is_iv" + (" or is_im" if d.get("im_too") else "") + ")") if d.get("iv") else ""
        if "atc" in d:
            name = f"atc_{d['atc'][0]}_{key}"
            code_sel.append(f"coalesce(bool_or(({' or '.join(f'code like {chr(39)}{p}%{chr(39)}' for p in d['atc'])}){route}), false) as {name}")
        else:
            name = f"drug_{key}"
            ing_sel.append(f"coalesce(bool_or(({' or '.join(f'ing like {chr(39)}%{i}%{chr(39)}' for i in d['ingredients'])}){route}), false) as {name}")
        kid_names.append(name)
    n_stays = con.execute("select count(*) from c").fetchone()[0]
    atc3 = [r[0] for r in con.execute(f"select left(code, 4) k from rx_codes where length(code) >= 4 group by 1 "
                                      f"having count(distinct stay_id) >= {drugs['atc_min_stay_fraction']} * {n_stays} order by 1").fetchall()]
    atc3_sel = [f"coalesce(bool_or(left(code, 4) = '{k}'), false) as atc3_{k}" for k in atc3]
    con.execute(f"create temp table rx_a as select stay_id, {', '.join(code_sel + atc3_sel)} from rx_codes group by 1")
    con.execute(f"create temp table rx_b as select stay_id, {', '.join(ing_sel)} from rx_ing group by 1")
    con.execute("create temp table rx as select c.stay_id, rx_a.* exclude (stay_id), rx_b.* exclude (stay_id) from c left join rx_a using (stay_id) left join rx_b using (stay_id)")
    atc_cols = kid_names + [f"atc3_{k}" for k in atc3]

    con.execute(f"""
create temp table dial_static as
select c.stay_id, count(*) as n_dialysis_sessions_before_t0,
  min(epoch(p.starttime - c.intime) / 3600.0) as first_dialysis_hour
from c join '{P}/icu/procedureevents.parquet' p using (stay_id)
where p.itemid in ({L(ids['procedureevents']['dialysis'])}) and p.starttime < c.time_zero group by 1""")

    # ---------------------------------------------------------------- wide table
    hv = ob + ["egfr_mdrd", "egfr_cg", "egfr_ckdepi"]
    aggs = []
    for v in hv:
        if v in sums or v == "intake_ml":
            aggs.append(f"sum({v}) as {v}_total")
        else:
            aggs += [f"min({v}) as {v}_min", f"max({v}) as {v}_max", f"avg({v}) as {v}_mean",
                     f"arg_min({v}, hour) filter (where {v} is not null) as {v}_first",
                     f"arg_max({v}, hour) filter (where {v} is not null) as {v}_last"]
        if v in ob:
            aggs.append(f"sum({v}_obs) as {v}_n_hours_obs")
    aggs += ["sum(vasopressor_active) as vasopressor_hours", "sum(dialysis_active) as dialysis_hours", "sum(crrt_active) as crrt_hours"]
    con.execute(f"create temp table agg as select stay_id, {', '.join(aggs)} from hourly group by 1")
    outl_cols = ", ".join(f"coalesce(max(n) filter (where var = '{v}'), 0) as n_outlier_{v}" for v in ranges if v not in ("intake_ml", "urine_ml_kg_h"))
    con.execute(f"create temp table outl_w as select c.stay_id, {outl_cols} from c left join outl using (stay_id) group by 1")
    rx_cols = ", ".join(f"coalesce(rx.{n}, false) as {n}" for n in atc_cols) + ", (" + " + ".join(f"coalesce(rx.{n}, false)::int" for n in kid_names) + ") as n_kidney_relevant_classes"
    con.execute(f"""
create temp table wide as
select c.stay_id, c.subject_id, c.hadm_id, c.intime, c.time_zero, c.anchor_year_group,
  c.age_at_icu, c.gender, c.first_careunit, c.admission_type, c.weight_kg, c.weight_src,
  c.esrd_chronic_dialysis, c.esrd_known_at_t0, c.esrd_icd_current_adm, c.esrd_icd_prior_adm, c.dialysis_hx_item,
  coalesce(ckd.ckd_icd_prior_adm, false) as ckd_icd_prior_adm, coalesce(ckd.ckd_icd_current_adm, false) as ckd_icd_current_adm,
  cb.creat_baseline_7d, cb.creat_last_pre_icu,
  coalesce(ds.n_dialysis_sessions_before_t0, 0) as n_dialysis_sessions_before_t0, ds.first_dialysis_hour,
  {rx_cols},
  a.* exclude (stay_id),
  ur.urine_ml_kg_h_overall,
  case when a.intake_ml_n_hours_obs > 0 and a.urine_ml_n_hours_obs > 0 then a.intake_ml_total - a.urine_ml_total - coalesce(a.drain_ml_total, 0) - coalesce(a.stool_ml_total, 0) - coalesce(a.other_output_ml_total, 0) end as fluid_balance_ml,
  o.* exclude (stay_id),
  c.y as label_aki_next_{cfg['task']['horizon_hours']}h, c.aki_by_creat, c.aki_by_uo,
  epoch(c.onset_aki - c.intime) / 3600.0 as onset_aki_hour, epoch(c.onset_creat - c.intime) / 3600.0 as onset_creat_hour,
  epoch(c.onset_uo - c.intime) / 3600.0 as onset_uo_hour, epoch(c.onset_uo_reference - c.intime) / 3600.0 as onset_uo_reference_hour,
  c.rrt_before_t0, c.hospital_expire_flag
from c left join agg a using (stay_id) left join outl_w o using (stay_id) left join ckd using (stay_id)
left join cr_base cb using (stay_id) left join rx using (stay_id) left join dial_static ds using (stay_id) left join uo_rate_stay ur using (stay_id)
order by c.stay_id""")
    con.execute(f"copy wide to '{OUT}/wide.parquet' (format parquet)")
    n, ncol = con.execute("select count(*), 1 from wide").fetchone()[0], len(con.execute("describe wide").fetchall())
    print(f"wide: {n} rows x {ncol} columns; hourly: {len(con.execute('describe hourly').fetchall())} columns")


if __name__ == "__main__":
    main()
