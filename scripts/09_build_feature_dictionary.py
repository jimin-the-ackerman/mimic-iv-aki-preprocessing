"""Generate docs/feature_dictionary.md and docs/feature_dictionary_kr.md from the Parquet schemas.

Every column in hourly.parquet / wide.parquet / splits.parquet must be covered by a rule below; the script fails
otherwise, so the dictionary cannot drift from the files. Re-run after rebuilding the features.
"""
from pathlib import Path
import re
import duckdb, yaml


def check_inputs():
    """Stop with a clear message if an earlier pipeline step has not been run."""
    required = ['data/features/hourly.parquet', 'data/features/wide.parquet', 'data/features/splits.parquet']
    missing = [p for p in required if not Path(p).exists()]
    if missing:
        raise SystemExit("Missing input files (run the earlier steps first, see docs/pipeline.md; run from the project root):\n  " + "\n  ".join(missing))


def main():
    check_inputs()
    cfg = yaml.safe_load(open("config.yaml"))
    H = cfg["task"]["horizon_hours"]
    cols = lambda t: [r[0] for r in duckdb.sql(f"describe select * from 'data/features/{t}.parquet'").fetchall()]

    # var -> (English label, Korean label, unit, source)
    V = {
        "hr": ("Heart rate", "심박수", "bpm", "chartevents 220045"),
        "sbp": ("Systolic blood pressure (non-invasive and arterial, average)", "수축기 혈압(비침습 혈압과 동맥 혈압의 평균)", "mmHg", "chartevents 220179, 220050"),
        "dbp": ("Diastolic blood pressure (non-invasive and arterial, average)", "이완기 혈압(비침습 혈압과 동맥 혈압의 평균)", "mmHg", "chartevents 220180, 220051"),
        "mbp": ("Mean blood pressure (non-invasive and arterial, average)", "평균 혈압(비침습 혈압과 동맥 혈압의 평균)", "mmHg", "chartevents 220181, 220052"),
        "rr": ("Respiratory rate", "호흡수", "/min", "chartevents 220210"),
        "temp_c": ("Body temperature (Fahrenheit values are converted to Celsius)", "체온(화씨 값은 섭씨로 변환)", "°C", "chartevents 223762, 223761"),
        "weight_daily": ("Daily weight", "일일 체중", "kg", "chartevents 224639"),
        "dial_blood_flow": ("Dialysis blood flow", "투석 혈류량", "mL/min", "chartevents 224144"),
        "dialysate_rate": ("Dialysate flow rate", "투석액 유량", "mL/h", "chartevents 224154"),
        "ultrafiltrate_ml": ("Ultrafiltrate output", "한외여과량", "mL", "chartevents 226457"),
        "creatinine": ("Serum creatinine", "혈청 크레아티닌", "mg/dL", "labevents 50912"),
        "creatinine_wb": ("Whole-blood creatinine (blood gas analyzer)", "전혈(혈액가스 분석기) 크레아티닌", "mg/dL", "labevents 52024"),
        "bun": ("Blood urea nitrogen (BUN)", "혈액요소질소(BUN)", "mg/dL", "labevents 51006"),
        "urine_creat": ("Urine creatinine", "소변 크레아티닌", "mg/dL", "labevents 51082"),
        "na": ("Sodium (chemistry and whole blood)", "나트륨(화학검사 값과 전혈 값)", "mEq/L", "labevents 50983, 50824"),
        "k": ("Potassium (chemistry and whole blood)", "칼륨(화학검사 값과 전혈 값)", "mEq/L", "labevents 50971, 50822"),
        "cl": ("Chloride (chemistry and whole blood)", "염소(화학검사 값과 전혈 값)", "mEq/L", "labevents 50902, 50806"),
        "hco3": ("Bicarbonate (HCO3)", "중탄산염(HCO3)", "mEq/L", "labevents 50882, 50803"),
        "phosphate": ("Phosphate", "인산염", "mg/dL", "labevents 50970"),
        "mg": ("Magnesium", "마그네슘", "mg/dL", "labevents 50960"),
        "uric_acid": ("Uric acid", "요산", "mg/dL", "labevents 51007"),
        "urine_ml": ("Urine output", "소변량", "mL", "outputevents (Foley, void, catheters, nephrostomy, OR urine, PACU urine)"),
        "drain_ml": ("Drain output", "배액량", "mL", "outputevents (see config.yaml itemids.outputevents.drainage)"),
        "stool_ml": ("Stool and ostomy output", "대변량(장루 배출량 포함)", "mL", "outputevents 226579, 226580, 226582, 226583"),
        "other_output_ml": ("Other output (all items that are not urine, drain or stool)", "기타 배출량(소변, 배액, 대변이 아닌 모든 항목)", "mL", "outputevents (all remaining items)"),
        "urine_ml_kg_h": ("Urine output rate (per kg of weight)", "소변량 속도(체중 1 kg당)", "mL/kg/h", "outputevents, weight_kg"),
        "intake_ml": ("Fluid and infusion intake", "수액과 주입액 섭취량", "mL", "inputevents (items in mL, with drug infusions)"),
    }
    COMPUTED = {
        "egfr_mdrd": ("eGFR from the MDRD equation, calculated from the hourly creatinine (no race term)", "MDRD 식으로 구한 eGFR(시간별 크레아티닌 사용, 인종 항 없음)", "mL/min/1.73m²"),
        "egfr_cg": ("eGFR from the Cockcroft-Gault equation (uses the admission weight)", "Cockcroft-Gault 식으로 구한 eGFR(입실 시 체중 사용)", "mL/min"),
        "egfr_ckdepi": ("eGFR from the CKD-EPI 2021 creatinine equation", "CKD-EPI 2021 크레아티닌 식으로 구한 eGFR", "mL/min/1.73m²"),
    }
    FLAGS = {"vasopressor_active": ("A vasopressor infusion runs in the hour", "해당 시간에 승압제를 주입한다"),
             "dialysis_active": ("Dialysis (hemodialysis, CRRT or peritoneal dialysis) runs in the hour", "해당 시간에 투석(혈액투석, CRRT 또는 복막투석)을 한다"),
             "crrt_active": ("CRRT runs in the hour", "해당 시간에 CRRT를 한다")}
    STAT_KR = {"min": "최솟값", "max": "최댓값", "mean": "평균", "first": "첫 값", "last": "마지막 값"}
    STAT_EN = {"min": "Minimum", "max": "Maximum", "mean": "Mean", "first": "First value", "last": "Last value"}
    SUM_VARS = {"urine_ml", "drain_ml", "stool_ml", "other_output_ml", "ultrafiltrate_ml", "intake_ml"}
    STATIC = {  # column -> (English, Korean, role)
        "stay_id": ("ICU stay identifier", "ICU 입실 식별자", "id"), "subject_id": ("Patient identifier. The splits use this column", "환자 식별자. 분할이 이 칼럼을 사용한다", "id"),
        "hadm_id": ("Hospital admission identifier", "입원 식별자", "id"), "intime": ("ICU admission time", "ICU 입실 시각", "id"),
        "time_zero": ("Prediction time (time zero): `icustays.intime` plus 48 hours", "예측 시점(time zero): `icustays.intime` + 48시간", "id"),
        "anchor_year_group": ("MIMIC anchor year group. The temporal splits use this column", "MIMIC 기준 연도 그룹. 시간 기반 분할이 이 칼럼을 사용한다", "id"),
        "age_at_icu": ("Age at ICU admission (years): `patients.anchor_age` plus the years from `patients.anchor_year` to `icustays.intime`", "ICU 입실 시 나이(세): `patients.anchor_age`에 `patients.anchor_year`부터 `icustays.intime`까지의 연수를 더한 값", "feature"), "gender": ("Sex (F or M)", "성별(F 또는 M)", "feature"),
        "first_careunit": ("First ICU care unit", "첫 ICU 병동", "feature"), "admission_type": ("Hospital admission type", "입원 유형", "feature"),
        "weight_kg": ("Weight in kg for eGFR and urine output. The column weight_src shows the source. The MIMIC-IV items are in `itemids.md`", "eGFR과 소변량 계산에 쓰는 체중(kg). 출처는 칼럼 weight_src에 있다. MIMIC-IV 항목은 `itemids_kr.md`에 있다", "feature"),
        "weight_src": ("Source of the column weight_kg", "weight_kg 칼럼의 출처", "feature"),
        "esrd_chronic_dialysis": ("ESRD or chronic dialysis flag. Use it to filter stays. It uses `diagnoses_icd` and the history item in `itemids.md`. It includes ICD codes from the current admission (coded at discharge). Do not use it as a model input", "ESRD 또는 만성 투석 플래그. 입실을 걸러낼 때 사용한다. `diagnoses_icd`와 `itemids_kr.md`의 문진 항목을 사용한다. 현재 입원의 ICD 코드(퇴원 시 부여)를 포함하므로 모델 입력으로 사용하지 마십시오", "caution"),
        "esrd_known_at_t0": ("ESRD or chronic dialysis flag without the ICD codes of the current admission. Source: `diagnoses_icd` and `chartevents`. Use this column as the model input", "현재 입원의 ICD 코드를 뺀 ESRD 또는 만성 투석 플래그이다. 출처: `diagnoses_icd`와 `chartevents`. 모델 입력으로 이 칼럼을 사용하십시오", "feature"),
        "esrd_icd_current_adm": ("ESRD ICD code on this admission (coded at discharge). Source: `diagnoses_icd`", "이번 입원의 ESRD ICD 코드(퇴원 시 부여). 출처: `diagnoses_icd`", "caution"),
        "esrd_icd_prior_adm": ("ESRD ICD code on an earlier admission. Source: `diagnoses_icd`", "이전 입원의 ESRD ICD 코드. 출처: `diagnoses_icd`", "feature"),
        "dialysis_hx_item": ("The dialysis history at admission is yes (the item is in `itemids.md`), charted before time zero. Source: `chartevents`", "입원 시 투석 문진의 값이 예이다(항목은 `itemids_kr.md`에 있다). time zero 이전에 기록했다. 출처: `chartevents`", "feature"),
        "ckd_icd_prior_adm": ("CKD ICD code on an earlier admission (stage 1 to 5 or unspecified, no dialysis). Source: `diagnoses_icd`", "이전 입원의 CKD ICD 코드(1~5기 또는 미분류, 투석 제외). 출처: `diagnoses_icd`", "feature"),
        "ckd_icd_current_adm": ("The same CKD ICD codes on this admission (coded at discharge). Source: `diagnoses_icd`", "이번 입원의 동일한 CKD ICD 코드(퇴원 시 부여). 출처: `diagnoses_icd`", "caution"),
        "creat_baseline_7d": ("Lowest creatinine from 7 days before ICU admission to time zero. Source: `labevents`, itemid 50912", "ICU 입실 7일 전부터 time zero까지의 최저 크레아티닌. 출처: `labevents`, itemid 50912", "feature"),
        "creat_last_pre_icu": ("Last creatinine in the 7 days before ICU admission. Source: `labevents`, itemid 50912", "ICU 입실 전 7일 중 마지막 크레아티닌. 출처: `labevents`, itemid 50912", "feature"),
        "n_dialysis_sessions_before_t0": ("Number of dialysis sessions that start before time zero. Source: `procedureevents`", "time zero 이전에 시작한 투석 횟수. 출처: `procedureevents`", "feature"),
        "first_dialysis_hour": ("Hour of the first dialysis start, counted from ICU admission. Source: `procedureevents`", "첫 투석 시작 시점(ICU 입실 후 경과 시간). 출처: `procedureevents`", "feature"),
        "vasopressor_hours": ("Number of hours with a vasopressor infusion. Source: `inputevents`", "승압제를 주입한 시간 수. 출처: `inputevents`", "feature"),
        "dialysis_hours": ("Number of hours with dialysis. Source: `procedureevents`", "투석한 시간 수. 출처: `procedureevents`", "feature"),
        "crrt_hours": ("Number of hours with CRRT. Source: `procedureevents`", "CRRT를 한 시간 수. 출처: `procedureevents`", "feature"),
        "urine_ml_kg_h_overall": ("Urine output rate over hours 0 to 47. Total volume divided by the weight and by the covered hours. Source: `outputevents` and `weight_kg`", "0~47시간의 소변량 속도. 총 소변량을 체중과 커버한 시간으로 나눈 값이다. 출처: `outputevents`와 `weight_kg`", "feature"),
        "fluid_balance_ml": ("Intake minus urine, drain, stool and other output over hours 0 to 47. Empty if no intake value or no urine value exists. Source: `inputevents` and `outputevents`", "0~47시간의 섭취량에서 소변량, 배액량, 대변량, 기타 배출량을 뺀 값. 섭취 값이나 소변 값이 없으면 비어 있다. 출처: `inputevents`와 `outputevents`", "feature"),
        "rrt_before_t0": ("Dialysis starts before time zero. Source: `procedureevents`", "time zero 이전에 투석을 시작했다. 출처: `procedureevents`", "feature"),
        f"label_aki_next_{H}h": ("LABEL. The value is 1 if the first AKI starts in the prediction window. Source: `labevents`, `outputevents` and `weight_kg`", "라벨. 예측 구간 안에서 첫 AKI가 시작하면 값은 1이다. 출처: `labevents`, `outputevents`, `weight_kg`", "label"),
        "aki_by_creat": ("Label from the creatinine criteria only. Source: `labevents`", "크레아티닌 기준만으로 만든 라벨. 출처: `labevents`", "label"),
        "aki_by_uo": ("Label from the urine output criterion only. Source: `outputevents` and `weight_kg`", "소변량 기준만으로 만든 라벨. 출처: `outputevents`와 `weight_kg`", "label"),
        "onset_aki_hour": ("Hour of AKI start (any criterion, whole ICU stay). Source: `labevents` and `outputevents`", "AKI 시작 시점(어느 기준이든, ICU 재원 전체, 입실 후 경과 시간). 출처: `labevents`와 `outputevents`", "label"),
        "onset_creat_hour": ("Hour of AKI start by the creatinine criteria. Source: `labevents`", "크레아티닌 기준 AKI 시작 시점(입실 후 경과 시간). 출처: `labevents`", "label"),
        "onset_uo_hour": ("Hour of AKI start by the urine output criterion. Source: `outputevents`", "소변량 기준 AKI 시작 시점(입실 후 경과 시간). 출처: `outputevents`", "label"),
        "onset_uo_reference_hour": ("Hour of AKI start by the reference urine rule. Source: `outputevents`", "기준 소변량 규칙의 AKI 시작 시점(입실 후 경과 시간). 출처: `outputevents`", "label"),
        "hospital_expire_flag": ("Death in hospital. This outcome is not known at time zero", "원내 사망. time zero에는 이 결과를 알 수 없다", "label"),
        "split_random": ("Random split by patient (default)", "환자 단위 무작위 분할(기본값)", "split"),
        "split_temporal": ("Split by year group", "연도 그룹 분할", "split"),
        "split_hybrid": ("The latest year group is test. The other year groups split at random", "가장 최근 연도 그룹이 테스트이고, 나머지 연도 그룹은 무작위로 나눈다", "split"),
    }

    # names of the level-4 classes under each level-3 ATC class, taken from the drug map built by 06
    _m = duckdb.sql("select atc_codes, atc_names from 'data/external/drug_map.parquet' where atc_codes <> ''").df()
    ATC3_NAMES = {}
    for _codes, _names in zip(_m.atc_codes, _m.atc_names):
        for _c, _n in zip(_codes.split(";"), _names.split(";")):
            if len(_c) >= 4 and _n not in ATC3_NAMES.setdefault(_c[:4], []): ATC3_NAMES[_c[:4]].append(_n)

    def describe(c, table):
        """Return (English, Korean, role) for a column, or None."""
        if c in STATIC: return STATIC[c]
        if table == "hourly" and c == "hour": return ("Hour since ICU admission (0 to 47)", "ICU 입실 후 경과 시간(0~47)이다.", "id")
        m = re.fullmatch(r"(.+?)(_obs|_hsl)", c)
        if m and (m.group(1) in V):
            e, k, u, _ = V[m.group(1)]
            en, ko = ((f"{e}. The value is 1 if the hour has a value. Otherwise 0", f"{k}. 해당 시간에 값이 있으면 1이다. 없으면 0이다.") if m.group(2) == "_obs"
                      else (f"{e}. Hours since the last value. Empty if no value exists yet", f"{k}. 마지막 값 이후 경과 시간이다. 아직 값이 없으면 비어 있다."))
            return (en, ko, "feature")
        if c in V: return (f"{V[c][0]} ({V[c][2]}). Hourly " + ("total" if c in SUM_VARS else "mean"), f"{V[c][1]}({V[c][2]}). 시간별 " + ("합계이다." if c in SUM_VARS else "평균이다."), "feature")
        if c in COMPUTED: return (f"{COMPUTED[c][0]} ({COMPUTED[c][2]})", f"{COMPUTED[c][1]}({COMPUTED[c][2]}).", "feature")
        if c in FLAGS: return (FLAGS[c][0] + ". The value is 1 if this is true. Otherwise 0", FLAGS[c][1] + ". 이 조건이 참이면 값은 1이다. 아니면 0이다.", "feature")
        m = re.fullmatch(r"(.+?)_(min|max|mean|first|last)", c)
        if m and (m.group(1) in V or m.group(1) in COMPUTED):
            b = m.group(1); e, k = (V[b][:2] if b in V else COMPUTED[b][:2])
            return (f"{e}. {STAT_EN[m.group(2)]} of the hourly values (hours 0 to 47)", f"{k}. 0~47시간 시간별 값의 {STAT_KR[m.group(2)]}이다.", "feature")
        m = re.fullmatch(r"(.+?)_(n_hours_obs|total)", c)
        if m and m.group(1) in V:
            e, k = V[m.group(1)][:2]
            en, ko = ((f"{e}. Number of hours with a value", f"{k}. 값이 있는 시간의 수이다.") if m.group(2) == "n_hours_obs"
                      else (f"{e}. Total over hours 0 to 47", f"{k}. 0~47시간의 합계이다."))
            return (en, ko, "feature")
        m = re.fullmatch(r"n_outlier_(.+)", c)
        if m and m.group(1) in V: return (f"{V[m.group(1)][0]}. Number of values outside the plausible range", f"{V[m.group(1)][1]}. 허용 범위를 벗어난 값의 개수이다.", "feature")
        m = re.fullmatch(r"atc_([A-Z0-9]+)_(.+)", c)
        if m and m.group(2) in cfg["drugs"]["kidney_relevant"]:
            k = cfg["drugs"]["kidney_relevant"][m.group(2)]
            iv = ". Only intravenous orders count" + (" (intramuscular too)" if k.get("im_too") else "") if k.get("iv") else ""
            ivk = " 정맥(IV) 처방만 인정한다." + (" 근육(IM) 처방도 인정한다." if k.get("im_too") else "") if k.get("iv") else ""
            return (f"Kidney-relevant drug class (draft list): {k['label']}. ATC {'/'.join(k['atc'])}. The order starts before time zero{iv}. Source: `prescriptions` and the drug map",
                    f"신장 관련 약물군(초안): {k['label']}. ATC {'/'.join(k['atc'])}. time zero 이전에 시작한 처방이 있으면 1이다.{ivk} 출처: `prescriptions`와 약물 맵.", "feature")
        m = re.fullmatch(r"drug_(.+)", c)
        if m and m.group(1) in cfg["drugs"]["kidney_relevant"]:
            k = cfg["drugs"]["kidney_relevant"][m.group(1)]
            return (f"Kidney-relevant drug (draft list): {k['label']}. The match uses the ingredient name. The order starts before time zero. Only intravenous orders count. Source: `prescriptions` and the drug map",
                    f"신장 관련 약물(초안): {k['label']}. 성분명으로 매칭한다. time zero 이전에 시작한 처방이 있으면 1이다. 정맥(IV) 처방만 인정한다. 출처: `prescriptions`와 약물 맵.", "feature")
        m = re.fullmatch(r"atc3_([A-Z][0-9]{2}[A-Z])", c)
        if m:
            ex = "; ".join(ATC3_NAMES.get(m.group(1), [])[:1])
            return (f"Any drug of ATC class {m.group(1)} (level 3). The order starts before time zero. Source: `prescriptions` and the drug map" + (f". Example class: {ex}" if ex else ""),
                    f"time zero 이전에 시작한 처방 중 ATC {m.group(1)}(3단계) 약물이 있으면 1이다. 출처: `prescriptions`와 약물 맵." + (f" 예시 분류: {ex}." if ex else ""), "feature")
        if c == "n_kidney_relevant_classes":
            return ("Number of kidney-relevant drug classes with an order that starts before time zero", "time zero 이전에 시작한 처방이 있는 신장 관련 약물군의 수이다.", "feature")
        return None

    # every base variable name must appear in the item tables, so that the lookup in itemids.md is complete
    for doc in ("docs/itemids.md", "docs/itemids_kr.md"):
        text = Path(doc).read_text()
        absent = [v for v in list(V) + list(FLAGS) if f"`{v}`" not in text]
        if absent:
            raise SystemExit(f"{doc} does not list these variable names: {absent}")
    tables = {"hourly": cols("hourly"), "wide": cols("wide"), "splits": cols("splits")}
    # a column has the origin MIMIC if its name is exactly a column name in the MIMIC-IV tables that the pipeline reads
    mimic_cols, missing = set(), []
    for module, names in cfg["mimic_tables"].items():
        for n in names:
            path = f"data/mimiciv/3.1_parquet/{module}/{n}.parquet"
            if not Path(path).exists(): missing.append(path); continue
            mimic_cols |= {r[0] for r in duckdb.sql(f"describe select * from '{path}'").fetchall()}
    if missing:
        raise SystemExit("Missing Parquet tables (run step 01 first):\n  " + "\n  ".join(missing))
    ORIGIN = lambda c, kr: ("MIMIC 원본" if kr else "MIMIC") if c in mimic_cols else ("파생" if kr else "Derived")
    miss = [(t, c) for t, cs in tables.items() for c in cs if describe(c, t) is None]
    assert not miss, f"columns without a description: {miss}"

    ROLE = {"id": ("ID or time", "식별자 또는 시간"), "feature": ("Model input (feature)", "모델 입력(피처)"),
            "caution": ("Caution: contains information that the hospital codes at discharge. Do not use as a model input", "주의: 퇴원 시 병원이 부여하는 정보를 포함한다. 모델 입력으로 사용하지 마십시오"),
            "label": ("Label or outcome. Do not use as a model input", "라벨 또는 결과. 모델 입력으로 사용하지 마십시오"), "split": ("Split assignment", "분할 지정")}

    def write(path, kr):
        i = 1 if kr else 0
        L = []
        L.append("# 피처 사전" if kr else "# Feature dictionary")
        L.append("")
        L.append("스크립트 `scripts/09_build_feature_dictionary.py`가 Parquet 스키마로 이 파일을 생성한다. 이 파일을 직접 수정하지 마십시오." if kr
                 else "The script `scripts/09_build_feature_dictionary.py` generates this file from the Parquet schemas. Do not edit this file by hand.")
        L.append("")
        L.append("## 읽는 방법" if kr else "## How to read this dictionary")
        rules_en = [
            "The `wide` table has one row for each ICU stay. The `hourly` table has one row for each stay and each hour from 0 to 47.",
            "Hour h covers the time from the ICU admission time plus h hours to the ICU admission time plus h+1 hours.",
            "A column that ends in `_obs` is 1 for an hour with a value. A column that ends in `_hsl` shows the hours since the last value.",
            "The column Origin shows `MIMIC` if the column name is exactly a column name in the MIMIC-IV tables that the pipeline reads. It shows `Derived` if the pipeline creates the name. The values of a derived column come from MIMIC-IV data and from the rules of the pipeline.",
            "The columns `n_outlier_*` count the values outside the plausible range.",
            "Do not use columns with the role Label or Caution as model inputs. Caution columns contain ICD codes from the current admission. The hospital assigns these codes at discharge. Use `esrd_known_at_t0` and `ckd_icd_prior_adm` instead.",
            "The urine output rate uses only charting intervals of 6 hours or less. The code spreads each volume over the hours that its interval covers. An hour needs at least 30 minutes of coverage.",
            "The rules for the time window, missing values, implausible values, eGFR and drug classes are in `cohort_definition.md`. To find the MIMIC-IV items behind a measured variable, look up the base name of the column in `itemids.md`. The description of each other column names its MIMIC-IV source.",
        ]
        rules_kr = [
            "`wide` 테이블은 ICU 입실 1건당 1행이다. `hourly` 테이블은 입실 1건과 0~47시간의 각 시간마다 1행이다.",
            "h시간 행은 입실 시각 + h시간부터 입실 시각 + (h+1)시간까지를 나타낸다.",
            "`_obs`로 끝나는 칼럼은 값이 있는 시간에 1이다. `_hsl`로 끝나는 칼럼은 마지막 값 이후 경과 시간이다.",
            "칼럼 \"출처\"는 칼럼 이름이 파이프라인이 읽는 MIMIC-IV 테이블의 칼럼 이름과 정확히 같으면 `MIMIC 원본`이다. 파이프라인이 이름을 만들었으면 `파생`이다. 파생 칼럼의 값은 MIMIC-IV 데이터와 파이프라인의 규칙에서 나온다.",
            "`n_outlier_*` 칼럼은 허용 범위를 벗어난 값의 개수를 센다.",
            "역할이 라벨 또는 주의인 칼럼을 모델 입력으로 사용하지 마십시오. 주의 칼럼은 현재 입원의 ICD 코드를 포함한다. 병원이 이 코드를 퇴원 시 부여한다. 대신 `esrd_known_at_t0`와 `ckd_icd_prior_adm`을 사용하십시오.",
            "소변량 속도는 기록 간격이 6시간 이하인 경우에만 계산한다. 코드는 각 소변량을 그 간격이 걸친 시간들에 나누어 배분한다. 한 시간에 최소 30분의 간격이 걸쳐야 한다.",
            "시간 구간, 결측값, 비현실적 값, eGFR, 약물군의 규칙은 `cohort_definition_kr.md`에 있다. 측정 변수 뒤에 있는 MIMIC-IV 항목을 찾으려면 칼럼의 기본 이름을 `itemids_kr.md`에서 찾으십시오. 다른 칼럼의 설명에는 MIMIC-IV 출처가 있다.",
        ]
        L += [f"- {r}" for r in (rules_kr if kr else rules_en)]
        for t, cs in tables.items():
            L += ["", f"## {t}.parquet ({len(cs)} " + ("칼럼)" if kr else "columns)"), ""]
            L.append("| 칼럼 | 출처 | 설명 | 역할 |" if kr else "| Column | Origin | Description | Role |")
            L.append("| --- | --- | --- | --- |")
            for c in cs:
                d = describe(c, t)
                L.append(f"| `{c}` | {ORIGIN(c, kr)} | {d[i]} | {ROLE[d[2]][i]} |")
        open(path, "w").write("\n".join(L) + "\n")

    write("docs/feature_dictionary.md", False)
    write("docs/feature_dictionary_kr.md", True)
    print({t: len(cs) for t, cs in tables.items()}, "-> docs/feature_dictionary.md, docs/feature_dictionary_kr.md")


if __name__ == "__main__":
    main()
