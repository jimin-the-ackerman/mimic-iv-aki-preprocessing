"""Stage 12: standalone bilingual report PREPROCESSING_REPORT.md (English, then Korean) for posting outside the repository.

The report has no links to other files. Item numbers, ranges, drug rules, counts and column lists come from config.yaml,
the Parquet files and the flow tables. The script stops if a column of the feature tables is not covered by the report.
"""
import csv
import json
import re
from importlib.metadata import version
from pathlib import Path

import duckdb
import yaml

OUT = Path("PREPROCESSING_REPORT.md")


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/features/hourly.parquet', 'data/features/wide.parquet', 'data/features/splits.parquet',
                'data/cohort/flow_base.csv', 'data/cohort/flow_final.csv', 'data/external/drug_map.parquet', 'data/external/drug_map_info.json',
                'data/mimiciv/3.1_parquet/hosp/prescriptions.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))
    ids, ranges, drugs, aki, task = cfg["itemids"], cfg["plausible_ranges"], cfg["drugs"], cfg["aki"], cfg["task"]
    H, T = task["horizon_hours"], task["time_zero_hours"]
    con = duckdb.connect()
    cols = lambda t: [r[0] for r in con.execute(f"describe select * from 'data/features/{t}.parquet'").fetchall()]
    wide_cols, hourly_cols = cols("wide"), cols("hourly")
    flow = lambda f: list(csv.DictReader(open(f"data/cohort/{f}")))
    flow_base, flow_final = flow("flow_base.csv"), flow("flow_final.csv")
    info = json.load(open("data/external/drug_map_info.json"))
    n = lambda x: f"{int(x):,}"

    # ---- numbers from the outputs
    res = con.execute("""select count(*), count(distinct subject_id), sum(label_aki_next_24h::int), sum(aki_by_creat::int), sum(aki_by_uo::int),
        sum((aki_by_creat and aki_by_uo)::int), sum(esrd_chronic_dialysis::int), round(median(age_at_icu), 1), round(100 * avg((gender = 'F')::int), 1),
        sum(hospital_expire_flag) from 'data/features/wide.parquet'""").fetchone()
    n_stay, n_pat, n_pos, n_cr, n_uo, n_both, n_esrd, med_age, pct_f, n_death = res
    split_rows = con.execute("""select 'split_random', split_random, count(*), sum(label_aki_next_24h::int) from 'data/features/splits.parquet' s join 'data/features/wide.parquet' w using (stay_id) group by 2
        union all select 'split_temporal', split_temporal, count(*), sum(label_aki_next_24h::int) from 'data/features/splits.parquet' s join 'data/features/wide.parquet' w using (stay_id) group by 2
        union all select 'split_hybrid', split_hybrid, count(*), sum(label_aki_next_24h::int) from 'data/features/splits.parquet' s join 'data/features/wide.parquet' w using (stay_id) group by 2""").fetchall()
    sp = {(a, b): (c, d) for a, b, c, d in split_rows}
    n_orders, pct_atc = con.execute("""
        with o as (select lower(p.drug) drug, case when p.ndc is null or p.ndc in ('0', '') then null else p.ndc end ndc
                   from 'data/mimiciv/3.1_parquet/hosp/prescriptions.parquet' p join 'data/features/wide.parquet' w on w.hadm_id = p.hadm_id
                   where p.starttime < w.time_zero and coalesce(p.stoptime, p.starttime) >= w.intime)
        select count(*), round(100.0 * avg((coalesce(nullif(mn.atc_codes, ''), nullif(mm.atc_codes, ''), '') <> '')::int), 1)
        from o left join 'data/external/drug_map.parquet' mn on mn.kind = 'ndc' and mn.key = o.ndc
               left join 'data/external/drug_map.parquet' mm on mm.kind = 'name' and mm.key = o.drug""").fetchone()
    atc3 = sorted(c[5:] for c in wide_cols if c.startswith("atc3_"))
    pkgs = f"Python {'.'.join(__import__('platform').python_version_tuple())}, DuckDB {version('duckdb')}, pandas {version('pandas')}, pyarrow {version('pyarrow')}"

    # ---- variable table: (name, English, Korean, unit, table, itemids, hourly rule)
    ch, lab, ou = ids["chartevents"], ids["labevents"], ids["outputevents"]
    I = lambda xs: ", ".join(str(x) for x in xs)
    VARS = [
        ("hr", "Heart rate", "심박수", "bpm", "chartevents", I(ch["heart_rate"]), "mean"),
        ("sbp", "Systolic blood pressure, non-invasive and arterial pooled", "수축기 혈압(비침습과 동맥을 합산)", "mmHg", "chartevents", I(ch["sbp"]), "mean"),
        ("dbp", "Diastolic blood pressure, non-invasive and arterial pooled", "이완기 혈압(비침습과 동맥을 합산)", "mmHg", "chartevents", I(ch["dbp"]), "mean"),
        ("mbp", "Mean blood pressure, non-invasive and arterial pooled", "평균 혈압(비침습과 동맥을 합산)", "mmHg", "chartevents", I(ch["mbp"]), "mean"),
        ("rr", "Respiratory rate", "호흡수", "/min", "chartevents", I(ch["resp_rate"]), "mean"),
        ("temp_c", "Body temperature (Fahrenheit converted: (F - 32) x 5 / 9)", "체온(화씨는 (F - 32) x 5 / 9로 변환)", "°C", "chartevents", f"{I(ch['temp_c'])} (Celsius), {I(ch['temp_f'])} (Fahrenheit)", "mean"),
        ("weight_daily", "Daily weight", "일일 체중", "kg", "chartevents", I(ch["weight_daily_kg"]), "mean"),
        ("dial_blood_flow", "Dialysis blood flow", "투석 혈류량", "mL/min", "chartevents", I(ch["dialysis_blood_flow"]), "mean"),
        ("dialysate_rate", "Dialysate flow rate", "투석액 유량", "mL/h", "chartevents", I(ch["dialysate_rate"]), "mean"),
        ("ultrafiltrate_ml", "Ultrafiltrate output", "한외여과량", "mL", "chartevents", I(ch["ultrafiltrate_output"]), "sum"),
        ("creatinine", "Serum creatinine", "혈청 크레아티닌", "mg/dL", "labevents", "50912", "mean"),
        ("creatinine_wb", "Whole-blood creatinine (blood gas)", "전혈 크레아티닌(혈액가스)", "mg/dL", "labevents", "52024", "mean"),
        ("bun", "Blood urea nitrogen", "혈액요소질소", "mg/dL", "labevents", I(lab["bun"]), "mean"),
        ("urine_creat", "Urine creatinine", "소변 크레아티닌", "mg/dL", "labevents", I(lab["urine_creatinine"]), "mean"),
        ("na", "Sodium, chemistry and whole blood pooled", "나트륨(화학검사와 전혈을 합산)", "mEq/L", "labevents", I(lab["sodium"]), "mean"),
        ("k", "Potassium, chemistry and whole blood pooled", "칼륨(화학검사와 전혈을 합산)", "mEq/L", "labevents", I(lab["potassium"]), "mean"),
        ("cl", "Chloride, chemistry and whole blood pooled", "염소(화학검사와 전혈을 합산)", "mEq/L", "labevents", I(lab["chloride"]), "mean"),
        ("hco3", "Bicarbonate, chemistry and calculated pooled", "중탄산염(화학검사와 계산값을 합산)", "mEq/L", "labevents", I(lab["bicarbonate"]), "mean"),
        ("phosphate", "Phosphate", "인산염", "mg/dL", "labevents", I(lab["phosphate"]), "mean"),
        ("mg", "Magnesium", "마그네슘", "mg/dL", "labevents", I(lab["magnesium"]), "mean"),
        ("uric_acid", "Uric acid", "요산", "mg/dL", "labevents", I(lab["uric_acid"]), "mean"),
        ("urine_ml", "Urine output", "소변량", "mL", "outputevents", I(ou["urine"]), "sum"),
        ("drain_ml", "Drain output", "배액량", "mL", "outputevents", f"{len(ou['drainage'])} items (list in the code configuration)", "sum"),
        ("stool_ml", "Stool and ostomy output", "대변량(장루 포함)", "mL", "outputevents", I(ou["stool"]), "sum"),
        ("other_output_ml", "Other output: every output item that is not urine, drain, stool or excluded", "기타 배출량: 소변, 배액, 대변, 제외 항목이 아닌 모든 배출 항목", "mL", "outputevents", "all remaining items", "sum"),
    ]
    VARS_KR_IDS = lambda s: (s.replace("items (list in the code configuration)", "개 항목(코드 설정에 목록 있음)").replace("all remaining items", "나머지 모든 항목")
                              .replace("(Celsius)", "(섭씨)").replace("(Fahrenheit)", "(화씨)"))
    rng = lambda v: f"{ranges[v][0]} to {ranges[v][1]}" if v in ranges else "-"
    rng_kr = lambda v: f"{ranges[v][0]}~{ranges[v][1]}" if v in ranges else "-"
    not_out = I(ou["not_output"] + ou["urine_excluded"])

    # ---- coverage check: every column of both tables must be explained by a family below
    base_hourly = [v[0] for v in VARS] + ["intake_ml", "urine_ml_kg_h"]
    exp_h = {"stay_id", "hour", "vasopressor_active", "dialysis_active", "crrt_active", "egfr_mdrd", "egfr_cg", "egfr_ckdepi"}
    for v in base_hourly: exp_h |= {v, f"{v}_obs", f"{v}_hsl"}
    assert set(hourly_cols) == exp_h, ("hourly columns not covered", sorted(set(hourly_cols) ^ exp_h))
    SUMS = {"urine_ml", "drain_ml", "stool_ml", "other_output_ml", "ultrafiltrate_ml", "intake_ml"}
    STATIC = ["stay_id", "subject_id", "hadm_id", "intime", "time_zero", "anchor_year_group", "age_at_icu", "gender", "first_careunit", "admission_type",
              "weight_kg", "weight_src", "esrd_chronic_dialysis", "esrd_known_at_t0", "esrd_icd_current_adm", "esrd_icd_prior_adm", "dialysis_hx_item",
              "ckd_icd_prior_adm", "ckd_icd_current_adm", "creat_baseline_7d", "creat_last_pre_icu", "n_dialysis_sessions_before_t0", "first_dialysis_hour",
              "vasopressor_hours", "dialysis_hours", "crrt_hours", "urine_ml_kg_h_overall", "fluid_balance_ml", "n_kidney_relevant_classes",
              f"label_aki_next_{H}h", "aki_by_creat", "aki_by_uo", "onset_aki_hour", "onset_creat_hour", "onset_uo_hour", "onset_uo_reference_hour",
              "rrt_before_t0", "hospital_expire_flag"]
    kid = [f"atc_{d['atc'][0]}_{k}" if "atc" in d else f"drug_{k}" for k, d in drugs["kidney_relevant"].items()]
    exp_w = set(STATIC) | set(kid) | {f"atc3_{c}" for c in atc3} | {f"n_outlier_{v}" for v in ranges if v not in ("intake_ml", "urine_ml_kg_h")}
    stat_cols = {}
    for v in base_hourly:
        fam = ([f"{v}_total"] if v in SUMS else [f"{v}_{s}" for s in ("min", "max", "mean", "first", "last")]) + [f"{v}_n_hours_obs"]
        stat_cols[v] = fam; exp_w |= set(fam)
    for e in ("egfr_mdrd", "egfr_cg", "egfr_ckdepi"):
        stat_cols[e] = [f"{e}_{s}" for s in ("min", "max", "mean", "first", "last")]; exp_w |= set(stat_cols[e])
    assert set(wide_cols) == exp_w, ("wide columns not covered", sorted(set(wide_cols) ^ exp_w))

    def build(L):
        t = lambda en, kr: en if L == "en" else kr
        E = []
        w = E.append
        w(t("# English", "# 한국어"))
        w("")
        # ------------------------------------------------------------------ 0
        w(t("## Preprocessing of MIMIC-IV 3.1 for AKI prediction in the ICU", "## ICU의 AKI 예측을 위한 MIMIC-IV 3.1 전처리"))
        w("")
        w(t(f"This report describes how the preprocessed dataset was made. The model reads the first {T} hours of ICU data of a stay. It predicts whether acute kidney injury (AKI) starts in the next {H} hours. Every number below comes from the pipeline outputs, and every feature is listed with its derivation.",
            f"이 보고서는 전처리 데이터 세트를 만든 방법을 설명한다. 모델은 한 입실의 첫 {T}시간 ICU 데이터를 읽고, 이후 {H}시간 안에 급성 신손상(AKI)이 시작하는지 예측한다. 아래의 모든 숫자는 파이프라인 출력에서 나왔고, 모든 피처는 유도 방법과 함께 나열한다."))
        w("")
        w(t("| Item | Value |", "| 항목 | 값 |")); w("| --- | --- |")
        for a, b in [
            (t("Source data", "원본 데이터"), "MIMIC-IV 3.1 (hosp, icu)"),
            (t("ICU stays in the source", "원본의 ICU 입실"), f"{n(flow_base[0]['stays'])} ({n(flow_base[0]['patients'])}{t(' patients', '명')})"),
            (t("ICU stays in the dataset", "데이터 세트의 ICU 입실"), f"{n(n_stay)} ({n(n_pat)}{t(' patients', '명')})"),
            (t("Stays with label 1", "라벨 1인 입실"), f"{n(n_pos)} ({100 * n_pos / n_stay:.1f}%)"),
            (t("Label 1 by creatinine criteria / urine criterion / both", "크레아티닌 기준 / 소변량 기준 / 둘 다로 라벨 1"), f"{n(n_cr)} / {n(n_uo)} / {n(n_both)}"),
            (t("Hourly table", "hourly 테이블"), t(f"{n(n_stay * T)} rows ({n(n_stay)} stays x {T} hours), {len(hourly_cols)} columns", f"{n(n_stay * T)}행(입실 {n(n_stay)}건 x {T}시간), {len(hourly_cols)}칼럼")),
            (t("Wide table", "wide 테이블"), t(f"{n(n_stay)} rows (one per stay), {len(wide_cols)} columns", f"{n(n_stay)}행(입실당 1행), {len(wide_cols)}칼럼")),
            (t("Median age / female", "나이 중앙값 / 여성"), f"{med_age}{t(' years', '세')} / {pct_f}%"),
            (t("Deaths in hospital", "원내 사망"), t(f"{n(n_death)} stays", f"{n(n_death)}건")),
            (t("Software", "소프트웨어"), pkgs),
        ]:
            w(f"| {a} | {b} |")
        w("")
        # ------------------------------------------------------------------ 1 time axis & cohort
        w(t("### 1. Time axis and unit", "### 1. 시간 축과 단위"))
        w("")
        w(t(f"- The unit of the dataset is the ICU stay (`stay_id`).\n- `intime` is the ICU admission time. **Time zero** is `intime` + {T} hours. It is the prediction time.\n- The **prediction window** is the {H} hours after time zero.\n- Every feature uses only data from before time zero (see section 4.1).",
            f"- 데이터 세트의 단위는 ICU 입실(`stay_id`)이다.\n- `intime`은 ICU 입실 시각이다. **time zero**는 `intime` + {T}시간이며 예측 시점이다.\n- **예측 구간**은 time zero 이후 {H}시간이다.\n- 모든 피처는 time zero 이전의 데이터만 사용한다(4.1절 참고)."))
        w("")
        w(t("### 2. Cohort rules", "### 2. 코호트 규칙"))
        w("")
        R = [
            ("R1", "First ICU stay of the hospital admission", "입원의 첫 번째 ICU 입실"),
            ("R2", "Age at ICU admission is 18 years or more", "ICU 입실 시 나이가 18세 이상"),
            ("R3", f"ICU stay is {T} hours long or longer", f"ICU 재원이 {T}시간 이상"),
            ("R4", "A weight exists (see `weight_kg`)", "체중이 있다(`weight_kg` 참고)"),
            ("R5", "At least 2 creatinine values between ICU admission and time zero", "ICU 입실부터 time zero까지 크레아티닌 값이 2개 이상"),
            ("R6", "No AKI starts before time zero", "time zero 이전에 AKI가 시작하지 않았다"),
            ("R7", "The outcome is known: AKI starts in the prediction window, or the ICU stay lasts until the window ends (`outtime` >= time zero + window)", "결과를 알 수 있다: 예측 구간 안에서 AKI가 시작하거나 ICU 재원이 구간 끝까지 이어진다(`outtime` >= time zero + 구간)"),
            ("R8", "Not a non-ESRD patient who starts dialysis in the ICU before time zero", "ESRD가 아닌 환자가 time zero 이전에 ICU에서 투석을 시작한 입실이 아니다"),
            ("R9", "Not a label-0 stay whose prediction window has no creatinine value and less than 6 hours of urine data", "예측 구간에 크레아티닌 값이 없고 소변 데이터가 6시간 미만인 라벨 0 입실이 아니다"),
        ]
        counts = {"R1": flow_base[1], "R2": flow_base[2], "R3": flow_base[3], "R4": flow_final[1], "R5": flow_final[2], "R6": flow_final[3], "R7": flow_final[4], "R8": flow_final[5], "R9": flow_final[6]}
        w(t("| Rule | Condition | Stays left | Patients left |", "| 규칙 | 조건 | 남은 입실 | 남은 환자 |")); w("| --- | --- | --- | --- |")
        w(f"| - | {t('All ICU stays', '전체 ICU 입실')} | {n(flow_base[0]['stays'])} | {n(flow_base[0]['patients'])} |")
        for r, en, kr in R:
            w(f"| {r} | {t(en, kr)} | {n(counts[r]['stays'])} | {n(counts[r]['patients'])} |")
        w("")
        w(t("The pipeline applies the rules in this order. Stays of ESRD and chronic dialysis patients are kept and flagged (`esrd_chronic_dialysis`).",
            "파이프라인은 이 순서로 규칙을 적용한다. ESRD 환자와 만성 투석 환자의 입실은 제거하지 않고 플래그(`esrd_chronic_dialysis`)로 표시한다."))
        w("")
        # ------------------------------------------------------------------ 3 label
        w(t("### 3. Label", "### 3. 라벨"))
        w("")
        w(t(f"`label_aki_next_{H}h` is 1 if the first AKI of the stay starts after time zero and up to {H} hours after time zero. AKI starts at the first time that one of three KDIGO criteria is true.",
            f"`label_aki_next_{H}h`는 입실의 첫 AKI가 time zero 이후 {H}시간 이내에 시작하면 1이다. 세 가지 KDIGO 기준 중 하나가 처음 참이 되는 시점에 AKI가 시작한다."))
        w("")
        w(t("| Criterion | Definition | Computation |", "| 기준 | 정의 | 계산 |")); w("| --- | --- | --- |")
        w(t(f"| 1 | Creatinine rises by at least {aki['creatinine_rise_mg_dl']} mg/dL within {aki['creatinine_rise_window_hours']} hours | A creatinine value is compared with the lowest earlier value in the {aki['creatinine_rise_window_hours']} hours before it (strictly earlier). The criterion is true if the difference is at least {aki['creatinine_rise_mg_dl']} mg/dL. |",
            f"| 1 | {aki['creatinine_rise_window_hours']}시간 이내에 크레아티닌이 {aki['creatinine_rise_mg_dl']} mg/dL 이상 상승 | 크레아티닌 값을 직전 {aki['creatinine_rise_window_hours']}시간의 가장 낮은 이전 값(엄격히 이전)과 비교한다. 차이가 {aki['creatinine_rise_mg_dl']} mg/dL 이상이면 참이다. |"))
        w(t(f"| 2 | Creatinine is at least {aki['creatinine_ratio']} times the baseline within {aki['baseline_window_days']} days | A creatinine value is compared with the lowest earlier value in the {aki['baseline_window_days']} days before it (strictly earlier). The criterion is true if value >= {aki['creatinine_ratio']} x lowest earlier value. |",
            f"| 2 | {aki['baseline_window_days']}일 이내에 크레아티닌이 기준값의 {aki['creatinine_ratio']}배 이상 | 크레아티닌 값을 직전 {aki['baseline_window_days']}일의 가장 낮은 이전 값(엄격히 이전)과 비교한다. 값 >= {aki['creatinine_ratio']} x 가장 낮은 이전 값이면 참이다. |"))
        w(t(f"| 3 | Urine output below {aki['uo_threshold_ml_kg_h']} mL/kg/h for {aki['uo_consecutive_hours']} hours | See the urine rule below. |",
            f"| 3 | 소변량이 {aki['uo_consecutive_hours']}시간 동안 {aki['uo_threshold_ml_kg_h']} mL/kg/h 미만 | 아래 소변량 규칙을 참고한다. |"))
        w("")
        w(t(f"""**Creatinine series.** Only itemid 50912 counts (values from {aki['creatinine_plausible_mg_dl'][0]} to {aki['creatinine_plausible_mg_dl'][1]} mg/dL). The series of a stay starts 7 days before ICU admission and ends at ICU discharge. The pipeline joins the laboratory table with `subject_id`, because some earlier values have no `hadm_id`. Values with the same time are averaged. An AKI start needs a measurement time at or after `intime`. The first value of the series has no earlier value, so it cannot start AKI.""",
            f"""**크레아티닌 시계열.** itemid 50912만 사용한다(값 {aki['creatinine_plausible_mg_dl'][0]}~{aki['creatinine_plausible_mg_dl'][1]} mg/dL). 한 입실의 시계열은 ICU 입실 7일 전에 시작하고 ICU 퇴실에 끝난다. 일부 이전 값에는 `hadm_id`가 없으므로 파이프라인은 `subject_id`로 검사 테이블을 결합한다. 시각이 같은 값은 평균한다. AKI 시작은 `intime` 이후의 측정 시각이 필요하다. 시계열의 첫 값에는 이전 값이 없으므로 이 값으로는 AKI가 시작할 수 없다."""))
        w("")
        w(t(f"""**Urine rule.** The urine items (see section 4.3) are summed for each charting time. Each record covers the time since the previous record of the stay. The first record of a stay covers no time. For each record, the window is the {aki['uo_consecutive_hours']} hours up to and including its charting time. The window is valid if both conditions are true. (a) The intervals of the records in the window sum to at least {aki['uo_consecutive_hours']} and less than 12 hours. (b) Every interval in the window is at most {aki['uo_max_interval_hours']} hours. The rate is the volume sum of the window divided by the weight (`weight_kg`) and by the interval sum in hours. If the rate is below {aki['uo_threshold_ml_kg_h']} mL/kg/h, the criterion is true at the charting time of the record. A missing record is never zero output. The dataset also saves the start time of the reference rule without condition (b) (`onset_uo_reference_hour`).""",
            f"""**소변량 규칙.** 소변 항목(4.3절 참고)을 기록 시각마다 합산한다. 기록 하나는 같은 입실의 직전 기록 이후의 시간을 덮는다. 입실의 첫 번째 기록은 시간을 덮지 않는다. 각 기록의 구간은 그 기록 시각까지(시각 포함)의 {aki['uo_consecutive_hours']}시간이다. 다음 두 조건을 모두 만족하면 구간은 유효하다. (a) 구간 안 기록 간격의 합이 {aki['uo_consecutive_hours']}시간 이상 12시간 미만이다. (b) 구간 안의 모든 간격이 {aki['uo_max_interval_hours']}시간 이하이다. 속도는 구간의 소변량 합을 체중(`weight_kg`)과 간격의 합(시간)으로 나눈 값이다. 속도가 {aki['uo_threshold_ml_kg_h']} mL/kg/h 미만이면 그 기록의 시각에 기준이 참이다. 기록이 없는 시간을 소변량 0으로 보지 않는다. 데이터 세트는 조건 (b)가 없는 기준 규칙의 시작 시점(`onset_uo_reference_hour`)도 저장한다."""))
        w("")
        # ------------------------------------------------------------------ 4 features
        w(t("### 4. Features", "### 4. 피처"))
        w("")
        w(t("#### 4.1 General rules", "#### 4.1 일반 규칙"))
        w("")
        w(t(f"""- **Time window.** A measurement is used if its charting time is in [`intime`, time zero) and its storage time (`storetime`) is at or before time zero. This holds for `labevents`, `chartevents` and `outputevents`. Infusions (`inputevents`) and dialysis sessions (`procedureevents`) use their start time; the part of an infusion after time zero is cut off. Prescriptions use the start time before time zero and a stop time not before `intime`. The dialysis history item (225126) uses its charting time before time zero.
- **Hourly bins.** Hour h (0 to {T - 1}) is [`intime` + h hours, `intime` + h + 1 hours). A measurement belongs to the hour of its charting time.
- **Plausibility.** A raw value outside the range in the tables below is removed (set to missing) before the hourly aggregation. The wide table counts the removed values in `n_outlier_<variable>`.
- **Missing values.** A missing value stays missing. There is no imputation, no forward fill and no zero fill.
- **Masks.** For each hourly variable v, `v_obs` is 1 if hour h has a value, and 0 otherwise. `v_hsl` is the number of hours since the last hour with `v_obs` = 1 (0 if the hour has a value, empty before the first value).
- **Laboratory itemids with several items** (for example `na`) pool the values of all listed items. The hourly value is the mean of all pooled values in the hour.""",
            f"""- **시간 구간.** 기록 시각이 [`intime`, time zero)에 있고 저장 시각(`storetime`)이 time zero 이전 또는 같으면 그 측정값을 사용한다. 이 규칙은 `labevents`, `chartevents`, `outputevents`에 적용한다. 주입(`inputevents`)과 투석 세션(`procedureevents`)은 시작 시각을 사용하며, 주입의 time zero 이후 부분은 자른다. 처방은 시작 시각이 time zero 이전이고 중단 시각이 `intime`보다 앞서지 않아야 한다. 투석 문진 항목(225126)은 time zero 이전의 기록 시각을 사용한다.
- **시간 단위 구간.** h시간(0~{T - 1})은 [`intime` + h시간, `intime` + h + 1시간)이다. 측정값은 기록 시각이 속한 시간에 들어간다.
- **허용 범위.** 아래 표의 범위를 벗어난 원시 값은 시간별 집계 전에 제거한다(결측으로 바꾼다). wide 테이블의 `n_outlier_<변수>`가 제거한 값의 개수를 센다.
- **결측값.** 결측값은 결측으로 유지한다. 대치, 전방 채움, 0 채움이 없다.
- **마스크.** 시간별 변수 v마다 `v_obs`는 그 시간에 값이 있으면 1이고 없으면 0이다. `v_hsl`은 `v_obs` = 1인 마지막 시간 이후 경과 시간 수이다(값이 있는 시간은 0, 첫 값 이전은 비어 있다).
- **항목이 여러 개인 검사 변수**(예: `na`)는 나열한 모든 항목의 값을 합산한다. 그 시간의 값은 합산한 모든 값의 평균이다."""))
        w("")
        w(t("#### 4.2 Column names", "#### 4.2 칼럼 이름"))
        w("")
        w(t("| Pattern | Table | Meaning |", "| 패턴 | 테이블 | 의미 |")); w("| --- | --- | --- |")
        for a, b, c, d in [
            ("`<v>`", "hourly", "Hourly value of variable v", "변수 v의 시간별 값"),
            ("`<v>_obs`", "hourly", "1 if the hour has a value of v, otherwise 0", "그 시간에 v의 값이 있으면 1, 없으면 0"),
            ("`<v>_hsl`", "hourly", "Hours since the last value of v", "v의 마지막 값 이후 경과 시간"),
            ("`<v>_min`, `_max`, `_mean`", "wide", "Minimum, maximum and mean of the hourly values of v over hours 0 to 47 (hours without a value are skipped)", "시간별 값의 0~47시간 최솟값, 최댓값, 평균(값이 없는 시간은 건너뜀)"),
            ("`<v>_first`, `_last`", "wide", "Hourly value of v in the first and in the last hour that has a value", "값이 있는 첫 시간과 마지막 시간의 v 시간별 값"),
            ("`<v>_total`", "wide", "Sum of the hourly values of v (only for the variables that are volumes)", "v의 시간별 값의 합(부피 변수에만 있음)"),
            ("`<v>_n_hours_obs`", "wide", "Number of hours with a value of v (sum of `<v>_obs`)", "v의 값이 있는 시간의 수(`<v>_obs`의 합)"),
            ("`n_outlier_<v>`", "wide", "Number of raw values of v outside the plausible range", "허용 범위를 벗어난 v의 원시 값 개수"),
        ]:
            w(f"| {a} | {b} | {t(c, d)} |")
        w("")
        w(t(f"Variables that are volumes (they have `_total` and no `_min`, `_max`, `_mean`, `_first`, `_last`): {', '.join('`' + v + '`' for v in sorted(SUMS))}.",
            f"부피 변수(`_total`이 있고 `_min`, `_max`, `_mean`, `_first`, `_last`가 없음): {', '.join('`' + v + '`' for v in sorted(SUMS))}."))
        w("")
        w(t("#### 4.3 Measured variables (hourly table and wide table)", "#### 4.3 측정 변수(hourly 테이블과 wide 테이블)"))
        w("")
        w(t("Hourly rule: `mean` = mean of all values of the hour; `sum` = sum of the values of the hour. For output variables, the pipeline first sums all items at the same charting time. This sum is one event. It applies the range to the event. Then it sums the events of the hour.",
            "시간별 규칙: `mean` = 그 시간 모든 값의 평균, `sum` = 그 시간 값의 합. 배출량 변수는 파이프라인이 먼저 같은 기록 시각의 모든 항목을 합산한다. 이 합이 사건 하나이다. 파이프라인은 그 사건에 범위를 적용한다. 그 다음에 그 시간의 사건을 합산한다."))
        w("")
        w(t("| Variable | Meaning | Unit | MIMIC table | Itemids | Hourly rule | Plausible range |", "| 변수 | 의미 | 단위 | MIMIC 테이블 | Itemid | 시간별 규칙 | 허용 범위 |")); w("| --- | --- | --- | --- | --- | --- | --- |")
        for v, en, kr, u, tb, it, ag in VARS:
            w(f"| `{v}` | {t(en, kr)} | {u} | {tb} | {it if L == 'en' else VARS_KR_IDS(it)} | {ag} | {rng(v) if L == 'en' else rng_kr(v)} |")
        w("")
        w(t(f"Urine items: {I(ou['urine'])}. The pipeline does not count {not_out} as output (pre-admission output, irrigant fluid, blood loss and tube-feed residual).",
            f"소변 항목: {I(ou['urine'])}. 파이프라인은 {not_out}을 배출량으로 세지 않는다(입실 전 배출량, 세척액, 출혈량, 경관영양 잔여량)."))
        w("")
        w(t("#### 4.4 Derived hourly variables", "#### 4.4 파생 시간별 변수"))
        w("")
        w(t("| Variable | Derivation |", "| 변수 | 유도 방법 |")); w("| --- | --- |")
        w(t(f"| `intake_ml` | Records of `inputevents` with the unit mL and an amount above 0 and up to 10000 mL. The pipeline spreads the amount of a record over the hours that it overlaps with [`intime`, time zero): the share of an hour is (overlap time of the hour) / (total duration of the record). A record without duration goes entirely to its start hour. The hourly value is the sum of the shares. |",
            f"| `intake_ml` | `inputevents`의 단위가 mL이고 양이 0 초과 10000 mL 이하인 기록. 파이프라인은 기록의 양을 [`intime`, time zero)와 겹치는 시간들에 나누어 배분한다. 한 시간의 몫은 (그 시간의 겹치는 시간) / (기록의 전체 지속 시간)이다. 지속 시간이 없는 기록은 시작 시간에 모두 들어간다. 시간별 값은 몫의 합이다. |"))
        w(t(f"| `urine_ml_kg_h` | Urine output rate in mL/kg/h. Only records with an interval from the previous record of 1 second to 6 hours count. The pipeline spreads the volume of a record over the hours of its interval, in proportion to the overlap time. The hourly rate is (spread volume) / `weight_kg` / (covered time in hours). An hour needs at least 30 minutes of covered time. Rates outside {ranges['urine_ml_kg_h'][0]} to {ranges['urine_ml_kg_h'][1]} are removed. |",
            f"| `urine_ml_kg_h` | mL/kg/h 단위의 소변량 속도. 직전 기록과의 간격이 1초 이상 6시간 이하인 기록만 사용한다. 파이프라인은 기록의 소변량을 그 간격이 걸친 시간들에 겹치는 시간에 비례해 배분한다. 시간별 속도는 (배분한 소변량) / `weight_kg` / (덮은 시간, 시간 단위)이다. 한 시간에 최소 30분이 덮여야 한다. {ranges['urine_ml_kg_h'][0]}~{ranges['urine_ml_kg_h'][1]} 밖의 속도는 제거한다. |"))
        w(t(f"| `vasopressor_active` | 1 if a vasopressor infusion in `inputevents` (itemids {I(drugs['vasopressor_itemids'])}) covers the hour. An infusion that ends exactly at the start of an hour also marks that hour. Otherwise 0. |",
            f"| `vasopressor_active` | `inputevents`의 승압제 주입(itemid {I(drugs['vasopressor_itemids'])})이 그 시간을 덮으면 1. 정확히 시간 시작에 끝나는 주입도 그 시간을 표시한다. 아니면 0. |"))
        w(t(f"| `dialysis_active` | 1 if a dialysis session in `procedureevents` (itemids {I(ids['procedureevents']['dialysis'])}) covers the hour (same rule as `vasopressor_active`). Otherwise 0. |",
            f"| `dialysis_active` | `procedureevents`의 투석 세션(itemid {I(ids['procedureevents']['dialysis'])})이 그 시간을 덮으면 1(`vasopressor_active`와 같은 규칙). 아니면 0. |"))
        w(t("| `crrt_active` | The same as `dialysis_active`, for itemid 225802 (CRRT) only. |", "| `crrt_active` | `dialysis_active`와 같고, itemid 225802(CRRT)만 사용한다. |"))
        w(t("| `egfr_mdrd` | `175 x creatinine^-1.154 x age^-0.203 x 0.742 (if female)`, in mL/min/1.73 m2. `creatinine` is the hourly value, `age` is `age_at_icu`. No race term. |",
            "| `egfr_mdrd` | `175 x 크레아티닌^-1.154 x 나이^-0.203 x 0.742(여성이면)`, 단위 mL/min/1.73 m2. 크레아티닌은 시간별 값이고 나이는 `age_at_icu`이다. 인종 항은 없다. |"))
        w(t("| `egfr_cg` | Cockcroft-Gault: `(140 - age) x weight_kg / (72 x creatinine) x 0.85 (if female)`, in mL/min. |", "| `egfr_cg` | Cockcroft-Gault: `(140 - 나이) x weight_kg / (72 x 크레아티닌) x 0.85(여성이면)`, 단위 mL/min. |"))
        w(t("| `egfr_ckdepi` | CKD-EPI 2021: `142 x min(Scr/k, 1)^a x max(Scr/k, 1)^-1.200 x 0.9938^age x 1.012 (if female)`. Scr is the hourly creatinine. k = 0.7 (female) or 0.9 (male). a = -0.241 (female) or -0.302 (male). No race term. |",
            "| `egfr_ckdepi` | CKD-EPI 2021: `142 x min(Scr/k, 1)^a x max(Scr/k, 1)^-1.200 x 0.9938^나이 x 1.012(여성이면)`. Scr은 시간별 크레아티닌이다. k = 0.7(여성) 또는 0.9(남성). a = -0.241(여성) 또는 -0.302(남성). 인종 항은 없다. |"))
        w("")
        w(t("The three eGFR variables have a value only in hours with a creatinine value (`egfr_cg` also needs `weight_kg`). They have no `_obs` and no `_hsl`. The wide table has their `_min`, `_max`, `_mean`, `_first` and `_last`.",
            "eGFR 변수 세 개는 크레아티닌 값이 있는 시간에만 값이 있다(`egfr_cg`는 `weight_kg`도 필요하다). 이 변수에는 `_obs`와 `_hsl`이 없다. wide 테이블에는 `_min`, `_max`, `_mean`, `_first`, `_last`가 있다."))
        w("")
        w(t("#### 4.5 Static features and derived columns (wide table)", "#### 4.5 정적 피처와 파생 칼럼(wide 테이블)"))
        w("")
        ST = [
            ("`stay_id`, `subject_id`, `hadm_id`, `intime`, `anchor_year_group`, `gender`, `first_careunit`, `admission_type`, `hospital_expire_flag`", "MIMIC-IV columns, copied without change from `icustays`, `patients` and `admissions`.", "MIMIC-IV 칼럼. `icustays`, `patients`, `admissions`에서 그대로 복사한다."),
            ("`time_zero`", f"`intime` + {T} hours.", f"`intime` + {T}시간."),
            ("`age_at_icu`", "`patients.anchor_age` + (year of `intime` - `patients.anchor_year`).", "`patients.anchor_age` + (`intime`의 연도 - `patients.anchor_year`)."),
            ("`weight_kg`, `weight_src`", f"Earliest charted value of the first available source in this order: itemid {ch['weight_admission_kg'][0]} (kg), {ch['weight_admission_lbs'][0]} (pounds x 0.45359237), {ch['weight_daily_kg'][0]} (daily, kg). Only values charted before time zero and from {aki['weight_plausible_kg'][0]} to {aki['weight_plausible_kg'][1]} kg count. `weight_src` is `admission_kg`, `admission_lbs` or `daily`.",
             f"다음 순서로 처음 사용 가능한 출처의 가장 이른 기록 값: itemid {ch['weight_admission_kg'][0]}(kg), {ch['weight_admission_lbs'][0]}(파운드 x 0.45359237), {ch['weight_daily_kg'][0]}(일일, kg). time zero 이전에 기록했고 {aki['weight_plausible_kg'][0]}~{aki['weight_plausible_kg'][1]} kg인 값만 사용한다. `weight_src`는 `admission_kg`, `admission_lbs`, `daily` 중 하나이다."),
            ("`esrd_icd_current_adm`", f"1 if `diagnoses_icd` of this admission has an ICD-10 code {I(cfg['cohort']['esrd_icd10'])} or an ICD-9 code {I(cfg['cohort']['esrd_icd9'])}. The hospital assigns the codes at discharge.", f"이번 입원의 `diagnoses_icd`에 ICD-10 코드 {I(cfg['cohort']['esrd_icd10'])} 또는 ICD-9 코드 {I(cfg['cohort']['esrd_icd9'])}가 있으면 1. 병원이 이 코드를 퇴원 시 부여한다."),
            ("`esrd_icd_prior_adm`", "The same codes on an earlier admission of the same patient (earlier `admittime`).", "같은 환자의 이전 입원(더 이른 `admittime`)에 같은 코드가 있으면 1."),
            ("`dialysis_hx_item`", f"1 if `chartevents` of the stay has itemid {I(cfg['cohort']['esrd_chartevent_itemids'])} with the value 1, charted before time zero.", f"입실의 `chartevents`에 itemid {I(cfg['cohort']['esrd_chartevent_itemids'])}의 값이 1이고 time zero 이전에 기록했으면 1."),
            ("`esrd_chronic_dialysis`", "`esrd_icd_current_adm` OR `esrd_icd_prior_adm` OR `dialysis_hx_item`. It filters stays. It includes information coded at discharge, so it is not a model input.", "`esrd_icd_current_adm` 또는 `esrd_icd_prior_adm` 또는 `dialysis_hx_item`. 입실을 거르는 데 쓴다. 퇴원 시 부여한 정보를 포함하므로 모델 입력이 아니다."),
            ("`esrd_known_at_t0`", "`esrd_icd_prior_adm` OR `dialysis_hx_item`. It is known at time zero. Use it as the model input.", "`esrd_icd_prior_adm` 또는 `dialysis_hx_item`. time zero에 알 수 있다. 모델 입력으로 사용한다."),
            ("`ckd_icd_current_adm`, `ckd_icd_prior_adm`", "1 if `diagnoses_icd` has an ICD-10 code that starts with N18 (not N186) or an ICD-9 code 5851, 5852, 5853, 5854, 5855 or 5859, on this admission (current) or on an earlier admission (prior).", "`diagnoses_icd`에 N18로 시작하는 ICD-10 코드(N186 제외) 또는 ICD-9 코드 5851, 5852, 5853, 5854, 5855, 5859가 이번 입원(current) 또는 이전 입원(prior)에 있으면 1."),
            ("`creat_baseline_7d`, `creat_last_pre_icu`", f"From `labevents` itemid 50912 ({ranges['creatinine'][0]} to {ranges['creatinine'][1]} mg/dL, stored by time zero) with a charting time from 7 days before `intime` up to time zero: `creat_baseline_7d` is the lowest value, `creat_last_pre_icu` is the last value before `intime`.", f"`labevents` itemid 50912({ranges['creatinine'][0]}~{ranges['creatinine'][1]} mg/dL, time zero까지 저장)에서 기록 시각이 `intime` 7일 전부터 time zero까지인 값. `creat_baseline_7d`는 최저값이고 `creat_last_pre_icu`는 `intime` 이전의 마지막 값이다."),
            ("`n_dialysis_sessions_before_t0`, `first_dialysis_hour`", f"Number of rows of `procedureevents` (itemids {I(ids['procedureevents']['dialysis'])}) that start before time zero, and the smallest start time in hours from `intime` (empty if none).", f"time zero 이전에 시작한 `procedureevents` 행(itemid {I(ids['procedureevents']['dialysis'])})의 수와 `intime`부터 가장 이른 시작 시각까지의 시간(없으면 비어 있음)."),
            ("`vasopressor_hours`, `dialysis_hours`, `crrt_hours`", "Sum of `vasopressor_active`, `dialysis_active` and `crrt_active` over the 48 hours.", "48시간 동안 `vasopressor_active`, `dialysis_active`, `crrt_active`의 합."),
            ("`rrt_before_t0`", "1 if the first dialysis session of the stay (same itemids) starts at or before time zero.", "입실의 첫 투석 세션(같은 itemid)이 time zero 이전 또는 같은 시각에 시작하면 1."),
            ("`urine_ml_kg_h_overall`", f"(sum of the volumes of the valid records, see `urine_ml_kg_h`) / `weight_kg` / (sum of their intervals in hours). Values above 20 are set to missing.", "(유효한 기록의 소변량 합, `urine_ml_kg_h` 참고) / `weight_kg` / (그 간격의 합, 시간 단위). 20을 넘는 값은 결측으로 바꾼다."),
            ("`fluid_balance_ml`", "`intake_ml_total` - `urine_ml_total` - `drain_ml_total` - `stool_ml_total` - `other_output_ml_total` (a missing output total counts as 0). Empty if there is no intake value or no urine value.", "`intake_ml_total` - `urine_ml_total` - `drain_ml_total` - `stool_ml_total` - `other_output_ml_total`(없는 배출량 합은 0으로 센다). 섭취 값이나 소변 값이 없으면 비어 있다."),
            (f"`label_aki_next_{H}h`, `aki_by_creat`, `aki_by_uo`", f"Label (section 3). `aki_by_creat` is 1 if the first start by criterion 1 or 2 is in the prediction window. `aki_by_uo` is 1 if the first start by criterion 3 (with condition (b)) is in the prediction window. The label is 1 if one of them is 1.", f"라벨(3절). `aki_by_creat`는 기준 1 또는 2로 처음 시작한 시점이 예측 구간 안에 있으면 1. `aki_by_uo`는 기준 3(조건 (b) 포함)으로 처음 시작한 시점이 예측 구간 안에 있으면 1. 둘 중 하나가 1이면 라벨은 1이다."),
            ("`onset_aki_hour`, `onset_creat_hour`, `onset_uo_hour`, `onset_uo_reference_hour`", "Hours from `intime` to the first AKI start of the whole stay: by any criterion, by criteria 1 and 2, by criterion 3, and by the reference urine rule. Empty if there is none. These columns hold information after time zero. They are not model inputs.", "`intime`부터 입실 전체에서 첫 AKI 시작까지의 시간: 모든 기준, 기준 1과 2, 기준 3, 기준 소변량 규칙 각각의 값. 없으면 비어 있다. 이 칼럼은 time zero 이후의 정보를 담으므로 모델 입력이 아니다."),
            ("`n_kidney_relevant_classes`", "Number of the kidney-relevant drug flags (section 4.6) that are 1.", "값이 1인 신장 관련 약물 플래그(4.6절)의 수."),
        ]
        w(t("| Column | Derivation |", "| 칼럼 | 유도 방법 |")); w("| --- | --- |")
        for c, en, kr in ST: w(f"| {c} | {t(en, kr)} |")
        w("")
        w(t("#### 4.6 Drug features (wide table)", "#### 4.6 약물 피처(wide 테이블)"))
        w("")
        w(t(f"""1. **Orders.** An order of `prescriptions` counts if its start time is before time zero. Its stop time must not be before `intime`. If an order has no stop time, the start time replaces it. The pipeline matches orders to the stay with `hadm_id`.
2. **Drug classes.** Script 06 maps each order to ATC classes with the RxNav service of the US National Library of Medicine: NDC code -> RxNorm product -> ingredient -> ATC classes (levels 1 to 4). {n(info['ndc_mapped'])} of {n(info['ndc_total'])} NDC codes map. For the other orders, the pipeline looks up the drug name. Of {n(info['names_total'])} names, {n(info['names_exact'])} match exactly and {n(info['names_approx'])} match by approximate match. An approximate match needs rank 1 and the first word of the name inside the matched name. The NDC result has priority over the name result. {pct_atc}% of the {n(n_orders)} orders of the stays in the dataset that start before time zero have an ATC class.
3. **Route filter.** The pipeline drops an ATC code that does not fit the route of the order. Skin, eye and ear routes keep only ATC groups D and S. Other routes drop D and S. Other routes keep the intestinal anti-infectives A07 only for oral routes.""",
            f"""1. **처방.** `prescriptions`의 처방은 시작 시각이 time zero 이전이면 사용한다. 중단 시각은 `intime`보다 앞서면 안 된다. 중단 시각이 없으면 시작 시각이 대신한다. 파이프라인은 `hadm_id`로 처방을 입실에 연결한다.
2. **약물 분류.** 스크립트 06은 미국 국립의학도서관의 RxNav 서비스로 각 처방을 ATC 분류에 매핑한다: NDC 코드 -> RxNorm 제품 -> 성분 -> ATC 분류(1~4단계). NDC 코드 {n(info['ndc_total'])}개 중 {n(info['ndc_mapped'])}개가 매핑된다. 나머지 처방은 약물 이름으로 찾는다. 이름 {n(info['names_total'])}개 중 {n(info['names_exact'])}개가 정확히 일치하고 {n(info['names_approx'])}개가 근사 일치한다. 근사 일치는 순위가 1이어야 하고 이름의 첫 단어가 일치한 이름에 있어야 한다. NDC 결과가 이름 결과보다 우선한다. 데이터 세트 입실에서 time zero 이전에 시작한 처방 {n(n_orders)}건의 {pct_atc}%에 ATC 분류가 있다.
3. **경로 필터.** 파이프라인은 처방의 경로에 맞지 않는 ATC 코드를 버린다. 피부, 안과, 귀 경로는 ATC 그룹 D와 S만 유지한다. 그 밖의 경로는 D와 S를 버린다. 그 밖의 경로는 장내 항감염제 A07을 경구 경로에서만 유지한다."""))
        w("")
        w(t(f"**Kidney-relevant flags** (draft list, 1 if at least one matching order exists). Antibiotics and antivirals count only intravenous orders (`IV` route; for aminoglycosides also `IM`).",
            f"**신장 관련 플래그**(초안 목록, 일치하는 처방이 하나 이상 있으면 1). 항생제와 항바이러스제는 정맥 처방(경로 `IV`, 아미노글리코시드는 `IM`도)만 인정한다."))
        w("")
        w(t("| Column | Match rule | Route rule |", "| 칼럼 | 일치 규칙 | 경로 규칙 |")); w("| --- | --- | --- |")
        for (k, d), name in zip(drugs["kidney_relevant"].items(), kid):
            rule = (t("ATC code starts with ", "ATC 코드가 다음으로 시작: ") + ", ".join(d["atc"])) if "atc" in d else (t("ingredient name contains ", "성분 이름이 다음을 포함: ") + ", ".join(d["ingredients"]))
            route = (t("intravenous", "정맥") + (t(" or intramuscular", " 또는 근육") if d.get("im_too") else "")) if d.get("iv") else t("any", "제한 없음")
            w(f"| `{name}` | {rule} | {route} |")
        w("")
        w(t(f"**ATC level-3 flags** `atc3_<code>`: 1 if an order has an ATC code that starts with the 4 characters of `<code>`. The pipeline makes a flag for every class with an order in at least {int(drugs['atc_min_stay_fraction'] * 100)}% of the stays ({len(atc3)} flags): ",
            f"**ATC 3단계 플래그** `atc3_<코드>`: 처방의 ATC 코드가 `<코드>`의 4글자로 시작하면 1. 전체 입실의 {int(drugs['atc_min_stay_fraction'] * 100)}% 이상에 처방이 있는 분류마다 플래그를 만든다({len(atc3)}개): ") + ", ".join(atc3) + ".")
        w("")
        w(t("#### 4.7 Splits (`splits` table)", "#### 4.7 분할(`splits` 테이블)"))
        w("")
        w(t("Each split puts all stays of one patient (`subject_id`) in the same part.", "각 분할은 한 환자(`subject_id`)의 모든 입실을 같은 부분에 넣는다."))
        w("")
        w(t("| Column | Definition | Train | Validation | Test |", "| 칼럼 | 정의 | 학습 | 검증 | 테스트 |")); w("| --- | --- | --- | --- | --- |")
        sz = lambda s, p: f"{n(sp[(s, p)][0])} ({100 * sp[(s, p)][1] / sp[(s, p)][0]:.1f}%)"
        tc = cfg["splits"]["temporal"]
        w(f"| `split_random` | {t('Random by patient, 70/15/15 %, stratified by whether the patient has a label-1 stay (default)', '환자 단위 무작위 70/15/15 %, 환자의 라벨 1 입실 유무로 층화(기본값)')} | {sz('split_random', 'train')} | {sz('split_random', 'val')} | {sz('split_random', 'test')} |")
        w(f"| `split_temporal` | {t('By `anchor_year_group`', '`anchor_year_group` 기준')}: {t('train', '학습')} {', '.join(g.replace(' ', '') for g in tc['train'])}; {t('validation', '검증')} {', '.join(g.replace(' ', '') for g in tc['val'])}; {t('test', '테스트')} {', '.join(g.replace(' ', '') for g in tc['test'])} | {sz('split_temporal', 'train')} | {sz('split_temporal', 'val')} | {sz('split_temporal', 'test')} |")
        w(f"| `split_hybrid` | {t('Test = latest year group; earlier years random by patient 85/15 % train/validation', '테스트 = 가장 최근 연도 그룹. 이전 연도는 환자 단위 무작위로 학습 85%, 검증 15%')} | {sz('split_hybrid', 'train')} | {sz('split_hybrid', 'val')} | {sz('split_hybrid', 'test')} |")
        w("")
        w(t(f"The numbers in brackets are the shares of label 1. The seed of the random split is {cfg['splits']['seed']}.", f"괄호의 숫자는 라벨 1의 비율이다. 무작위 분할의 시드는 {cfg['splits']['seed']}이다."))
        w("")
        # ------------------------------------------------------------------ 5 limits
        w(t("### 5. Known limits", "### 5. 알려진 한계"))
        w("")
        w(t(f"""- **Selection.** The dataset keeps only stays of {T} hours or longer without AKI before time zero. A model applies only to such patients.
- **Urine criterion and charting frequency.** The urine criterion needs charting intervals of at most {aki['uo_max_interval_hours']} hours. A stay with rare urine charting cannot reach it. The `_n_hours_obs` columns measure charting frequency, so they can predict the label for a reason that is not clinical.
- **Drug data.** `prescriptions` has orders, not given doses. It has no intravenous contrast. The drug list is a draft that the clinical team has not reviewed.
- **Plausible ranges** are a draft that the clinical team has not reviewed.
- **Discharge codes.** The columns `esrd_icd_current_adm`, `ckd_icd_current_adm` and `esrd_chronic_dialysis` hold ICD codes that the hospital assigns at discharge. Do not use them as model inputs. The columns `label_*`, `aki_by_*`, `onset_*` and `hospital_expire_flag` hold outcome information. They are not model inputs.
- **Single hospital.** MIMIC-IV comes from one hospital. The dataset has no external validation.
- **eGFR** has no race term.""",
            f"""- **선택 효과.** 데이터 세트는 재원 {T}시간 이상이고 time zero 이전에 AKI가 없는 입실만 유지한다. 모델은 그런 환자에게만 적용된다.
- **소변량 기준과 기록 빈도.** 소변량 기준은 기록 간격이 {aki['uo_max_interval_hours']}시간 이하여야 한다. 소변 기록이 드문 입실은 이 기준에 도달할 수 없다. `_n_hours_obs` 칼럼은 기록 빈도를 나타내므로 임상과 무관한 이유로 라벨을 예측할 수 있다.
- **약물 데이터.** `prescriptions`에는 처방이 있고 실제 투여 용량은 없다. 정맥 조영제도 없다. 약물 목록은 임상팀이 아직 검토하지 않은 초안이다.
- **허용 범위**는 임상팀이 아직 검토하지 않은 초안이다.
- **퇴원 코드.** 칼럼 `esrd_icd_current_adm`, `ckd_icd_current_adm`, `esrd_chronic_dialysis`는 병원이 퇴원 시 부여하는 ICD 코드를 담는다. 모델 입력으로 사용하지 마십시오. 칼럼 `label_*`, `aki_by_*`, `onset_*`, `hospital_expire_flag`는 결과 정보를 담으므로 모델 입력이 아니다.
- **단일 병원.** MIMIC-IV는 한 병원의 데이터이다. 이 데이터 세트에는 외부 검증이 없다.
- **eGFR**에는 인종 항이 없다."""))
        w("")
        # ------------------------------------------------------------------ appendix
        w(t("### Appendix: all columns", "### 부록: 전체 칼럼"))
        w("")
        w(t(f"**Hourly table ({len(hourly_cols)} columns).**", f"**hourly 테이블({len(hourly_cols)}칼럼).**"))
        w("")
        w("```text"); w(", ".join(hourly_cols)); w("```")
        w("")
        w(t(f"**Wide table ({len(wide_cols)} columns).**", f"**wide 테이블({len(wide_cols)}칼럼).**"))
        w("")
        w("```text"); w(", ".join(wide_cols)); w("```")
        w("")
        return "\n".join(E)

    OUT.write_text(build("en") + "\n---\n\n" + build("kr"))
    print(f"{OUT}: {len(OUT.read_text().splitlines())} lines; hourly {len(hourly_cols)} and wide {len(wide_cols)} columns covered")


if __name__ == "__main__":
    main()
